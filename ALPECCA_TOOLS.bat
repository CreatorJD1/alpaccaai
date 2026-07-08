@echo off
setlocal
title Alpecca Tools
cd /d "%~dp0"

:menu
cls
echo ============================================
echo              A L P E C C A   T O O L S
echo ============================================
echo.
echo   [1] Dev launch - configured local model + full senses
echo   [2] Desktop app window
echo   [3] Cloudflare preview tunnel
echo   [4] Publish House HQ phone preview to R2
echo   [5] Voice tools
echo   [6] Rigged figure / Studio avatar
echo   [0] Exit
echo.
set /p choice="Choose: "
echo.

if "%choice%"=="1" goto dev
if "%choice%"=="2" goto desktop
if "%choice%"=="3" goto preview
if "%choice%"=="4" goto publish
if "%choice%"=="5" goto voice
if "%choice%"=="6" goto rigger
if "%choice%"=="0" goto done
goto menu

:dev
set ALPECCA_LLM_BACKEND=ollama
if "%ALPECCA_MODEL%"=="" set ALPECCA_MODEL=qwen3.5:9b
set ALPECCA_NUM_CTX=8192
set ALPECCA_TTS_BACKEND=auto
set ALPECCA_COMPUTER_USE=1
echo Checking Alpecca health...
python scripts\doctor.py
echo.
echo Making sure Ollama is running...
start "Ollama" /min cmd /c "ollama serve"
timeout /t 2 >nul
echo Pulling/checking %ALPECCA_MODEL%...
ollama pull %ALPECCA_MODEL%
echo.
echo Waking Alpecca with full senses...
python scripts\run_full.py
pause
goto menu

:desktop
set ALPECCA_COMPUTER_USE=1
if "%ALPECCA_MODEL%"=="" set ALPECCA_MODEL=qwen3.5:9b
set ALPECCA_NUM_CTX=8192
set ALPECCA_TTS_BACKEND=auto
echo Opening Alpecca desktop app...
python app.py
pause
goto menu

:preview
if exist "data\cloudflared\config.yml" (
  echo Opening stable Cloudflare tunnel...
  python scripts\run_cloudflare_tunnel.py %*
) else (
  echo Opening temporary Cloudflare preview...
  echo To create a permanent link, run:
  echo   python scripts\setup_cloudflare_tunnel.py --hostname alpecca.your-domain.com
  python scripts\preview.py %*
)
pause
goto menu

:publish
if "%ALPECCA_R2_PUBLIC_URL%"=="" set "ALPECCA_R2_PUBLIC_URL=https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev"
if "%ALPECCA_R2_BUCKET%"=="" set "ALPECCA_R2_BUCKET=alpeccaai"
echo Checking Cloudflare Wrangler login...
if not exist data mkdir data
call npx.cmd --yes wrangler whoami > data\wrangler_whoami.txt 2>&1
type data\wrangler_whoami.txt
findstr /C:"not authenticated" data\wrangler_whoami.txt >nul
if not errorlevel 1 (
  echo.
  echo Wrangler is not logged in. A browser login will open now.
  call npx.cmd --yes wrangler login
  if errorlevel 1 goto publish_failed
)
echo.
echo Building and publishing House HQ to R2...
python scripts\prepare_house_hq_r2_static.py --build --public-url "%ALPECCA_R2_PUBLIC_URL%" --bucket "%ALPECCA_R2_BUCKET%" --upload
if errorlevel 1 goto publish_failed
echo.
echo House HQ preview:
echo %ALPECCA_R2_PUBLIC_URL%/house-hq
pause
goto menu

:publish_failed
echo.
echo Publish failed. Check Cloudflare login, ALPECCA_R2_BUCKET, and R2 public access.
pause
goto menu

:voice
echo ============================================
echo              Voice Tools
echo ============================================
echo.
echo   [1] Install voice packages
echo   [2] Check Kokoro and edge imports
echo   [0] Back
echo.
set /p voice_choice="Choose: "
if "%voice_choice%"=="1" goto voice_install
if "%voice_choice%"=="2" goto voice_check
goto menu

:voice_install
echo Installing edge-tts...
python -m pip install --no-cache-dir --disable-pip-version-check --timeout 30 --retries 1 -v edge-tts || python -m pip install --no-cache-dir --no-deps edge-tts
echo.
echo Installing kokoro + soundfile...
python -m pip install --no-cache-dir --disable-pip-version-check --timeout 60 --retries 1 -v kokoro soundfile || python -m pip install --no-cache-dir --no-deps kokoro soundfile
echo.
echo Install espeak-ng for Kokoro if needed:
echo https://github.com/espeak-ng/espeak-ng/releases
pause
goto voice

:voice_check
echo Checking Kokoro...
python -c "from kokoro import KPipeline; KPipeline(lang_code='a'); print('KOKORO: OK')"
echo.
echo Checking edge-tts...
python -c "import edge_tts; print('EDGE: OK')"
pause
goto voice

:rigger
if not exist "data\avatar\her.psd" goto no_psd
echo Starting her rigged figure...
python scripts\run_rigger.py
pause
goto menu

:no_psd
echo No PSD found at data\avatar\her.psd
echo Save her decomposed See-Through PSD there, then rerun this option.
pause
goto menu

:done
endlocal
