@echo off
REM Launch Alpecca with all senses + cowork, from the right folder, no PowerShell
REM env-var confusion. A .bat runs in cmd, where `set VAR=value` IS correct.
REM Just double-click this file, or run  .\start_full.bat  in the project folder.

cd /d "%~dp0"

REM Enable computer use (cowork). run_full.py turns on sight/face/voice/proactive.
set ALPECCA_COMPUTER_USE=1

echo.
echo  Starting Alpecca with all senses + cowork...
echo  Open  http://127.0.0.1:8765  when it says "waking up".
echo.

python scripts\run_full.py

echo.
echo  (Alpecca stopped. Close this window or press a key.)
pause >nul
