@echo off
REM One-click launcher for Alpecca on Windows.
REM Double-click this file (NOT web\index.html) to start her up.

cd /d "%~dp0"

echo Installing dependencies (first run only)...
python -m pip install -r requirements.txt

echo.
echo Starting Alpecca... when it says she's awake, open this in your browser:
echo     http://127.0.0.1:8765
echo (Leave this window open while you talk to her. Close it to stop.)
echo.

REM Open the browser automatically after a short delay, then run the server.
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8765"
python server.py

pause
