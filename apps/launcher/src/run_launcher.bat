@echo off
REM Alpecca launcher -- run from source. Prefers pythonw so no console window
REM tags along behind her little control panel; falls back to plain python.
cd /d %~dp0
where pythonw >nul 2>&1
if errorlevel 1 (
  start "" python alpecca_launcher.py
) else (
  start "" pythonw alpecca_launcher.py
)
