from pathlib import Path

from click.testing import CliRunner

from kodekloud_downloader import desktop_drive
from kodekloud_downloader.cli import kodekloud


def test_detect_one_drive(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda path: path == Path("G:/My Drive"))
    assert desktop_drive.find_drive_folder() == Path("G:/My Drive")


def test_missing_drive_explains_sign_in(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda path: False)
    result = CliRunner().invoke(kodekloud, ["dl", "--browser", "--drive-desktop"])
    assert result.exit_code != 0
    assert "sign in" in result.output


def test_modes_cannot_be_combined():
    result = CliRunner().invoke(kodekloud, ["dl", "--drive", "--drive-desktop"])
    assert result.exit_code != 0
    assert "not both" in result.output


def test_multiple_drives_require_selection(monkeypatch):
    monkeypatch.setattr(
        Path, "is_dir", lambda path: path in (Path("G:/My Drive"), Path("H:/My Drive"))
    )
    result = CliRunner().invoke(kodekloud, ["dl", "--browser", "--drive-desktop"])
    assert result.exit_code != 0
    assert "Multiple Drive folders" in result.output
