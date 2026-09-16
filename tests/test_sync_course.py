import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import sync_course as sync


def test_completion_requires_matching_remote_checksum():
    record = {
        "version": 1,
        "course": "c",
        "lesson": "l",
        "quality": "720p",
        "files": [{"path": "course/video.mkv", "size": 3, "md5": "abc"}],
    }
    inventory = {"course/video.mkv": {"Size": 3, "Hashes": {"MD5": "abc"}}}
    assert sync.is_complete(record, inventory, "c", "l", "720p")
    assert not sync.is_complete(record, inventory, "c", "l", "1080p")
    assert not sync.is_complete(record, {}, "c", "l", "720p")
    inventory["course/video.mkv"]["Hashes"]["MD5"] = "different"
    assert not sync.is_complete(record, inventory, "c", "l", "720p")


@pytest.mark.parametrize("record", [None, [], {}, {"version": 1, "files": []}])
def test_invalid_completion_is_not_skipped(record):
    assert not sync.is_complete(record, {}, "c", "l", "720p")


def test_only_cleanup_after_all_uploads_and_record_succeed(tmp_path):
    video = tmp_path / "KodeKloud/Course/video.mkv"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    drive = MagicMock()
    drive.upload.side_effect = [
        sync.metadata(video, "Course/video.mkv"),
        sync.TransferError("offline"),
    ]
    with pytest.raises(sync.TransferError):
        sync.upload_and_record(drive, [video], tmp_path, ".progress/test.json", "c", "l", "720p")
    assert video.exists()
    assert drive.upload.call_args_list[0].args[1] == "Course/video.mkv"


def test_verified_uploads_then_cleanup(tmp_path):
    video = tmp_path / "KodeKloud/Course/video.mkv"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    drive = MagicMock()
    drive.upload.return_value = sync.metadata(video, "Course/video.mkv")
    sync.upload_and_record(drive, [video], tmp_path, ".progress/test.json", "c", "l", "720p")
    assert drive.upload.call_count == 2
    assert not video.exists()


def test_upload_detects_checksum_mismatch(tmp_path):
    video = tmp_path / "video.mkv"
    video.write_bytes(b"video")
    drive = sync.Drive("remote:KodeKloud")
    drive.run = MagicMock(side_effect=["", json.dumps({"Size": 5, "Hashes": {"MD5": "wrong"}})])
    with pytest.raises(sync.TransferError, match="checksum"):
        drive.upload(video, "Course/video.mkv")
    assert video.exists()


def test_remote_failures_do_not_leak_output(monkeypatch):
    monkeypatch.setattr(
        sync.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="private-token", stderr="private-token"
        ),
    )
    with pytest.raises(sync.TransferError) as error:
        sync.Drive("remote:folder").run("lsjson", "remote:folder")
    assert "private-token" not in str(error.value)


@pytest.mark.parametrize("path", ["../secret", "/absolute", "a/../../secret", "a\\b"])
def test_remote_path_cannot_escape(path):
    with pytest.raises(ValueError):
        sync.Drive("remote:folder").target(path)


def test_verified_lesson_is_skipped_before_api_or_download(tmp_path, monkeypatch):
    course = SimpleNamespace(
        id="c",
        title="Course",
        modules=[
            SimpleNamespace(
                title="Module", lessons=[SimpleNamespace(id="l", title="Lesson", type="video")]
            )
        ],
    )
    state = sync.checkpoint_name("c", "l", "720p")
    drive = MagicMock()
    drive.inventory.return_value = {
        state: {},
        "Course/video.mkv": {"Size": 3, "Hashes": {"MD5": "abc"}},
    }
    drive.read_json.return_value = {
        "version": 1,
        "course": "c",
        "lesson": "l",
        "quality": "720p",
        "files": [{"path": "Course/video.mkv", "size": 3, "md5": "abc"}],
    }
    session = MagicMock()
    download = MagicMock()
    monkeypatch.setattr(sync, "download_video", download)
    sync.run_course(course, session, drive, tmp_path, "720p")
    session.get.assert_not_called()
    download.assert_not_called()
    drive.upload.assert_not_called()


def test_missing_remote_video_is_downloaded_again(tmp_path, monkeypatch):
    course = SimpleNamespace(
        id="c",
        title="Course",
        modules=[
            SimpleNamespace(
                title="Module", lessons=[SimpleNamespace(id="l", title="Lesson", type="video")]
            )
        ],
    )
    drive = MagicMock()
    drive.inventory.return_value = {}
    session = MagicMock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = {
        "video_url": "https://player.vimeo.com/video/123?h=example"
    }
    video = tmp_path / "KodeKloud/Course/1 - Module/1 - Lesson.mkv"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    download = MagicMock(return_value=[video])
    monkeypatch.setattr(sync, "download_video", download)
    drive.upload.return_value = sync.metadata(video, "Course/1 - Module/1 - Lesson.mkv")
    sync.run_course(course, session, drive, tmp_path, "720p")
    assert download.call_args.args[0].endswith("?h=example")
    assert drive.upload.call_count == 2


def test_unauthorized_stops_without_checkpoint(tmp_path):
    course = SimpleNamespace(
        id="c",
        title="Course",
        modules=[
            SimpleNamespace(
                title="Module", lessons=[SimpleNamespace(id="l", title="Lesson", type="video")]
            )
        ],
    )
    drive = MagicMock()
    drive.inventory.return_value = {}
    session = MagicMock()
    session.get.return_value.status_code = 401
    with pytest.raises(sync.TransferError, match="401"):
        sync.run_course(course, session, drive, tmp_path)
    drive.upload.assert_not_called()


def test_real_rclone_local_transfer_and_second_run(tmp_path, monkeypatch):
    import shutil

    if not shutil.which("rclone"):
        pytest.skip("rclone is not installed")
    monkeypatch.setenv("RCLONE_CONFIG_TESTDRIVE_TYPE", "local")
    root = tmp_path / "downloads"
    remote = tmp_path / "remote"
    video = root / "KodeKloud/Course/video.mkv"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"synthetic media for transfer verification")
    drive = sync.Drive("testdrive:" + remote.as_posix())
    assert drive.inventory() == {}
    sync.upload_and_record(drive, [video], root, ".progress/example.json", "c", "l", "720p")
    inventory = drive.inventory()
    record = drive.read_json(".progress/example.json")
    assert sync.is_complete(record, inventory, "c", "l", "720p")
    assert not video.exists()
    (remote / "Course/video.mkv").write_bytes(b"changed")
    assert not sync.is_complete(record, drive.inventory(), "c", "l", "720p")
