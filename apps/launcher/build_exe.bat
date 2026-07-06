@echo off
REM Build AlpeccaLauncher.exe -- a single-file, no-console launcher for her.
REM Safe to run from anywhere: we cd to this script's own folder first so all
REM relative paths (src\, dist\, build\) land under apps\launcher\.
cd /d %~dp0

REM PyInstaller is the one build-time dependency; install it only if missing.
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo Installing PyInstaller...
  python -m pip install pyinstaller
  if errorlevel 1 (
    echo Could not install PyInstaller. Is Python on PATH?
    pause
    exit /b 1
  )
)

echo Building AlpeccaLauncher.exe ...
python -m PyInstaller --onefile --noconsole --name AlpeccaLauncher ^
  --distpath dist --workpath build --specpath build ^
  src\alpecca_launcher.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Done: %~dp0dist\AlpeccaLauncher.exe
echo Keep the exe somewhere INSIDE the repo so it can find server.py above it.
pause
