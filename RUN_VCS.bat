@echo off
REM ===================================================================
REM  Run VRoid Companion Studio (the ported Emergent VCS app) locally.
REM  Starts the FastAPI backend (:8001) and the React frontend (:3200)
REM  each in its own window, then opens the studio in your browser.
REM  Close either window to stop that half. See apps\vcs\RUN_LOCAL.md.
REM ===================================================================
setlocal
set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%apps\vcs\backend"
set "FRONTEND_DIR=%ROOT%apps\vcs\frontend"
cd /d "%ROOT%"

echo Starting VCS backend on http://127.0.0.1:8001 ...
start "VCS backend (:8001)" cmd /k ^
  "cd /d "%BACKEND_DIR%" && ..\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8001"

echo Starting VCS frontend on http://localhost:3200 ...
start "VCS frontend (:3200)" cmd /k ^
  "cd /d "%FRONTEND_DIR%" && npm start"

REM Give the dev server a moment, then open the studio (auto-loads Alpecca).
timeout /t 12 /nobreak >nul
start "" "http://localhost:3200"

echo.
echo VCS is starting in two windows. Studio: http://localhost:3200
echo (Alpecca auto-loads; close the two windows to stop.)
endlocal
