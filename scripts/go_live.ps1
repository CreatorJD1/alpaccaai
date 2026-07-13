<#
  go_live.ps1  --  Bring Alpecca up for phone access, the reliable way.

  THE PROBLEM THIS FIXES:
    The server reads its allowed sign-in origins ONCE at startup
    (ALPECCA_CORS_ORIGINS). Cloudflare quick tunnels hand out a new random
    *.trycloudflare.com URL every time, so when the tunnel is started AFTER the
    server, that URL is never allow-listed and the phone password sign-in fails
    with {"detail":"same-origin password sign-in required"}.

  THE FIX:
    Start the tunnel FIRST, capture its URL, register it as the allowed origin,
    THEN start Alpecca via the normal START_HERE.bat (her brain config is
    inherited unchanged). Run this INSTEAD of START_HERE.bat + share.py.

  USAGE:
    Right-click this file -> "Run with PowerShell"
    (or from a terminal:  powershell -ExecutionPolicy Bypass -File scripts\go_live.ps1)
#>

$ErrorActionPreference = 'Stop'
$repo  = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$cfExe = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$port  = 8765

Write-Host ''
Write-Host '  A L P E C C A  -  going live for your phone' -ForegroundColor Cyan
Write-Host ''

# --- guard: never double-start on top of a running server -------------------
$busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "Something is already listening on port $port -- Alpecca may already be running." -ForegroundColor Yellow
    Write-Host "Close her existing window first, then run this again." -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'
    exit 1
}
if (-not (Test-Path $cfExe)) {
    Write-Host "cloudflared not found at $cfExe" -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

# --- 1. open the Cloudflare quick tunnel and read back its URL ---------------
$log    = Join-Path $env:TEMP 'alpecca_go_live_tunnel.log'
$errLog = "$log.err"
Remove-Item $log, $errLog -ErrorAction SilentlyContinue
Write-Host 'Opening a Cloudflare tunnel...' -ForegroundColor Cyan
$cf = Start-Process -FilePath $cfExe `
    -ArgumentList @('tunnel', '--url', "http://127.0.0.1:$port", '--no-autoupdate') `
    -RedirectStandardOutput $log -RedirectStandardError $errLog `
    -WindowStyle Minimized -PassThru

$rx  = 'https://[a-z0-9-]+\.trycloudflare\.com'
$url = $null
foreach ($i in 1..40) {
    Start-Sleep -Milliseconds 750
    $hit = Select-String -Path @($log, $errLog) -Pattern $rx -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { $url = $hit.Matches[0].Value; break }
    if ($cf.HasExited) { break }
}
if (-not $url) {
    Write-Host "Couldn't read a tunnel URL from cloudflared. Check your internet and retry." -ForegroundColor Red
    if (-not $cf.HasExited) { Stop-Process -Id $cf.Id -Force -ErrorAction SilentlyContinue }
    Read-Host 'Press Enter to exit'
    exit 1
}
Write-Host "Tunnel is up:  $url" -ForegroundColor Green

# --- 2. THE FIX: register this tunnel's origin BEFORE the server boots -------
$env:ALPECCA_CORS_ORIGINS = $url
try { $url | Set-Content (Join-Path $repo 'data\preview_public_url.txt') -Encoding utf8 } catch {}

# --- 3. hand off to the normal launcher (brain config unchanged). It inherits
#        ALPECCA_CORS_ORIGINS, so the origin is live from the server's first
#        request -- the phone password sign-in now works. ---------------------
Write-Host 'Starting Alpecca with her normal settings...' -ForegroundColor Cyan
& cmd /c 'START_HERE.bat'

# --- 4. the phone link ------------------------------------------------------
Write-Host ''
Write-Host '=================================================================' -ForegroundColor Green
Write-Host '  OPEN THIS ON YOUR PHONE:' -ForegroundColor Green
Write-Host "     $url/house-hq"
Write-Host ''
Write-Host '  Enter your creator password once -- this browser is then trusted' -ForegroundColor Green
Write-Host '  and you will not see the gate again on it.' -ForegroundColor Green
Write-Host '  Keep this link private; it reaches her over the internet.' -ForegroundColor Green
Write-Host '=================================================================' -ForegroundColor Green
Write-Host ''
Write-Host '(Leave this window and her server window open while you use her.)' -ForegroundColor DarkGray
