@echo off
REM ============================================================
REM   ALPECCA DISCORD BRIDGE - double-click to put her on Discord.
REM   Safe to run anytime: if a bridge is already running, this
REM   window says so and exits instead of double-replying.
REM   Close this window (or Ctrl+C) to take her off Discord.
REM   Needs: server running (START_HERE.bat) + bot token in
REM   data\secrets\alpecca_discord.env
REM ============================================================
title Alpecca - Discord bridge
cd /d "%~dp0"
echo Starting Alpecca's Discord bridge...
python scripts\run_discord_bridge.py
echo.
echo Bridge stopped. Read any message above for the reason.
pause
