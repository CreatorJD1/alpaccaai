@echo off
REM Alpecca GUI boot surface. Prefer the frozen launcher when present, then
REM fall back to the stdlib-only source version without a console window.
cd /d "%~dp0"
if exist "..\dist\AlpeccaLauncher.exe" (
  start "" "..\dist\AlpeccaLauncher.exe"
  exit /b 0
)
where pythonw >nul 2>&1
if errorlevel 1 (
  start "" python alpecca_launcher.py
) else (
  start "" pythonw alpecca_launcher.py
)
