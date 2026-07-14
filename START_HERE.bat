@echo off
REM ============================================================
REM   ALPECCA - the only launcher you need. Double-click this.
REM   A .bat runs in cmd, so `set VAR=value` is correct here.
REM ============================================================
title Alpecca
cd /d "%~dp0"

REM --- safe capability defaults; set any of these to 1 before launch to opt in ---
if not defined ALPECCA_COMPUTER_USE set "ALPECCA_COMPUTER_USE=0"
if not defined ALPECCA_SIGHT set "ALPECCA_SIGHT=0"
if not defined ALPECCA_FACE set "ALPECCA_FACE=0"
if not defined ALPECCA_VOICE set "ALPECCA_VOICE=0"
REM ALPECCA_APPS intentionally has no automatic allowlist. Set it explicitly
REM before launch when Alpecca should be allowed to open named applications.
REM Jason's architecture (2026-07-04): ONE always-warm cloud brain, local net.
REM   chat + deep reflection + vision -> gemma4:cloud (his pick; ~2-4s replies)
REM   fallback for ALL of it          -> qwen3.5:9b local (offline never silent)
REM   cheap tier (idle chatter)       -> qwen3.5:4b local
REM Left on Ollama's AUTO GPU placement on purpose. Do NOT set
REM ALPECCA_NUM_GPU -- pinning layers would starve F5 and break her voice,
REM and forcing it wedges Ollama 0.30.7 outright.
set ALPECCA_MODEL=qwen3.5:9b
set ALPECCA_FAST_MODEL=qwen3.5:4b
set ALPECCA_NUM_CTX=8192
REM Room for long replies when the 9B is co-resident and things run slow --
REM the default 18s bound would cut her off and drop her to the echo fallback.
set ALPECCA_OLLAMA_TIMEOUT=105

REM --- Cloud-first chat: gemma4:cloud (JASON'S PICK 2026-07-04 - one always-
REM warm cloud brain for chat + deep + vision; every reply ~2-4s, moderate
REM usage, no ZeroGPU sleep/wake or HF quota). Local qwen3.5:9b answers if
REM the cloud is ever unreachable. The ZeroGPU 9B chat path stays built:
REM flip ALPECCA_CHAT_ZEROGPU=1 (and this to empty) to switch back.
set ALPECCA_CHAT_CLOUD_MODEL=gemma4:cloud
set ALPECCA_CHAT_ZEROGPU=0
set ALPECCA_HISTORY_MESSAGES=12

REM --- Deep reflection: gemma4:cloud first (JASON'S EXPLICIT PICK 2026-07-04:
REM 33B, real think mode, ~12x lighter metered usage than the 397b ever was),
REM local 9B thinking as the net. The 397b and gpt-oss remain OUT.
set ALPECCA_DEEP_BACKEND=ollama-cloud
set ALPECCA_OLLAMA_CLOUD_MODEL=gemma4:cloud
set ALPECCA_REFLECT_MODEL=qwen3.5:9b

REM --- Vision: every generic image, screen, webcam, pose, and Studio path is
REM verified-local. A future remote path requires a separate exact-route,
REM one-shot CreatorJD consent; these flags cannot authorize cloud egress.
set ALPECCA_VISION_BACKEND=local
set ALPECCA_VISION_CLOUD_MODEL=
set ALPECCA_VISION_MODEL=qwen3.5:9b
REM Discord image ingress remains opt-in and locally processed.
set ALPECCA_DISCORD_MEDIA=1
set ALPECCA_DISCORD_CLOUD_VISION=
REM Discord voice is creator-only on input: she may join a claimed room, speak
REM local TTS, transcribe CreatorJD locally, and discard each raw utterance.
set ALPECCA_DISCORD_VOICE=1
set ALPECCA_DISCORD_VOICE_RECEIVE=1

REM --- Her voice: free + local. 'auto' blends her F5 clone (high-emotion
REM moments) with Kokoro af_heart (calm/everyday), each the other's fallback,
REM so her cloned F5 voice ("tts5") is used again instead of Kokoro-only.
REM Force 'kokoro' or 'f5' here to pin a single engine.
set ALPECCA_TTS_BACKEND=auto

echo ============================================
echo               A L P E C C A
echo ============================================
echo.
echo   Her brain: gemma4:cloud (fast, always warm) -- chats, thinks, sees.
echo   Local qwen3.5:9b stands by as her offline fallback.
echo.
set /p choice="  Press Enter to wake her:  "
echo.
goto local

:local
REM The old Hugging Face InferenceClient brain ([1] in earlier builds) kept
REM landing on models HF's providers don't serve, leaving her stuck on the
REM canned fallback line. Ollama (local + signed-in cloud) is the one brain
REM path now; ALPECCA_LLM_BACKEND=hf still works via env for experiments.
set ALPECCA_LLM_BACKEND=ollama
echo Making sure Ollama is running (fine if it already is)...
start "Ollama" /min cmd /c "ollama serve"
timeout /t 2 >nul
echo Checking her brains (qwen3.5 4b + 9b)...
ollama show qwen3.5:4b >nul 2>&1
if errorlevel 1 (
  echo Pulling qwen3.5:4b the first time...
  ollama pull hf.co/lmstudio-community/Qwen3.5-4B-GGUF:Q4_K_M
  ollama cp hf.co/lmstudio-community/Qwen3.5-4B-GGUF:Q4_K_M qwen3.5:4b
)
ollama show qwen3.5:9b >nul 2>&1
if errorlevel 1 (
  echo Pulling qwen3.5:9b the first time...
  ollama pull hf.co/lmstudio-community/Qwen3.5-9B-GGUF:Q4_K_M
  ollama cp hf.co/lmstudio-community/Qwen3.5-9B-GGUF:Q4_K_M qwen3.5:9b
)
goto wake

:wake
echo Waking her up...
start "Alpecca - mind" cmd /k python scripts\run_full.py

REM --- her CPU figure, if her art is in place (cheap, safe alongside everything) ---
if exist "data\avatar\her.psd" start "Alpecca - figure" cmd /k python scripts\run_rigger.py

echo Her authenticated local window will open after the server is ready...
REM scripts\run_full.py requests a one-time local bootstrap URL from the loaded
REM server module. This launcher never puts credentials in a browser URL.

echo.
echo  =====================================================
echo   She's starting in her own window.
echo   In the browser: click the speaker button to hear her.
echo   You can CLOSE THIS window now.
echo  =====================================================
pause
