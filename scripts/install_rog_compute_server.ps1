[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$Install,
    [switch]$Remove,
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$RunWorker,
    [switch]$EnableBlender
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedHost = 'Jason_HOLYROG'
$TaskName = 'Alpecca ROG Compute Server'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$SetupScript = Join-Path $PSScriptRoot 'setup_rog_worker.ps1'
$LogDir = Join-Path $env:LOCALAPPDATA 'Alpecca\rog-worker\logs'
$LogPath = Join-Path $LogDir 'dedicated-server.log'
$WorkerDataDir = Join-Path $env:LOCALAPPDATA 'Alpecca\rog-worker'
$BlenderMarker = Join-Path $WorkerDataDir 'blender-enabled'
$BlendRoot = Join-Path $WorkerDataDir 'blend-input'
$OutputRoot = Join-Path $WorkerDataDir 'render-output'
$ObservedHost = [System.Net.Dns]::GetHostName()

function Find-BlenderExecutable {
    $command = Get-Command blender -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    $foundation = Join-Path $env:ProgramFiles 'Blender Foundation'
    if (-not (Test-Path -LiteralPath $foundation -PathType Container)) {
        return $null
    }
    return Get-ChildItem -LiteralPath $foundation -Filter blender.exe -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

if (-not [string]::Equals($ObservedHost, $ExpectedHost, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The dedicated compute server is assigned to $ExpectedHost; this machine is $ObservedHost."
}

if ($RunWorker) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    $env:ALPECCA_ROG_WORKER_LAN = '1'
    $env:ALPECCA_ROG_WORKER_MODEL = 'qwen3.5:9b'
    if (Test-Path -LiteralPath $BlenderMarker -PathType Leaf) {
        $blender = Find-BlenderExecutable
        if ([string]::IsNullOrWhiteSpace($blender)) {
            throw 'Blender rendering is enabled, but blender.exe could not be found.'
        }
        $env:ALPECCA_ROG_WORKER_BLENDER_EXE = $blender
        $env:ALPECCA_ROG_WORKER_BLEND_ROOT = $BlendRoot
        $env:ALPECCA_ROG_WORKER_OUTPUT_ROOT = $OutputRoot
    }
    "`n=== Dedicated ROG worker start $(Get-Date -Format o) ===" | Add-Content -LiteralPath $LogPath
    try {
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $SetupScript -CheckWorker -StartWorker *>> $LogPath
        exit $LASTEXITCODE
    } catch {
        "Dedicated worker failed: $($_.Exception.GetType().Name)" | Add-Content -LiteralPath $LogPath
        exit 2
    }
}

$selected = @($Install, $Remove, $Start, $Stop, $Status | Where-Object { $_ }).Count
if ($selected -gt 1) {
    throw 'Choose exactly one of -Install, -Remove, -Start, -Stop, or -Status.'
}
if ($selected -eq 0) {
    $Status = $true
}

if ($Install) {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $isAdmin = ([System.Security.Principal.WindowsPrincipal] `
        [System.Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [System.Security.Principal.WindowsBuiltInRole]::Administrator
        )
    if (-not $isAdmin) {
        throw 'Run this installer from an Administrator PowerShell window on Jason_HOLYROG.'
    }

    if ($EnableBlender) {
        $blender = Find-BlenderExecutable
        if ([string]::IsNullOrWhiteSpace($blender)) {
            throw 'Blender was not found. Install Blender for all users or add blender.exe to PATH.'
        }
        New-Item -ItemType Directory -Path $BlendRoot -Force | Out-Null
        New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
        New-Item -ItemType File -Path $BlenderMarker -Force | Out-Null
        Write-Host "Blender worker enabled: $blender" -ForegroundColor Green
        Write-Host "Approved input root: $BlendRoot"
        Write-Host "Approved output root: $OutputRoot"
    }

    $env:ALPECCA_ROG_WORKER_LAN = '1'
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $SetupScript -CheckWorker
    if ($LASTEXITCODE -ne 0) {
        throw 'Worker qualification failed; the dedicated task was not installed.'
    }

    $arguments = @(
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', ('"{0}"' -f $PSCommandPath),
        '-RunWorker'
    ) -join ' '
    $action = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -Argument $arguments `
        -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $principal = New-ScheduledTaskPrincipal `
        -UserId $identity `
        -LogonType Interactive `
        -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew

    if ($PSCmdlet.ShouldProcess($TaskName, 'install dedicated compute-server task')) {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Description 'Compute-only Alpecca worker; no CoreMind, Discord, memory, or continuity authority.' `
            -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
    }
    Write-Host "Dedicated compute server installed and started: $TaskName" -ForegroundColor Green
    Write-Host "It starts at $identity logon and restarts after bounded failures."
    Write-Host "Log: $LogPath"
    exit 0
}

if ($Remove) {
    if ($PSCmdlet.ShouldProcess($TaskName, 'stop and unregister dedicated compute-server task')) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    }
    Write-Host 'Dedicated task removed. Credentials, TLS keys, models, and Alpecca data were not changed.'
    exit 0
}

if ($Start) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Dedicated compute server start requested: $TaskName"
    exit 0
}

if ($Stop) {
    Stop-ScheduledTask -TaskName $TaskName
    Write-Host "Dedicated compute server stopped: $TaskName"
    exit 0
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host 'Dedicated compute server is not installed.' -ForegroundColor Yellow
    exit 1
}
$info = Get-ScheduledTaskInfo -TaskName $TaskName
[PSCustomObject]@{
    TaskName = $TaskName
    State = $task.State
    LastRunTime = $info.LastRunTime
    LastTaskResult = $info.LastTaskResult
    NextRunTime = $info.NextRunTime
    LogPath = $LogPath
    BlenderEnabled = Test-Path -LiteralPath $BlenderMarker -PathType Leaf
    BlendRoot = $BlendRoot
    OutputRoot = $OutputRoot
} | Format-List
