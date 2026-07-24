<#
.SYNOPSIS
  Install / control the reboot-persistent Alpecca House HQ compute-only edge
  gateway on Jason_HOLYROG (port 8765) plus its stable Tailscale Funnel.

.DESCRIPTION
  The gateway (scripts/run_house_hq_gateway.py) serves the built House HQ SPA
  statically and reverse-proxies authenticated HTTP + WebSocket traffic to the
  single authoritative primary (RygenART), with a read-only standby / offline
  fallback. It owns no CoreMind, Discord bridge, autonomy loop, memory writer,
  or continuity lease, and never imports the authoritative server.

  A logon Scheduled Task keeps the gateway bound to 127.0.0.1:8765 across
  reboots; Tailscale Funnel (persisted by tailscaled) publishes it at
  https://jason-holyrog.tailda0108.ts.net/house-hq. This script does not create
  a second speaking Alpecca instance.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$Install,
    [switch]$Remove,
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$RunGateway,
    [switch]$EnableFunnel,
    [switch]$DisableFunnel
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedHost = 'Jason_HOLYROG'
$TaskName = 'Alpecca House HQ Gateway'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Gateway = Join-Path $RepoRoot 'scripts\run_house_hq_gateway.py'
$DataDir = Join-Path $env:LOCALAPPDATA 'Alpecca\house-hq-gateway'
$LogDir = Join-Path $DataDir 'logs'
$LogPath = Join-Path $LogDir 'gateway.log'
$ConfigPath = Join-Path $DataDir 'gateway.env'
$Port = 8765
$FunnelTarget = "http://127.0.0.1:$Port"
$PublicUrl = 'https://jason-holyrog.tailda0108.ts.net/house-hq'
$ObservedHost = [System.Net.Dns]::GetHostName()

function Get-TailscaleExe {
    $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }
    $fixed = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (Test-Path -LiteralPath $fixed) { return $fixed }
    throw 'tailscale.exe was not found.'
}

function Get-PythonExe {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }
    throw 'Python was not found on PATH.'
}

function Import-GatewayConfig {
    # Optional overrides (ALPECCA_HOUSE_PRIMARY_URL / _STANDBY_URL / ...).
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { return }
    foreach ($line in Get-Content -LiteralPath $ConfigPath) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith('#')) { continue }
        $idx = $trimmed.IndexOf('=')
        if ($idx -lt 1) { continue }
        $name = $trimmed.Substring(0, $idx).Trim()
        $value = $trimmed.Substring($idx + 1).Trim()
        Set-Item -Path ("Env:{0}" -f $name) -Value $value
    }
}

if (-not [string]::Equals($ObservedHost, $ExpectedHost, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The House HQ gateway is assigned to $ExpectedHost; this machine is $ObservedHost."
}

# --- worker invoked by the scheduled task -------------------------------------
if ($RunGateway) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    if ([string]::IsNullOrWhiteSpace($env:ALPECCA_HOUSE_GATEWAY_HOST)) {
        $env:ALPECCA_HOUSE_GATEWAY_HOST = '127.0.0.1'
    }
    if ([string]::IsNullOrWhiteSpace($env:ALPECCA_HOUSE_GATEWAY_PORT)) {
        $env:ALPECCA_HOUSE_GATEWAY_PORT = "$Port"
    }
    Import-GatewayConfig
    "`n=== House HQ gateway start $(Get-Date -Format o) ===" | Add-Content -LiteralPath $LogPath
    $python = Get-PythonExe
    # uvicorn writes its normal INFO/health lines to stderr; under the strict
    # error preference PowerShell would treat those as terminating and kill a
    # perfectly healthy server. Relax it for the long-running child only.
    $ErrorActionPreference = 'Continue'
    & $python $Gateway *>> $LogPath
    exit $LASTEXITCODE
}

# --- Tailscale Funnel ---------------------------------------------------------
if ($EnableFunnel) {
    $ts = Get-TailscaleExe
    if ($PSCmdlet.ShouldProcess($PublicUrl, 'Enable Tailscale Funnel')) {
        & $ts funnel --bg $Port
        Write-Host "Funnel published: $PublicUrl -> $FunnelTarget"
        & $ts funnel status
    }
    if (-not ($Install -or $Start)) { return }
}

if ($DisableFunnel) {
    $ts = Get-TailscaleExe
    if ($PSCmdlet.ShouldProcess($PublicUrl, 'Reset Tailscale Funnel')) {
        & $ts funnel reset
        Write-Host 'Funnel reset.'
    }
    if (-not ($Remove -or $Stop)) { return }
}

# --- scheduled task lifecycle -------------------------------------------------
if ($Install) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    $identity = "$env:USERDOMAIN\$env:USERNAME"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
        '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass ' +
        ('-File "{0}" -RunGateway' -f $PSCommandPath)
    )
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings `
        -Description 'Compute-only House HQ static+proxy edge gateway (8765). No CoreMind, Discord, memory, autonomy, or continuity lease.' `
        -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Installed and started '$TaskName'. It restarts at $identity logon and after bounded failures."
    Write-Host "Log: $LogPath"
    Write-Host "Publish publicly with: -EnableFunnel  (public URL $PublicUrl)"
    return
}

if ($Remove) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed '$TaskName'. (Funnel unchanged; use -DisableFunnel to unpublish.)"
    return
}

if ($Start) { Start-ScheduledTask -TaskName $TaskName; Write-Host "Started '$TaskName'."; return }
if ($Stop) { Stop-ScheduledTask -TaskName $TaskName; Write-Host "Stopped '$TaskName'."; return }

if ($Status) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $info) { Write-Host "'$TaskName' is not installed."; return }
    [PSCustomObject]@{
        TaskName = $TaskName
        LastRunTime = $info.LastRunTime
        LastTaskResult = $info.LastTaskResult
        NumberOfMissedRuns = $info.NumberOfMissedRuns
        LogPath = $LogPath
        PublicUrl = $PublicUrl
    } | Format-List
    return
}

Write-Host 'No action requested. Verbs: -Install -Remove -Start -Stop -Status -RunGateway -EnableFunnel -DisableFunnel'
Write-Host "Public URL when funneled: $PublicUrl"
