param(
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = Join-Path $Root ".venv-f5-tts"
$Python = Join-Path $Venv "Scripts\python.exe"

if ($Force -and (Test-Path $Venv)) {
  Remove-Item -LiteralPath $Venv -Recurse -Force
}

if (-not (Test-Path $Python)) {
  python -m venv $Venv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install f5-tts
& $Python (Join-Path $Root "scripts\prepare_open_tts_refs.py")
& $Python (Join-Path $Root "scripts\warm_open_tts.py") --device cuda --nfe-step 16

Write-Host ""
Write-Host "F5-TTS environment ready:"
Write-Host "  $Python"
Write-Host ""
Write-Host "To make Alpecca use it:"
Write-Host "  `$env:ALPECCA_OPEN_TTS_PYTHON='$Python'"
Write-Host "  `$env:ALPECCA_TTS_BACKEND='auto'"
Write-Host ""
Write-Host "Then restart server.py."
