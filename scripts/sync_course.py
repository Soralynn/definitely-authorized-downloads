"""Download one course, upload each lesson, and persist verified progress in Drive."""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import requests
import yt_dlp
from kodekloud_downloader.main import create_file_path, download_resource_lesson
from kodekloud_downloader.models.helper import fetch_course_detail


class TransferError(RuntimeError):
    pass


class Drive:
    def __init__(self, destination):
        if not re.fullmatch(r"[A-Za-z0-9_-]+:[^\r\n]*", destination):
            raise ValueError("Drive destination must be remote:folder")
        self.destination = destination.rstrip("/")

    def target(self, relative):
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative:
            raise ValueError("Unsafe remote path")
        return self.destination + "/" + str(path)

    def run(self, *args):
        result = subprocess.run(
            ["rclone", *args],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode:
            raise TransferError(
                f"Drive operation {args[0]} failed (exit {result.returncode}). "
                "Check RCLONE_CONFIG, the remote name, connection, and storage quota."
            )
        return result.stdout

    def inventory(self):
        self.run("mkdir", self.destination)
        rows = json.loads(
            self.run("lsjson", self.destination, "--recursive", "--files-only", "--hash")
        )
        return {row["Path"]: row for row in rows}

    def read_json(self, relative):
        return json.loads(self.run("cat", self.target(relative)))

    def upload(self, path, relative):
        self.run("copyto", str(path), self.target(relative), "--checksum", "--retries", "3")
        remote = json.loads(self.run("lsjson", self.target(relative), "--stat", "--hash"))
        expected = metadata(path, relative)
        if remote.get("Size") != expected["size"] or remote_md5(remote) != expected["md5"]:
            raise TransferError("Drive checksum verification failed; local file retained.")
        return expected


def remote_md5(remote):
    hashes = {key.lower(): value for key, value in remote.get("Hashes", {}).items()}
    return hashes.get("md5", "").lower()


def metadata(path, relative):
    digest = hashlib.md5()  # Transfer checksum only, not a security primitive.
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": relative, "size": Path(path).stat().st_size, "md5": digest.hexdigest()}


def is_complete(record, inventory, course_id, lesson_id, quality):
    if not isinstance(record, dict) or record.get("version") != 1:
        return False
    if (record.get("course"), record.get("lesson"), record.get("quality")) != (
        course_id,
        lesson_id,
        quality,
    ):
        return False
    files = record.get("files")
    if not isinstance(files, list) or not files:
        return False
    for file in files:
        if not isinstance(file, dict):
            return False
        remote = inventory.get(file.get("path"), {})
        if file.get("size", 0) <= 0 or remote.get("Size") != file.get("size"):
            return False
        if not file.get("md5") or remote_md5(remote) != file["md5"]:
            return False
    return True


def checkpoint_name(course_id, lesson_id, quality):
    identity = f"{course_id}/{lesson_id}/{quality}".encode()
    return ".progress/" + hashlib.sha256(identity).hexdigest() + ".json"


def upload_and_record(drive, files, root, state_path, course_id, lesson_id, quality):
    records = []
    for file in files:
        relative = file.resolve().relative_to((root / "KodeKloud").resolve()).as_posix()
        records.append(drive.upload(file, relative))
    record = {
        "version": 1,
        "course": course_id,
        "lesson": lesson_id,
        "quality": quality,
        "files": records,
    }
    checkpoint = root / state_path
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps(record), encoding="utf-8")
    drive.upload(checkpoint, state_path)
    # All content and its completion record are now verified remotely.
    for file in files:
        file.unlink()
    checkpoint.unlink()


def download_video(url, path, quality):
    completed = []
    options = {
        "format": f"bestvideo[height<={quality[:-1]}]+bestaudio/best[height<={quality[:-1]}]/best",
        "outtmpl": str(path) + ".%(ext)s",
        "merge_output_format": "mkv",
        "http_headers": {"Referer": "https://learn.kodekloud.com/"},
        "continuedl": True,
        "concurrent_fragment_downloads": 4,
        "post_hooks": [lambda filename: completed.append(Path(filename))],
        "quiet": True,
        "no_warnings": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.download([url])
    if not completed or any(not file.is_file() or not file.stat().st_size for file in completed):
        raise TransferError("Video download did not produce a completed file.")
    return completed


def run_course(course, session, drive, root, quality="1080p"):
    inventory = drive.inventory()
    completed = skipped = unsupported = 0
    for module_index, module in enumerate(course.modules, 1):
        for lesson_index, lesson in enumerate(module.lessons, 1):
            state_path = checkpoint_name(course.id, lesson.id, quality)
            if state_path in inventory:
                record = drive.read_json(state_path)
                if is_complete(record, inventory, course.id, lesson.id, quality):
                    print(f"SKIP verified lesson: {lesson.title}", flush=True)
                    skipped += 1
                    continue
            print(f"Processing: {lesson.title}", flush=True)
            path = create_file_path(
                root, course.title, module_index, module.title, lesson_index, lesson.title
            )
            if lesson.type == "video":
                response = session.get(
                    f"https://learn-api.kodekloud.com/api/lessons/{lesson.id}",
                    params={"course_id": course.id},
                    timeout=45,
                )
                if response.status_code in (401, 403):
                    raise TransferError(
                        f"KodeKloud returned {response.status_code}. Refresh KK_COOKIES "
                        "and confirm your account is enrolled and can access the course."
                    )
                response.raise_for_status()
                video_url = response.json().get("video_url", "")
                parsed = urlparse(video_url)
                if parsed.hostname not in ("vimeo.com", "player.vimeo.com"):
                    raise TransferError(
                        "Unsupported video provider; upstream downloader needs updating."
                    )
                # Preserve signed/unlisted Vimeo URL parameters from the API.
                files = download_video(video_url, path, quality)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                # This inherited parser only supports downloadable resource pages.
                download_resource_lesson(
                    f"https://learn.kodekloud.com/user/courses/{course.slug}/module/{module.id}/lesson/{lesson.id}",
                    path,
                    None,
                )
                files = [
                    file
                    for file in path.parent.iterdir()
                    if file.is_file() and file.suffix in (".md", ".pdf")
                ]
                if not files:
                    print(f"No supported downloadable resource: {lesson.title}", flush=True)
                    unsupported += 1
                    continue
            upload_and_record(drive, files, root, state_path, course.id, lesson.id, quality)
            completed += 1
            print(f"Uploaded and verified: {lesson.title}", flush=True)
    print(
        f"Finished: {completed} uploaded, {skipped} verified skips, {unsupported} unsupported/non-file lessons."
    )


def main():
    token = os.environ.get("KK_COOKIES", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token or "\n" in token or "\r" in token:
        raise ValueError("KK_COOKIES must contain one non-empty bearer token.")
    course_url = urlparse(os.environ.get("COURSE_URL", ""))
    if course_url.scheme != "https" or course_url.hostname not in (
        "kodekloud.com",
        "learn.kodekloud.com",
    ):
        raise ValueError("Enter an HTTPS KodeKloud course URL.")
    slug = course_url.path.rstrip("/").split("/")[-1]
    if not slug:
        raise ValueError("The course URL has no course slug.")
    quality = os.environ.get("QUALITY", "1080p")
    if quality not in ("360p", "480p", "540p", "720p", "1080p"):
        raise ValueError("Unsupported video quality.")
    course = fetch_course_detail(slug)
    with requests.Session() as session:
        session.headers["Authorization"] = "Bearer " + token
        run_course(
            course,
            session,
            Drive(os.environ.get("DRIVE_DESTINATION", "CloudDriveRemote:KodeKloud")),
            Path("CourseDownload"),
            quality,
        )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TransferError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        # Do not print request URLs, headers, or arbitrary exception bodies.
        print(
            f"ERROR: {type(error).__name__}. Run stopped; verified Drive progress is retained.",
            file=sys.stderr,
        )
        sys.exit(1)
