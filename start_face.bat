@echo off
REM ============================================================
REM  One double-click: her brain + her neural face, both windows.
REM  Run setup_face.bat ONCE first (installs THA3, pulls the 4B
REM  model, preps her image, downloads the face models).
REM ============================================================
cd /d "%~dp0"
title Alpecca launcher

REM A 4B brain fits beside her neural face on a 4 GB GPU; cowork on.
REM These env vars are inherited by both windows started below.
set ALPECCA_MODEL=qwen3:4b-instruct-2507
set ALPECCA_COMPUTER_USE=1

echo.
echo  Launching Alpecca -- her brain first, then her face.
echo.

REM Window 1: her brain + senses (sees the env vars set above)
start "Alpecca - brain" cmd /k python scripts\run_full.py

echo  Waiting ~15s for her brain to wake before her face connects...
timeout /t 15 /nobreak >nul

REM Window 2: her neural face (THA3 separable_half, adaptive framerate)
start "Alpecca - face" cmd /k python scripts\run_talkinghead.py

echo.
echo  Two windows are opening. Give them a few seconds, then open:
echo.
echo      http://127.0.0.1:8765
echo.
echo  If the FACE window says "isn't reachable", her brain just needed
echo  longer to load -- close that window and run, in the project folder:
echo      python scripts\run_talkinghead.py
echo.
echo  To stop her: close both windows (Ctrl+C in each).
echo.
pause
