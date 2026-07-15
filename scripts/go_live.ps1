<#
  go_live.ps1 -- Start one complete Alpecca stack and publish phone access.

  This launcher deliberately delegates tunnel selection to scripts/share.py.
  That is the one tested tunnel manager: it reuses a healthy named/quick
  Cloudflare route, retries quick tunnels, then falls back to LocalTunnel.
  The resulting origin is written to data/preview.json before it is used, so
  password and native-device sign-in remain same-origin even when the public
  hostname rotates.

  Usage:
    powershell -ExecutionPolicy Bypass -File scripts\go_live.ps1
#>

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$port = 8765

Write-Host ''
Write-Host '  A L P E C C A  -  full stack and phone access' -ForegroundColor Cyan
Write-Host ''

# A second CoreMind/database writer is never allowed. Reuse the existing app
# manually instead of attaching another launcher with ambiguous ownership.
$busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "Alpecca already appears to be running on port $port." -ForegroundColor Yellow
    Write-Host 'Use the existing local app or its current phone link; no second instance was started.' -ForegroundColor Yellow
    exit 1
}

$pythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    Write-Host 'python.exe was not found on PATH.' -ForegroundColor Red
    exit 1
}
$pythonExe = $pythonCommand.Source

$logDir = Join-Path $repo 'data\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stackOut = Join-Path $logDir 'go_live_stack.out.log'
$stackErr = Join-Path $logDir 'go_live_stack.err.log'
$shareOut = Join-Path $logDir 'go_live_share.out.log'
$shareErr = Join-Path $logDir 'go_live_share.err.log'
Remove-Item $stackOut, $stackErr, $shareOut, $shareErr -ErrorAction SilentlyContinue

# Keep the backend loopback-only. The HTTPS relay is the remote ingress path.
$env:ALPECCA_SERVER_HOST = '127.0.0.1'
$env:PYTHONUNBUFFERED = '1'

Write-Host 'Starting Alpecca brain, voice, Discord, and app services...' -ForegroundColor Cyan
$stack = Start-Process -FilePath $pythonExe `
    -ArgumentList @('scripts\run_full.py') `
    -WorkingDirectory $repo `
    -RedirectStandardOutput $stackOut `
    -RedirectStandardError $stackErr `
    -WindowStyle Hidden -PassThru

$ready = $false
foreach ($i in 1..180) {
    Start-Sleep -Milliseconds 500
    if ($stack.HasExited) { break }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 1
        if ($health.service -eq 'alpecca' -and $health.version -eq 1) {
            $ready = $true
            break
        }
    } catch {}
}
if (-not $ready) {
    Write-Host 'The local Alpecca stack did not become healthy.' -ForegroundColor Red
    Write-Host "Check $stackErr" -ForegroundColor Yellow
    if (-not $stack.HasExited) { Stop-Process -Id $stack.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}
Write-Host 'Local full stack is healthy.' -ForegroundColor Green

# share.py owns provider choice, preview-state registration, R2 discovery
# publication, and the lifetime of whichever tunnel it opens.
Write-Host 'Publishing a secure phone route (Cloudflare, then HTTPS fallback)...' -ForegroundColor Cyan
$share = Start-Process -FilePath $pythonExe `
    -ArgumentList @('scripts\share.py', '--tunnel') `
    -WorkingDirectory $repo `
    -RedirectStandardOutput $shareOut `
    -RedirectStandardError $shareErr `
    -WindowStyle Hidden -PassThru

$url = $null
$provider = 'unknown'
$statePath = Join-Path $repo 'data\preview.json'
foreach ($i in 1..480) {
    Start-Sleep -Milliseconds 500
    if ($share.HasExited) { break }
    $published = Select-String -Path $shareOut -Pattern 'PUBLIC LINK' -Quiet -ErrorAction SilentlyContinue
    if (-not $published) { continue }
    try {
        $state = Get-Content $statePath -Raw | ConvertFrom-Json
        $candidate = [string]$state.url
        if ($candidate -match '^https://[a-z0-9.-]+$') {
            $url = $candidate.TrimEnd('/')
            $provider = [string]$state.provider
            break
        }
    } catch {}
}

if (-not $url) {
    Write-Host 'Alpecca is running locally, but no HTTPS phone relay became ready.' -ForegroundColor Red
    Write-Host "Check $shareErr and $shareOut" -ForegroundColor Yellow
    if (-not $share.HasExited) { Stop-Process -Id $share.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}

Write-Host ''
Write-Host '=================================================================' -ForegroundColor Green
Write-Host '  ALPECCA VOID ON YOUR PHONE:' -ForegroundColor Green
Write-Host "     $url/house-hq"
Write-Host ''
Write-Host "  Relay provider: $provider" -ForegroundColor Green
Write-Host '  In the Android app, enter the creator password once to enroll' -ForegroundColor Green
Write-Host '  this phone. Later hostname rotations use its device key.' -ForegroundColor Green
Write-Host '  Local app: http://127.0.0.1:8765/house-hq' -ForegroundColor Green
Write-Host '=================================================================' -ForegroundColor Green
Write-Host ''
Write-Host "Stack PID $($stack.Id); relay manager PID $($share.Id)." -ForegroundColor DarkGray
Write-Host 'Leave the laptop awake while this local instance is serving the live brain.' -ForegroundColor DarkGray
