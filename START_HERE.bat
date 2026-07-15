@echo off
REM ============================================================
REM   ALPECCA - desktop boot entry point. Double-click this.
REM   It opens the GUI launcher instead of keeping a terminal window open.
REM ============================================================
cd /d "%~dp0"

REM --- safe capability defaults; set any of these to 1 before launch to opt in ---
if not defined ALPECCA_COMPUTER_USE set "ALPECCA_COMPUTER_USE=0"
if not defined ALPECCA_SIGHT set "ALPECCA_SIGHT=0"
if not defined ALPECCA_FACE set "ALPECCA_FACE=0"
if not defined ALPECCA_VOICE set "ALPECCA_VOICE=0"
REM ALPECCA_APPS intentionally has no automatic allowlist. Set it explicitly
REM before launch when Alpecca should be allowed to open named applications.
REM Current approved pairing: gemma4:cloud for hosted chat/deep work, with
REM qwen3.5:9b as the local model and reliable offline fallback. Local vision
REM stays on qwen3.5:9b.
REM Left on Ollama's AUTO GPU placement on purpose. Do NOT set
REM ALPECCA_NUM_GPU -- pinning layers would starve F5 and break her voice,
REM and forcing it wedges Ollama 0.30.7 outright.
if not defined ALPECCA_MODEL set "ALPECCA_MODEL=qwen3.5:9b"
if not defined ALPECCA_FAST_MODEL set "ALPECCA_FAST_MODEL=qwen3.5:9b"
if not defined ALPECCA_NUM_CTX set "ALPECCA_NUM_CTX=8192"
REM Room for long replies when the 9B is co-resident and things run slow --
REM the default 18s bound would cut her off and drop her to the echo fallback.
if not defined ALPECCA_OLLAMA_TIMEOUT set "ALPECCA_OLLAMA_TIMEOUT=105"

REM --- Hosted chat uses the approved Gemma 4 cloud tag and falls back to the
REM local qwen3.5:9b model on any provider or network failure.
if not defined ALPECCA_CHAT_CLOUD_MODEL set "ALPECCA_CHAT_CLOUD_MODEL=gemma4:cloud"
if not defined ALPECCA_CHAT_ZEROGPU set "ALPECCA_CHAT_ZEROGPU=0"
if not defined ALPECCA_HISTORY_MESSAGES set "ALPECCA_HISTORY_MESSAGES=12"

REM --- Deep reflection tries approved Gemma 4 cloud reasoning first; local
REM qwen3.5:9b thinking remains the final fallback.
if not defined ALPECCA_DEEP_BACKEND set "ALPECCA_DEEP_BACKEND=ollama-cloud"
if not defined ALPECCA_OLLAMA_CLOUD_MODEL set "ALPECCA_OLLAMA_CLOUD_MODEL=gemma4:cloud"
if not defined ALPECCA_REFLECT_MODEL set "ALPECCA_REFLECT_MODEL=qwen3.5:9b"

REM --- Vision: every generic image, screen, webcam, pose, and Studio path is
REM verified-local. A future remote path requires a separate exact-route,
REM one-shot CreatorJD consent; these flags cannot authorize cloud egress.
if not defined ALPECCA_VISION_BACKEND set "ALPECCA_VISION_BACKEND=local"
if not defined ALPECCA_VISION_CLOUD_MODEL set "ALPECCA_VISION_CLOUD_MODEL="
if not defined ALPECCA_VISION_MODEL set "ALPECCA_VISION_MODEL=qwen3.5:9b"
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

REM The GUI inherits every configuration line above, then starts the existing
REM singleton-protected full stack in the background when Wake Alpecca is used.
call "apps\launcher\src\run_launcher.bat"
exit /b 0
