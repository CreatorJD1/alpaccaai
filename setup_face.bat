@echo off
REM ============================================================
REM  Set up her real neural face (Talking Head Anime 3) on your
REM  RTX 3060. Run this ONCE. Double-click it, or:  .\setup_face.bat
REM ============================================================
cd /d "%~dp0"

echo.
echo  === Setting up her neural face (THA3) for your GPU ===
echo  This downloads a few GB (PyTorch + the THA3 engine). Be patient.
echo.

echo  [1/4] Installing CUDA PyTorch (matches RTX 3060 / CUDA 12.1)...
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
python -m pip install requests pillow numpy
if errorlevel 1 goto :fail

echo.
echo  [2/4] Fetching the THA3 engine...
if not exist vendor mkdir vendor
if not exist vendor\talking-head-anime-3-demo (
  git clone https://github.com/pkhungurn/talking-head-anime-3-demo vendor\talking-head-anime-3-demo
) else (
  echo      already cloned, skipping.
)
if exist vendor\talking-head-anime-3-demo\requirements.txt (
  python -m pip install -r vendor\talking-head-anime-3-demo\requirements.txt
)

echo.
echo  [3/4] Cropping her portrait to THA3's 512 head format...
python scripts\run_talkinghead.py --prep data\avatar\portraits\idle.png

echo.
echo  [4/4] A brain that fits beside her face on a 4 GB card...
echo  On a 4 GB GPU we run a 4B model so the LLM and the face share the
echo  card. Pulling it now:
ollama pull qwen3:4b-instruct-2507

echo.
echo  MODELS (the one manual step)
echo  ------------------------------------------------------------
echo  THA3's model files are distributed by the author, not via pip.
echo  Download them and unzip into:
echo.
echo      vendor\talking-head-anime-3-demo\data\models\
echo.
echo  The link is in that repo's README ("Download the Models").
echo  On your 4 GB laptop GPU you want the LIGHT set -- the runner
echo  defaults to "separable_half" (about half the VRAM of standard).
echo  ------------------------------------------------------------
echo.
echo  When the models are in place, run her with TWO windows:
echo      Window 1:   set ALPECCA_MODEL=qwen3:4b-instruct-2507 ^&^& start_full.bat
echo      Window 2:   python scripts\run_talkinghead.py   (her face)
echo.
echo  Then refresh http://127.0.0.1:8765  -- she switches to her live
echo  neural face automatically (blink, gaze, lip-sync, head-turn).
echo.
echo  Tip: run  python scripts\doctor.py  any time to check what's
echo  still missing for her face.
echo.
goto :end

:fail
echo.
echo  Something failed in the install above. Copy the error and ask for help.
echo.

:end
pause
