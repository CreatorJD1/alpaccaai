@echo off
REM ============================================================
REM   Install Alpecca's free voice packages. Just double-click this.
REM   Installs ONE at a time so pip's resolver can't hang.
REM ============================================================
title Alpecca - install voice packages
cd /d "%~dp0"

echo ============================================================
echo   Installing Alpecca's voice packages (free, local)
echo ============================================================
echo.
echo [1 of 2] edge-tts  (her always-works neural fallback voice)
echo ------------------------------------------------------------
python -m pip install --no-cache-dir --disable-pip-version-check --timeout 30 --retries 1 -v edge-tts || python -m pip install --no-cache-dir --no-deps edge-tts
echo.
echo [2 of 2] kokoro + soundfile  (her best free LOCAL voice, Kokoro-82M)
echo ------------------------------------------------------------
python -m pip install --no-cache-dir --disable-pip-version-check --timeout 60 --retries 1 -v kokoro soundfile || python -m pip install --no-cache-dir --no-deps kokoro soundfile
echo.
echo ============================================================
echo   Finished.
echo   If you see "Successfully installed" / "already satisfied"
echo   above, her voice is ready. Also install espeak-ng for Kokoro:
echo     https://github.com/espeak-ng/espeak-ng/releases  (.msi)
echo   Then close this window and run START_HERE.bat.
echo ============================================================
pause
