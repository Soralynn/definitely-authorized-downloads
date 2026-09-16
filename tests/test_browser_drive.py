import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from kodekloud_downloader import browser, helpers, main
from kodekloud_downloader.cli import kodekloud
from kodekloud_downloader.drive import DriveUploader


def test_manual_signin_uses_normal_browser_without_printing_token(
    tmp_path, monkeypatch, capsys
):
    executable = tmp_path / "brave.exe"
    executable.touch()
    launch = MagicMock()
    monkeypatch.setattr(browser.subprocess, "Popen", launch)
    monkeypatch.setattr(browser.getpass, "getpass", lambda prompt: "synthetic-session")
    result = browser.get_session_token_from_browser(
        auto_launch=True, executable_path=str(executable)
    )
    assert result == "synthetic-session"
    assert launch.call_args.args[0] == [
        str(executable),
        "https://learn.kodekloud.com/user/courses",
    ]
    assert "synthetic-session" not in capsys.readouterr().out


def test_manual_signin_rejects_empty_session(tmp_path, monkeypatch):
    executable = tmp_path / "brave.exe"
    executable.touch()
    monkeypatch.setattr(browser.subprocess, "Popen", MagicMock())
    monkeypatch.setattr(browser.getpass, "getpass", lambda prompt: "  ")
    with pytest.raises(RuntimeError, match="No session value"):
        browser.manual_browser_signin("brave", str(executable))


def test_brave_windows_detection(tmp_path, monkeypatch):
    executable = tmp_path / "BraveSoftware/Brave-Browser/Application/brave.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(browser.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert browser.browser_path("brave") == executable


def test_cookie_domain_is_restricted():
    context = MagicMock()
    context.cookies.return_value = [
        {"name": "session-cookie", "value": "wrong", "domain": "evilkodekloud.com"},
        {"name": "session-cookie", "value": "correct", "domain": ".kodekloud.com"},
    ]
    assert browser._extract_session_cookie(context) == "correct"
    context.cookies.assert_called_once_with("https://learn.kodekloud.com")


def test_video_returns_final_postprocessed_path(tmp_path, monkeypatch):
    final = tmp_path / "lesson.mkv"

    class FakeYDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def download(self, url):
            for hook in self.options["post_hooks"]:
                hook(str(final))

    monkeypatch.setattr(helpers.yt_dlp, "YoutubeDL", FakeYDL)
    assert helpers.download_video(
        "https://example.com", tmp_path / "lesson", None, "720p"
    ) == [final]


def test_failed_download_returns_no_upload_candidates(tmp_path, monkeypatch):
    def fail(**kwargs):
        raise main.yt_dlp.utils.DownloadError("test failure")

    monkeypatch.setattr(main, "download_video", fail)
    assert (
        main.download_video_lesson(
            "https://example.com", tmp_path / "lesson", None, "720p"
        )
        == []
    )


def test_course_uploads_only_completed_paths(tmp_path, monkeypatch):
    lesson = SimpleNamespace(type="video", title="Lesson", id="lesson")
    course = SimpleNamespace(
        id="course",
        title="Course",
        modules=[SimpleNamespace(title="Module", lessons=[lesson])],
    )
    session = MagicMock()
    session.get.return_value.json.return_value = {
        "video_url": "https://example.com/123"
    }
    monkeypatch.setattr(main.requests, "Session", lambda: session)
    completed = [tmp_path / "final.mkv"]
    monkeypatch.setattr(main, "download_video_lesson", lambda *args: completed)
    upload = MagicMock()
    main.download_course(
        course, "720p", tmp_path, 3, "synthetic-token", on_download=upload
    )
    upload.assert_called_once_with(completed[0])


@pytest.fixture
def upload_file(tmp_path):
    path = tmp_path / "KodeKloud/Course/Module/lesson.mkv"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic-video")
    return path


def test_drive_creates_hierarchy_and_verifies_upload(tmp_path, upload_file):
    service = MagicMock()
    files = service.files.return_value
    files.list.return_value.execute.return_value = {"files": []}
    files.create.return_value.execute.side_effect = [
        {"id": "top"},
        {"id": "course"},
        {"id": "module"},
    ]
    files.create.return_value.next_chunk.side_effect = [
        (None, None),
        (
            None,
            {
                "id": "video",
                "size": str(upload_file.stat().st_size),
                "md5Checksum": hashlib.md5(upload_file.read_bytes()).hexdigest(),  # noqa: S324
            },
        ),
    ]
    uploader = DriveUploader(service, tmp_path)
    assert uploader.upload(upload_file) == "video"
    calls = files.create.call_args_list
    assert [call.kwargs["body"]["name"] for call in calls] == [
        "KodeKloud",
        "Course",
        "Module",
        "lesson.mkv",
    ]
    assert calls[-1].kwargs["body"]["parents"] == ["module"]
    assert files.create.return_value.next_chunk.call_count == 2
    assert upload_file.exists()


def test_drive_skips_identical_upload(tmp_path, upload_file):
    service = MagicMock()
    files = service.files.return_value
    files.list.return_value.execute.side_effect = [
        {"files": [{"id": "top"}]},
        {"files": [{"id": "course"}]},
        {"files": [{"id": "module"}]},
        {
            "files": [
                {
                    "id": "video",
                    "size": str(upload_file.stat().st_size),
                    "md5Checksum": hashlib.md5(upload_file.read_bytes()).hexdigest(),  # noqa: S324
                }
            ]
        },
    ]
    assert DriveUploader(service, tmp_path).upload(upload_file) == "video"
    files.create.assert_not_called()
    files.update.assert_not_called()


def test_drive_mismatch_retains_local_file(tmp_path, upload_file):
    service = MagicMock()
    files = service.files.return_value
    files.list.return_value.execute.return_value = {"files": [{"id": "existing"}]}
    files.update.return_value.next_chunk.return_value = (
        None,
        {"id": "existing", "size": "0", "md5Checksum": "bad"},
    )
    with pytest.raises(RuntimeError, match="verification failed"):
        DriveUploader(service, tmp_path).upload(upload_file)
    assert upload_file.read_bytes() == b"synthetic-video"


def test_drive_network_failure_retains_local_file(tmp_path, upload_file):
    service = MagicMock()
    files = service.files.return_value
    files.list.return_value.execute.return_value = {"files": [{"id": "existing"}]}
    files.update.return_value.next_chunk.side_effect = OSError("offline")
    with pytest.raises(OSError):
        DriveUploader(service, tmp_path).upload(upload_file)
    assert upload_file.exists()


def test_drive_rejects_partial_or_outside_files(tmp_path):
    partial = tmp_path / "video.part"
    partial.touch()
    uploader = DriveUploader(MagicMock(), tmp_path)
    with pytest.raises(ValueError):
        uploader.upload(partial)
    with pytest.raises(ValueError):
        uploader.upload(tmp_path.parent / "outside.mp4")
    uploader.service.files.assert_not_called()


def test_missing_credentials_fails_before_downloading(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(kodekloud, ["dl", "--browser", "--drive"])
    assert result.exit_code != 0
    assert "credentials are missing" in result.output


def test_cli_routes_brave_and_upload(tmp_path, monkeypatch):
    import kodekloud_downloader.cli as cli
    import kodekloud_downloader.drive as drive

    auth = MagicMock(return_value="synthetic-token")
    monkeypatch.setattr(browser, "get_session_token_from_browser", auth)
    monkeypatch.setattr(drive, "authorize", MagicMock())
    uploader = MagicMock()
    monkeypatch.setattr(drive, "DriveUploader", lambda *args: uploader)
    monkeypatch.setattr(cli, "parse_course_from_url", lambda url: "course")
    download = MagicMock()
    monkeypatch.setattr(cli, "download_course", download)
    result = CliRunner().invoke(
        kodekloud,
        [
            "dl",
            "--browser",
            "--drive",
            "-o",
            str(tmp_path),
            "https://kodekloud.com/courses/example",
        ],
    )
    assert result.exit_code == 0, result.output
    assert auth.call_args.kwargs["browser_name"] == "brave"
    download.call_args.kwargs["on_download"](tmp_path / "test.mkv")
    uploader.upload.assert_called_once_with(tmp_path / "test.mkv")
