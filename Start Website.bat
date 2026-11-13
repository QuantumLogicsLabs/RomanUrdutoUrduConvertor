@echo off
rem  Starts the Roman Urdu -> Urdu website on http://127.0.0.1:8000 and opens it.
rem  Close this window (or press Ctrl+C) to stop the website.
chcp 65001 >nul
cd /d "%~dp0"
python web\app.py --open
pause
