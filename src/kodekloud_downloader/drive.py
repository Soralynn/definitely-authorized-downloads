"""Optional Google Drive uploads using narrowly scoped desktop OAuth."""

import hashlib
import logging
import mimetypes
import os
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"
APP_PROPERTIES = {"kodekloud_downloader": "v1"}


def authorize(credentials_path, token_path, browser_name="brave", executable_path=None):
    """Authorize in the selected browser and cache the grant locally."""
    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "Install Drive support: uv sync --extra browser --extra drive"
        ) from None

    token_path = Path(token_path)
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            credentials = None
    if not credentials or not credentials.valid:
        if not Path(credentials_path).is_file():
            raise RuntimeError(
                "Google OAuth credentials are missing. Save your Desktop app JSON as "
                "credentials.json, or use --drive-credentials PATH. See DRIVE_SETUP.md."
            )
        from kodekloud_downloader.browser import browser_path

        executable = (
            Path(executable_path) if executable_path else browser_path(browser_name)
        )
        if executable is None or not executable.is_file():
            raise RuntimeError(f"Cannot find {browser_name}; use --browser-path.")
        webbrowser.register(
            "kodekloud-auth", None, webbrowser.BackgroundBrowser(str(executable))
        )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        credentials = flow.run_local_server(
            host="localhost",
            port=0,
            browser="kodekloud-auth",
            timeout_seconds=300,
            authorization_prompt_message="Authorize Google Drive in your browser.",
            success_message="Google Drive is connected. You can close this tab.",
        )
    token_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = token_path.with_suffix(".tmp")
    with open(temporary, "w", encoding="utf-8") as output:
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        output.write(credentials.to_json())
    temporary.replace(token_path)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _escape(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _checksum(path):
    # MD5 is used only to compare file bytes with Drive's checksum, not for security.
    digest = hashlib.md5()  # noqa: S324
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DriveUploader:
    """Upload completed files; keep local originals even if an upload fails."""

    def __init__(self, service, output_dir):
        self.service = service
        self.output_dir = Path(output_dir).resolve()
        self.folders = {}

    def _find(self, parent, name, folder=False):
        query = (
            f"'{_escape(parent)}' in parents and name = '{_escape(name)}' "
            "and trashed = false and appProperties has "
            "{ key='kodekloud_downloader' and value='v1' } "
            f"and mimeType {'=' if folder else '!='} '{FOLDER_MIME}'"
        )
        result = (
            self.service.files()
            .list(
                q=query,
                fields="files(id,size,md5Checksum)",
                pageSize=2,
            )
            .execute(num_retries=3)
        )
        matches = result.get("files", [])
        if len(matches) > 1:
            raise RuntimeError(
                f"Duplicate Drive items named {name}; resolve them before retrying."
            )
        return matches[0] if matches else None

    def _folder(self, parent, name):
        key = (parent, name)
        if key not in self.folders:
            existing = self._find(parent, name, folder=True)
            if existing is None:
                existing = (
                    self.service.files()
                    .create(
                        body={
                            "name": name,
                            "mimeType": FOLDER_MIME,
                            "parents": [parent],
                            "appProperties": APP_PROPERTIES,
                        },
                        fields="id",
                    )
                    .execute()
                )
            self.folders[key] = existing["id"]
        return self.folders[key]

    def upload(self, path):
        from googleapiclient.http import MediaFileUpload

        path = Path(path).resolve()
        relative = path.relative_to(self.output_dir)
        if not path.is_file() or path.suffix.lower() in (".part", ".ytdl", ".tmp"):
            raise ValueError("Only completed download files can be uploaded")
        checksum = _checksum(path)
        size = str(path.stat().st_size)
        parent = "root"
        for component in relative.parts[:-1]:
            parent = self._folder(parent, component)
        existing = self._find(parent, path.name)
        if (
            existing
            and existing.get("md5Checksum") == checksum
            and existing.get("size") == size
        ):
            logger.info("Already uploaded: %s", relative)
            return existing["id"]
        media = MediaFileUpload(
            str(path),
            mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            chunksize=8 * 1024 * 1024,
            resumable=True,
        )
        try:
            if existing:
                request = self.service.files().update(
                    fileId=existing["id"],
                    media_body=media,
                    fields="id,size,md5Checksum",
                )
            else:
                request = self.service.files().create(
                    body={
                        "name": path.name,
                        "parents": [parent],
                        "appProperties": APP_PROPERTIES,
                    },
                    media_body=media,
                    fields="id,size,md5Checksum",
                )
            result = None
            logger.info("Uploading to Drive: %s", relative)
            while result is None:
                _, result = request.next_chunk(num_retries=3)
            if result.get("md5Checksum") != checksum or result.get("size") != size:
                raise RuntimeError(
                    f"Drive verification failed for {relative}; local copy retained."
                )
            logger.info("Verified Drive upload: %s", relative)
            return result["id"]
        finally:
            media.stream().close()
