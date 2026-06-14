@echo off
REM ============================================================
REM   Alpecca - her rigged figure (CPU, zero GPU cost).
REM   Renders her full-body figure from her decomposed art and
REM   streams it to the home + the Studio mini-screen.
REM   Prerequisite: her See-Through PSD at data\avatar\her.psd
REM   Run this alongside START_HERE.bat, in its own window.
REM ============================================================
title Alpecca - rigger figure
cd /d "%~dp0"

if not exist "data\avatar\her.psd" goto nopsd
echo Starting her rigged figure (CPU)...
python scripts\run_rigger.py
goto end

:nopsd
echo No PSD found at data\avatar\her.psd
echo.
echo One-time: decompose her art into layers with See-Through, then save the
echo resulting .psd to:  data\avatar\her.psd   and run this again.
echo (Her figure then appears in the home and the Studio design screen.)
echo.

:end
pause
