# Brave sign-in and Google Drive uploads

The local version defaults to Brave when `--browser` is used. Chrome is still
available with `--browser-name chrome`. KodeKloud sign-in opens your normal
browser without automation or debugging flags. Complete sign-in and any human
verification yourself. After the courses page loads, press F12 and open
**Application > Storage > Cookies > https://learn.kodekloud.com**. Copy the
**Value** of `session-cookie` and paste it into the terminal's hidden prompt,
then press Enter. The value is not saved to disk. Do not share it in chat.

## Recommended: Google Drive for desktop (no Cloud project)

1. Open **Google Drive** from the Windows Start menu and sign in to Google.
2. Finish its setup. You only need **My Drive**; backing up Desktop, Documents,
   and Pictures is optional and unnecessary for this downloader.
3. Wait until **Google Drive > My Drive** appears in File Explorer.
4. Double-click `Download-to-Drive.cmd` in this repository.
5. Sign in to KodeKloud in Brave, supply the session value as described above,
   and select your courses in the terminal.

The launcher detects the My Drive folder and saves under **My Drive > KodeKloud**.
Google Drive for desktop uploads automatically. Keep it running and check its
sync status for completion; the downloader finishing does not prove cloud sync
has finished. Downloads and temporary video merging still use local disk/cache.

Equivalent PowerShell command:

```powershell
cd C:\Users\wesg4\Desktop\KKScraper\kodekloud-downloader
.\.venv\Scripts\kodekloud.exe dl --browser --drive-desktop
```

For a custom, translated, mirrored, or multiple-account Drive location, supply
the actual folder with `--drive-folder "G:\My Drive"` (replace that example path
with your own). Desktop mode uses this folder instead of `--output-dir`.
Do not add `--drive`, which selects the separate API method below.
Files deleted from the synced folder may also be deleted in Drive; use the
Drive application's storage controls if you want to free local cached space.

## Alternative: one-time Google API setup

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. Under **APIs & Services > Library**, enable **Google Drive API**.
3. Open **Google Auth platform** and configure the app branding and contact email.
   For a personal Gmail account, choose **External** as the audience. While the
   app is in testing, add your Google email under **Audience > Test users**.
4. Under **Data Access**, add `https://www.googleapis.com/auth/drive.file`.
   This application requests access to files it creates or that you explicitly
   make available to it, rather than your entire Drive.
5. Under **Clients > Create client**, choose **Desktop app** and create the client.
6. Download its JSON file and save it as:

   `C:\Users\wesg4\Desktop\KKScraper\kodekloud-downloader\credentials.json`

Keep this file and the generated `.secrets/google-token.json` on your computer.
Both are excluded from Git. Do not paste authorization tokens into chat.

Google's [Python quickstart](https://developers.google.com/workspace/drive/api/quickstart/python)
describes the desktop OAuth setup. This project uses the narrower
[`drive.file` scope](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

## Download and upload

Open a new PowerShell window and run:

```powershell
cd C:\Users\wesg4\Desktop\KKScraper\kodekloud-downloader
.\.venv\Scripts\kodekloud.exe dl --browser --browser-name brave --drive -o .\downloads
```

1. Authorize your Google account in Brave. Google authorization uses a normal
   Brave window and a temporary localhost callback. It times out after five minutes.
2. Sign in to KodeKloud in normal Brave and paste your session value at the
   hidden terminal prompt as described above.
3. Select the enrolled courses you want from the terminal list.
4. Completed video files and successfully extracted resources upload automatically
   to **My Drive > KodeKloud > Course > Module**.

For one course, add its URL at the end of the command. Use `-q 720p` to request
720p instead of the default 1080p. Omit `--drive` for local downloads only.
Use `--drive-credentials PATH` for a different OAuth JSON location and
`--browser-path PATH` if Brave is installed in a custom location.

## Transfer behavior and limits

- Videos download and merge locally before uploading. Keep enough free disk space
  for the downloaded courses. Local copies are retained after uploads.
- Uploads use 8 MiB chunks, retry transient failures, and verify size and MD5
  against Drive's returned metadata. MD5 is used for transfer integrity only.
- Rerunning the same command skips matching uploaded files and updates changed
  files created by this application. It does not overwrite unrelated Drive files.
  Use one downloader process at a time to avoid duplicate folder creation races.
- If an upload fails, the run stops and retains the local file. Correct the
  connection/quota problem and rerun the same command. An unfinished upload may
  restart from the beginning; resumable sessions are not persisted between runs.
- The Google grant is cached in `.secrets/google-token.json`. If Google revokes
  or expires it, the program requests authorization again. Testing-mode grants
  may require renewed authorization.
- Resource extraction depends on the upstream downloader's HTML parser. Some
  lessons, labs, or quizzes may not produce downloadable resource files. Separate
  `dl-quiz` exports are not part of automatic Drive uploads.
- Changes were tested with synthetic files and mocked Drive responses. A real
  account login and upload still need to be verified after authorization.

## Local checks

```powershell
uv sync --extra browser --extra drive --group dev
.\.venv\Scripts\python.exe -m pytest -q
```
