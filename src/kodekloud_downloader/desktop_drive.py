"""Find the Windows Google Drive for desktop destination."""

import string
from pathlib import Path


def find_drive_folder():
    candidates = [
        Path(f"{letter}:/") / name
        for letter in string.ascii_uppercase
        for name in ("My Drive", "MyDrive")
        if (Path(f"{letter}:/") / name).is_dir()
    ]
    if not candidates:
        raise ValueError(
            "Google Drive's My Drive folder was not found. Open Google Drive for "
            "desktop and sign in, then retry. For a custom or mirrored location, "
            "pass --drive-folder followed by your My Drive folder path."
        )
    if len(candidates) > 1:
        raise ValueError(
            "Multiple Drive folders were found. Choose one with --drive-folder: "
            + ", ".join(str(path) for path in candidates)
        )
    return candidates[0]
