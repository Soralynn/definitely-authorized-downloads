@echo off
cd /d "%~dp0"
".venv\Scripts\kodekloud.exe" dl --browser --browser-name brave --drive-desktop %*
pause
