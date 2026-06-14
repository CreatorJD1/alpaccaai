@echo off
REM ============================================================
REM   Alpecca voice check - tests Kokoro and edge directly.
REM ============================================================
title Alpecca - voice check
cd /d "%~dp0"

echo ============================================================
echo   Checking her voice engines
echo ============================================================
echo.
echo [Kokoro] loading (first run downloads the model, ~30s)...
echo ------------------------------------------------------------
python -c "from kokoro import KPipeline; KPipeline(lang_code='a'); print('KOKORO: OK')"
echo.
echo [edge-tts] importing...
echo ------------------------------------------------------------
python -c "import edge_tts; print('EDGE: OK')"
echo.
echo ============================================================
echo   If Kokoro shows an error above, copy it and send it.
echo   ModuleNotFoundError = not fully installed.
echo   espeak/phonemizer error = install espeak-ng (.msi).
echo ============================================================
pause
