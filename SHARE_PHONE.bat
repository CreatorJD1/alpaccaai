@echo off
REM ============================================================
REM   ALPECCA - phone link (Cloudflare tunnel, token-gated).
REM   Double-click this. It installs cloudflared if missing,
REM   then starts her and prints your tap-to-open PUBLIC LINK:
REM     https://<random>.trycloudflare.com/?token=...
REM   The link is always behind her access token; the first tap
REM   drops a 30-day cookie on your phone. Ctrl-C here ends it.
REM ============================================================
title Alpecca (phone link)
cd /d "%~dp0"

where cloudflared >nul 2>nul
if errorlevel 1 (
    echo cloudflared isn't installed yet - installing via winget...
    winget install --accept-source-agreements --accept-package-agreements Cloudflare.cloudflared
    echo.
    echo If winget just installed it, PATH may need a fresh window:
    echo close this and double-click SHARE_PHONE.bat again if the
    echo tunnel line below says it's still missing.
    echo.
)

REM Same brain knobs as the desktop launcher.
if "%ALPECCA_MODEL%"=="" set ALPECCA_MODEL=qwen3.5:9b
set ALPECCA_NUM_CTX=8192

python scripts\share.py --tunnel
pause
