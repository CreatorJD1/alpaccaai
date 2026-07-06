@echo off
REM Nightly Stage 4 art drip: spend the fresh ZeroGPU quota on the current
REM target, then run the conveyor so anything that returned lands in the app.
REM Scheduled via Windows Task Scheduler ("Alpecca Stage4 Nightly Drip").
cd /d "%~dp0.."
set LOG=output\alpecca_stage4_tile_jobs\drip.log
echo ==== drip start %date% %time% ==== >> %LOG%
python scripts\run_alpecca_stage4_zerogpu_target.py >> %LOG% 2>&1
python scripts\run_alpecca_stage4_conveyor.py --apply >> %LOG% 2>&1
echo ==== drip end %date% %time% ==== >> %LOG%
