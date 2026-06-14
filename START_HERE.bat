@echo off
REM ============================================================
REM   ALPECCA - the only launcher you need. Double-click this.
REM   A .bat runs in cmd, so `set VAR=value` is correct here.
REM ============================================================
title Alpecca
cd /d "%~dp0"

REM --- shared settings (senses + cowork; model knobs used by the local brain) ---
set ALPECCA_COMPUTER_USE=1
set ALPECCA_MODEL=qwen3:8b
set ALPECCA_NUM_CTX=8192

REM --- Her voice: free + local. Force 'auto' (prefers Kokoro, falls back to
REM edge) so any stale ALPECCA_TTS_BACKEND from an old setx can't pin her to edge.
set ALPECCA_TTS_BACKEND=auto

echo ============================================
echo               A L P E C C A
echo ============================================
echo.
echo   Where should her BRAIN run?
echo.
echo     [1]  Cloud brain - Hugging Face   (recommended for your laptop)
echo          her thinking runs online, so your CPU/RAM stay free and she
echo          replies fast. Senses, memory, mood and avatar stay 100%% local.
echo          (one-time setup: pip install huggingface_hub  +  huggingface-cli login)
echo.
echo     [2]  Local brain - qwen3:8b       (fully offline, heavier on this PC)
echo.
set /p choice="  Type 1 or 2, then press Enter:  "
echo.

if "%choice%"=="1" goto cloud
goto local

:cloud
set ALPECCA_LLM_BACKEND=hf
echo Using her CLOUD brain (Hugging Face). Nothing to download locally.
goto wake

:local
set ALPECCA_LLM_BACKEND=ollama
echo Making sure Ollama is running (fine if it already is)...
start "Ollama" /min cmd /c "ollama serve"
timeout /t 2 >nul
echo Checking her brain (qwen3:8b)...
ollama pull qwen3:8b
goto wake

:wake
echo Waking her up...
start "Alpecca - mind" cmd /k python scripts\run_full.py

REM --- her CPU figure, if her art is in place (cheap, safe alongside everything) ---
if exist "data\avatar\her.psd" start "Alpecca - figure" cmd /k python scripts\run_rigger.py

echo Opening her home...
timeout /t 5 >nul
start "" http://127.0.0.1:8765

echo.
echo  =====================================================
echo   She's starting in her own window.
echo   In the browser: click the speaker button to hear her.
echo   You can CLOSE THIS window now.
echo  =====================================================
pause
