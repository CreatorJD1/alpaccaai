@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "MODE=%~1"
if "%MODE%"=="" (
  set "INTERACTIVE=1"
  goto menu
)

shift
set "LAUNCH_ARGS=%*"

set "INTERACTIVE=0"
if /I "%MODE%"=="tools" set "INTERACTIVE=1"
set "TOOL_CONTEXT="
if /I "%MODE%"=="help" goto show_help
if /I "%MODE%"=="-h" goto show_help
if /I "%MODE%"=="/?" goto show_help
if /I "%MODE%"=="full" goto start_here
if /I "%MODE%"=="here" goto start_here
if /I "%MODE%"=="start" goto start_here
if /I "%MODE%"=="stack" goto start_here
if /I "%MODE%"=="phone" goto share_phone
if /I "%MODE%"=="share" goto share_phone
if /I "%MODE%"=="cloud" goto wake_cloud
if /I "%MODE%"=="discord" goto start_discord
if /I "%MODE%"=="bridge" goto start_discord
if /I "%MODE%"=="vcs" goto run_vcs
if /I "%MODE%"=="frontier" goto start_frontier
if /I "%MODE%"=="tools" goto tools_menu
if /I "%MODE%"=="dev" goto tool_dev
if /I "%MODE%"=="app" goto tool_desktop
if /I "%MODE%"=="desktop" goto tool_desktop
if /I "%MODE%"=="preview" goto tool_preview
if /I "%MODE%"=="publish" goto tool_publish
if /I "%MODE%"=="voice-install" goto tool_voice_install
if /I "%MODE%"=="voice" goto tool_voice
if /I "%MODE%"=="rigger" goto tool_rigger
if /I "%MODE%"=="build-exe" goto tool_build_exe
echo Unknown mode: %MODE%
echo.
goto show_help

:menu
cls
echo ============================================
echo            A L P E C C A   L A U N C H E R
echo ============================================
echo.
echo   [1] Start Alpecca (default GUI launch)
echo   [2] Share phone link (Cloudflare tunnel)
echo   [3] Start Discord bridge
echo   [4] Open VCS Studio
echo   [5] Open Agentic Frontier
echo   [6] Tools
echo   [0] Exit
echo.
set /p MODE="Choose: "
if "%MODE%"=="1" goto start_here
if "%MODE%"=="2" goto share_phone
if "%MODE%"=="3" goto start_discord
if "%MODE%"=="4" goto run_vcs
if "%MODE%"=="5" goto start_frontier
if "%MODE%"=="6" goto tools_menu
if "%MODE%"=="0" goto done
echo Invalid choice.
pause
goto menu

:start_here
call :set_start_defaults
set "ALPECCA_AUTOWAKE=1"
where pythonw >nul 2>nul
if errorlevel 1 (
  start "Alpecca Launcher" python "apps\launcher\src\alpecca_launcher.py" %LAUNCH_ARGS%
) else (
  start "Alpecca Launcher" pythonw "apps\launcher\src\alpecca_launcher.py" %LAUNCH_ARGS%
)
goto finish

:share_phone
title Alpecca (phone link)
where cloudflared >nul 2>nul
if errorlevel 1 (
    echo cloudflared isn't installed yet - installing via winget...
    winget install --accept-source-agreements --accept-package-agreements Cloudflare.cloudflared
    echo.
    echo If winget just installed it, PATH may need a fresh window.
    echo Close and rerun this launcher if needed.
    echo.
)
if "%ALPECCA_MODEL%"=="" set "ALPECCA_MODEL=qwen3.5:9b"
set "ALPECCA_NUM_CTX=8192"
python scripts\share.py --tunnel %LAUNCH_ARGS%
goto finish

:wake_cloud
title Alpecca (cloud standby)
python scripts\wake_cloud_standby.py %LAUNCH_ARGS%
goto finish

:start_discord
echo Starting Alpecca's Discord bridge...
python scripts\run_discord_bridge.py %LAUNCH_ARGS%
echo.
echo Bridge stopped. Read any message above for the reason.
goto finish

:run_vcs
call :run_vcs_proc %LAUNCH_ARGS%
goto finish

:start_frontier
setlocal
cd /d "%~dp0"
if not defined AGENTIC_FRONTIER_PORT set "AGENTIC_FRONTIER_PORT=8870"
start "Agentic Frontier" http://127.0.0.1:%AGENTIC_FRONTIER_PORT%
python -m agentic_frontier.app %LAUNCH_ARGS%
endlocal
goto finish

:tools_menu
:tool_loop
set "TOOL_CONTEXT=1"
cls
echo ============================================
echo            A L P E C C A   T O O L S
echo ============================================
echo.
echo   [1] Dev launch - configured local model + full senses
echo   [2] Desktop app window
echo   [3] Cloudflare preview tunnel
echo   [4] Publish House HQ phone preview to R2
echo   [5] Voice tools
echo   [6] Rigged figure / Studio avatar
echo   [7] Build launcher executable
echo   [0] Back
echo.
set /p TOOLS_CHOICE="Choose: "
if "%TOOLS_CHOICE%"=="1" goto tool_dev
if "%TOOLS_CHOICE%"=="2" goto tool_desktop
if "%TOOLS_CHOICE%"=="3" goto tool_preview
if "%TOOLS_CHOICE%"=="4" goto tool_publish
if "%TOOLS_CHOICE%"=="5" goto tool_voice
if "%TOOLS_CHOICE%"=="6" goto tool_rigger
if "%TOOLS_CHOICE%"=="7" goto tool_build_exe
if "%TOOLS_CHOICE%"=="0" (
    if "%INTERACTIVE%"=="1" goto menu
    goto done
)
echo Invalid choice.
pause
goto tool_loop

:tool_dev
set "TOOL_CONTEXT=1"
setlocal
set "ALPECCA_LLM_BACKEND=ollama"
if "%ALPECCA_MODEL%"=="" set "ALPECCA_MODEL=qwen3.5:9b"
set "ALPECCA_NUM_CTX=8192"
set "ALPECCA_TTS_BACKEND=auto"
set "ALPECCA_COMPUTER_USE=1"
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
endlocal
goto tool_done

:tool_desktop
set "TOOL_CONTEXT=1"
setlocal
set "ALPECCA_COMPUTER_USE=1"
if "%ALPECCA_MODEL%"=="" set "ALPECCA_MODEL=qwen3.5:9b"
set "ALPECCA_NUM_CTX=8192"
set "ALPECCA_TTS_BACKEND=auto"
python app.py
endlocal
goto tool_done

:tool_preview
set "TOOL_CONTEXT=1"
if exist "data\cloudflared\config.yml" (
  echo Opening stable Cloudflare tunnel...
  python scripts\run_cloudflare_tunnel.py %LAUNCH_ARGS%
) else (
  echo Opening temporary Cloudflare preview...
  echo To create a permanent link, run:
  echo   python scripts\setup_cloudflare_tunnel.py --hostname alpecca.your-domain.com
  python scripts\preview.py %LAUNCH_ARGS%
)
goto tool_done

:tool_publish
set "TOOL_CONTEXT=1"
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
goto tool_done

:publish_failed
echo.
echo Publish failed. Check Cloudflare login, ALPECCA_R2_BUCKET, and R2 public access.
goto tool_done

:tool_voice
cls
echo ============================================
echo              Voice Tools
echo ============================================
echo.
echo   [1] Install voice packages
echo   [2] Check Kokoro and edge imports
echo   [0] Back
echo.
set /p VOICE_CHOICE="Choose: "
if "%VOICE_CHOICE%"=="1" goto tool_voice_install
if "%VOICE_CHOICE%"=="2" goto tool_voice_check
if "%VOICE_CHOICE%"=="0" goto tools_menu
goto tool_voice

:tool_voice_install
echo Installing edge-tts...
python -m pip install --no-cache-dir --disable-pip-version-check --timeout 30 --retries 1 -v edge-tts || python -m pip install --no-cache-dir --no-deps edge-tts
echo.
echo Installing kokoro + soundfile...
python -m pip install --no-cache-dir --disable-pip-version-check --timeout 60 --retries 1 -v kokoro soundfile || python -m pip install --no-cache-dir --no-deps kokoro soundfile
echo.
echo Install espeak-ng for Kokoro if needed:
echo https://github.com/espeak-ng/espeak-ng/releases
goto tool_done

:tool_voice_check
echo Checking Kokoro...
python -c "from kokoro import KPipeline; KPipeline(lang_code='a'); print('KOKORO: OK')"
echo.
echo Checking edge-tts...
python -c "import edge_tts; print('EDGE: OK')"
goto tool_done

:tool_rigger
set "TOOL_CONTEXT=1"
if not exist "data\avatar\her.psd" goto no_psd
echo Starting her rigged figure...
python scripts\run_rigger.py
goto tool_done

:no_psd
echo No PSD found at data\avatar\her.psd
echo Save her decomposed See-Through PSD there, then rerun this option.
goto tool_done

:tool_build_exe
set "TOOL_CONTEXT=1"
python "apps\launcher\build_launcher.py" %LAUNCH_ARGS%
goto tool_done

:tool_done
if "%INTERACTIVE%"=="1" (
  pause
  if "%TOOL_CONTEXT%"=="1" goto tools_menu
)
goto done

:run_vcs_proc
setlocal
set "VCS_ARGS=%*"
set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%apps\vcs\backend"
set "FRONTEND_DIR=%ROOT%apps\vcs\frontend"
cd /d "%ROOT%"
echo Starting VCS backend on http://127.0.0.1:8001 ...
start "VCS backend (:8001)" cmd /k ^
  "cd /d "%BACKEND_DIR%" && ..\\.venv\\Scripts\\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8001 %VCS_ARGS%"
echo Starting VCS frontend on http://localhost:3200 ...
start "VCS frontend (:3200)" cmd /k ^
  "cd /d "%FRONTEND_DIR%" && npm start"
timeout /t 12 /nobreak >nul
start "" "http://localhost:3200"
echo.
echo VCS is starting in two windows. Studio: http://localhost:3200
echo (Alpecca auto-loads; close the two windows to stop.)
endlocal
goto tool_done

:set_start_defaults
if not defined ALPECCA_COMPUTER_USE set "ALPECCA_COMPUTER_USE=0"
if not defined ALPECCA_SIGHT set "ALPECCA_SIGHT=0"
if not defined ALPECCA_FACE set "ALPECCA_FACE=0"
if not defined ALPECCA_VOICE set "ALPECCA_VOICE=0"
if not defined ALPECCA_MODEL set "ALPECCA_MODEL=qwen3.5:9b"
if not defined ALPECCA_FAST_MODEL set "ALPECCA_FAST_MODEL=qwen3.5:9b"
if not defined ALPECCA_NUM_CTX set "ALPECCA_NUM_CTX=8192"
if not defined ALPECCA_OLLAMA_TIMEOUT set "ALPECCA_OLLAMA_TIMEOUT=105"
if not defined ALPECCA_MINDPAGE set "ALPECCA_MINDPAGE=1"
if not defined ALPECCA_MINDPAGE_DISK_GB set "ALPECCA_MINDPAGE_DISK_GB=8"
if not defined ALPECCA_PRESSURE_PAGE_TARGET set "ALPECCA_PRESSURE_PAGE_TARGET=0.55"
if not defined OLLAMA_FLASH_ATTENTION set "OLLAMA_FLASH_ATTENTION=1"
if not defined OLLAMA_KV_CACHE_TYPE set "OLLAMA_KV_CACHE_TYPE=q8_0"
if not defined OLLAMA_MAX_LOADED_MODELS set "OLLAMA_MAX_LOADED_MODELS=1"
if not defined OLLAMA_NUM_PARALLEL set "OLLAMA_NUM_PARALLEL=1"
if not defined ALPECCA_CHAT_CLOUD_MODEL set "ALPECCA_CHAT_CLOUD_MODEL=gemma4:cloud"
if not defined ALPECCA_CHAT_ZEROGPU set "ALPECCA_CHAT_ZEROGPU=0"
if not defined ALPECCA_HISTORY_MESSAGES set "ALPECCA_HISTORY_MESSAGES=12"
if not defined ALPECCA_DEEP_BACKEND set "ALPECCA_DEEP_BACKEND=ollama-cloud"
if not defined ALPECCA_OLLAMA_CLOUD_MODEL set "ALPECCA_OLLAMA_CLOUD_MODEL=gemma4:cloud"
if not defined ALPECCA_REFLECT_MODEL set "ALPECCA_REFLECT_MODEL=qwen3.5:9b"
if not defined ALPECCA_VISION_BACKEND set "ALPECCA_VISION_BACKEND=local"
if not defined ALPECCA_VISION_CLOUD_MODEL set "ALPECCA_VISION_CLOUD_MODEL="
if not defined ALPECCA_VISION_MODEL set "ALPECCA_VISION_MODEL=qwen3.5:9b"
set "ALPECCA_DISCORD_MEDIA=1"
set "ALPECCA_DISCORD_CLOUD_VISION="
set "ALPECCA_DISCORD_VOICE=1"
set "ALPECCA_DISCORD_VOICE_RECEIVE=1"
set "ALPECCA_DISCORD_TTS_ENGINE=f5"
set "ALPECCA_TTS_BACKEND=auto"
goto :eof

:finish
if "%INTERACTIVE%"=="1" (
  pause
  if not "%MODE%"=="" goto done
  goto menu
)
goto done

:show_help
cls
echo.
echo Unified Alpecca launcher
echo.
echo Usage:
echo   ALPECCA_LAUNCHER.bat [command]
echo.
echo Commands:
echo   full ^| here ^| start ^| stack   Start normal local launch (defaults)
echo   phone ^| share                 Start Cloudflare phone link
echo   cloud                         Wake and check the cloud standby
echo   discord ^| bridge              Start Discord bridge
echo   vcs                           Start VCS backend + frontend
echo   frontier                      Start Agentic Frontier
echo   tools                         Open tools menu
echo   dev                           Run tools ^> Dev launch
echo   app ^| desktop                 Run tools ^> Desktop app window
echo   preview                       Run tools ^> preview/tunnel
echo   publish                       Run tools ^> publish R2
echo   voice-install                 Install voice deps (tools ^> voice tools)
echo   voice                         Check voice deps
echo   rigger                        Start rig flow
echo   build-exe                     Build launcher executable
echo.
goto done

:done
exit /b 0
