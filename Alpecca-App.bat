@echo off
REM ============================================================
REM   ALPECCA - desktop app (a real window, not a browser tab).
REM   Double-click this. A .bat runs in cmd, so `set VAR=value`
REM   is correct here.
REM ============================================================
title Alpecca (desktop app)
cd /d "%~dp0"

REM --- shared settings (senses + cowork + local brain knobs) ---
set ALPECCA_COMPUTER_USE=1
set ALPECCA_MODEL=qwen3:8b
set ALPECCA_NUM_CTX=8192
set ALPECCA_TTS_BACKEND=auto

echo ============================================
echo            A L P E C C A   -  desktop
echo ============================================
echo.
echo   How should she be reachable?
echo.
echo     [1]  Private   - just this PC, a native window. Nothing exposed.
echo     [2]  Internet  - ALSO open a public link via a Cloudflare tunnel,
echo                      so you can reach her from your phone / anywhere.
echo                      Needs `cloudflared` on PATH. ALWAYS behind a token
echo                      (printed in this window when she starts).
echo.
set /p reach="  Type 1 or 2, then press Enter:  "
echo.
if "%reach%"=="2" (
  set ALPECCA_REMOTE=1
  set ALPECCA_TUNNEL=cloudflare
  echo Internet access ON - watch below for the public URL and the access token.
)

echo   Where should her BRAIN run?
echo     [1]  Cloud - Hugging Face   (light on this laptop)
echo     [2]  Local - qwen3:8b       (fully offline)
set /p choice="  Type 1 or 2, then press Enter:  "
echo.
if "%choice%"=="1" (
  set ALPECCA_LLM_BACKEND=hf
) else (
  set ALPECCA_LLM_BACKEND=ollama
  echo Making sure Ollama is running...
  start "Ollama" /min cmd /c "ollama serve"
  timeout /t 2 >nul
  ollama pull qwen3:8b
)

echo.
echo Waking her up in her own window...
python app.py

pause
