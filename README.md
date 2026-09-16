# KodeKloud course downloads with verified Drive progress

This fork downloads one lesson at a time, uploads it to Google Drive, verifies
its size and MD5, and saves a completion record in Drive. Future runs skip a
lesson before downloading only when its record matches the files still in Drive.
Use only content your account is authorized to download and store.

## One-time setup in your own fork

Forks do not inherit secrets from the original repository. Under **Settings >
Secrets and variables > Actions**, add:

- `KK_COOKIES`: the bearer token from a successful KodeKloud API request. Either
  the raw token or `Bearer TOKEN` is accepted. It is not an exported cookie file.
- `RCLONE_CONFIG`: your working rclone configuration, including its Google
  authorization. Keep the same remote name as your configured destination.

`KK_EMAIL` and `KK_PASSWORD` are not used. The workflow does not automate login
or human verification. Update `KK_COOKIES` when its session expires.

## Run

1. Open **Actions** in your fork. Enable workflows if GitHub prompts you.
2. Select **KodeKloud Auto Downloader & Sync > Run workflow**.
3. Enter the course URL and choose the desired quality.
4. Set the destination to your configured remote and folder, for example
   `CloudDriveRemote:KodeKloud` or `gdrive:KodeKloud`.
5. Start the run. Uploaded files appear under the destination's course/module folders.

## Resume behavior

- Rerun with the same course, quality, and Drive destination.
- `SKIP verified lesson` means the saved completion record matches the current
  remote file size and checksum. No lesson API request or video download is made.
- Each lesson and its completion record upload before the next lesson starts.
  Local lesson files are deleted only after all those uploads are verified.
- An upload or authorization failure stops the run and keeps already-uploaded
  progress. On a fresh GitHub runner, an interrupted/unrecorded lesson downloads
  again. This is lesson-level resume, not cross-run partial-video resume.
- Existing files uploaded by the old workflow have no completion record. They
  are not blindly trusted: the first new run may download those lessons again.
  Matching remote uploads are compared using rclone checksums. The old workflow
  may have created a duplicated `KodeKloud/KodeKloud` folder; choose the actual
  existing course-parent folder as the destination if you want to reuse it.
- Do not delete the destination's `.progress` folder if you want to retain history.
- This does not detect provider-side changes to an already-recorded lesson with
  the same ID. Remove that lesson's record to force a new download.
- Only one run is active at a time to prevent concurrent progress updates.
- Sessions, runner storage, and GitHub execution time are finite. Large courses
  may need multiple runs. Check your GitHub Actions usage limits.

## Limitations

The upstream resource-page parser may not extract current PDFs or lesson notes.
Labs/quizzes and resource pages with no supported files are reported and not
marked completed. Video access still depends on KodeKloud/Vimeo responses and
your account permissions. No login, human-verification, or subscription bypass
is implemented. Automated tests use mocked services; they do not establish
successful live downloads or Google authorization.

## Local validation

```powershell
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt pytest==9.0.3 ruff==0.15.12
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check scripts tests
```

The GitHub runner installs FFmpeg and rclone itself. They are not needed on your
laptop when downloads run in GitHub Actions. To run locally, install both and
supply `KK_COOKIES`, `COURSE_URL`, and `RCLONE_CONFIG` (path to a local config) in
your process environment, then run `python scripts/sync_course.py`.
