@echo off
rem  Double-click: converts every .docx in the "input" folder into the "output" folder.
rem  Drag and drop: drop one or more .docx files onto this icon.
chcp 65001 >nul
cd /d "%~dp0"
python convert.py %*
echo.
pause
