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
$Runner = Join-Path $PSScriptRoot 'run_rog_compute_worker.py'
$ServiceDataDir = Join-Path $env:ProgramData 'Alpecca\rog-worker'
$ServiceTlsDir = Join-Path $ServiceDataDir 'tls'
$ServiceSecretPath = Join-Path $ServiceDataDir 'worker.secret'
$ServiceCertPath = Join-Path $ServiceTlsDir 'jason-holyrog.crt'
$ServiceKeyPath = Join-Path $ServiceTlsDir 'jason-holyrog.key'
$ServiceReplayPath = Join-Path $ServiceDataDir 'worker-ops.sqlite3'
$ServiceToolPathFile = Join-Path $ServiceDataDir 'tool-paths.txt'
$ServiceVenv = Join-Path $ServiceDataDir 'venv'
$ServicePython = Join-Path $ServiceVenv 'Scripts\python.exe'
$LogDir = Join-Path $ServiceDataDir 'logs'
$LogPath = Join-Path $LogDir 'dedicated-server.log'
$BlenderMarker = Join-Path $ServiceDataDir 'blender-enabled'
$BlendRoot = Join-Path $ServiceDataDir 'blend-input'
$OutputRoot = Join-Path $ServiceDataDir 'render-output'
$LegacyWorkerDataDir = Join-Path $env:LOCALAPPDATA 'Alpecca\rog-worker'
$LegacyBlenderMarker = Join-Path $LegacyWorkerDataDir 'blender-enabled'
$LegacyTlsDir = Join-Path $LegacyWorkerDataDir 'tls'
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

function Protect-ServiceDataDirectory {
    New-Item -ItemType Directory -Path $ServiceDataDir -Force | Out-Null
    & icacls.exe $ServiceDataDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not restrict the dedicated worker service-data directory.'
    }
}

function Sync-ServiceTlsIdentity {
    $legacyCert = Join-Path $LegacyTlsDir 'jason-holyrog.crt'
    $legacyKey = Join-Path $LegacyTlsDir 'jason-holyrog.key'
    if (-not (Test-Path -LiteralPath $legacyCert -PathType Leaf) -or
        -not (Test-Path -LiteralPath $legacyKey -PathType Leaf)) {
        throw 'LAN startup requires the existing ROG TLS identity; run setup_rog_worker.ps1 -InstallTls first.'
    }
    New-Item -ItemType Directory -Path $ServiceTlsDir -Force | Out-Null
    Copy-Item -LiteralPath $legacyCert -Destination $ServiceCertPath -Force
    Copy-Item -LiteralPath $legacyKey -Destination $ServiceKeyPath -Force
}

function Write-ServiceToolPaths {
    $directories = @()
    foreach ($toolName in @('git', 'node', 'npm', 'ffmpeg', 'ollama', 'python')) {
        $tool = Get-Command $toolName -ErrorAction SilentlyContinue
        if ($null -ne $tool -and -not [string]::IsNullOrWhiteSpace($tool.Source)) {
            $directories += Split-Path -Parent $tool.Source
        }
    }
    $directories = @($directories | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path -LiteralPath $_ -PathType Container)
    } | Select-Object -Unique)
    if ($directories.Count -eq 0) {
        throw 'Could not determine the local executable directories required by the ROG worker.'
    }
    Set-Content -LiteralPath $ServiceToolPathFile -Value $directories -Encoding utf8
}

function Add-ServiceToolPaths {
    if (-not (Test-Path -LiteralPath $ServiceToolPathFile -PathType Leaf)) {
        throw 'The dedicated worker tool-path configuration is missing.'
    }
    $directories = @(
        Get-Content -LiteralPath $ServiceToolPathFile | Where-Object {
            -not [string]::IsNullOrWhiteSpace($_) -and
            [System.IO.Path]::IsPathRooted($_) -and
            (Test-Path -LiteralPath $_ -PathType Container)
        } | Select-Object -Unique
    )
    if ($directories.Count -eq 0) {
        throw 'The dedicated worker tool-path configuration is invalid.'
    }
    $env:PATH = ($directories + @($env:PATH)) -join [System.IO.Path]::PathSeparator
}

function Install-ServicePython {
    param([Parameter(Mandatory = $true)][string]$BootstrapPython)

    if (-not (Test-Path -LiteralPath $ServicePython -PathType Leaf)) {
        & $BootstrapPython -m venv $ServiceVenv
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not create the dedicated ROG worker Python environment.'
        }
    }
    & $ServicePython -m ensurepip --upgrade *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not prepare pip in the dedicated ROG worker Python environment.'
    }
    Write-Host 'Installing dedicated ROG worker Python dependencies...' -ForegroundColor Cyan
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    & $ServicePython -m pip install --no-input `
        'cryptography>=43.0' 'fastapi>=0.110' 'uvicorn>=0.29'
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not install the dedicated ROG worker Python dependencies.'
    }
    & $ServicePython -c "import cryptography, fastapi, uvicorn" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'The dedicated ROG worker Python environment is incomplete.'
    }
}

if (-not [string]::Equals($ObservedHost, $ExpectedHost, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The dedicated compute server is assigned to $ExpectedHost; this machine is $ObservedHost."
}

if ($RunWorker) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Add-ServiceToolPaths
    $env:ALPECCA_ROG_WORKER_LAN = '1'
    $env:ALPECCA_ROG_WORKER_MODEL = 'qwen3.5:9b'
    $env:ALPECCA_ROG_WORKER_SECRET_FILE = $ServiceSecretPath
    $env:ALPECCA_ROG_WORKER_TLS_CERT = $ServiceCertPath
    $env:ALPECCA_ROG_WORKER_TLS_KEY = $ServiceKeyPath
    $env:ALPECCA_ROG_WORKER_REPLAY_DB = $ServiceReplayPath
    $env:ALPECCA_ROG_WORKER_PYTHON = $ServicePython
    # The task runs as SYSTEM while this checkout is owned by Jason. Scope the
    # Git trust exception to this worker process so qualification can verify
    # clean committed source without changing machine-wide Git settings.
    $env:GIT_CONFIG_COUNT = '1'
    $env:GIT_CONFIG_KEY_0 = 'safe.directory'
    $env:GIT_CONFIG_VALUE_0 = $RepoRoot
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
    $priorErrorActionPreference = $ErrorActionPreference
    $workerExitCode = 2
    try {
        # Native stderr is an ErrorRecord in Windows PowerShell.  Keep it
        # non-terminating here so the log retains the actual Python refusal.
        $ErrorActionPreference = 'Continue'
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $SetupScript -CheckWorker -StartWorker *>> $LogPath
        $workerExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $priorErrorActionPreference
    }
    if ($workerExitCode -ne 0) {
        "Dedicated worker exited with code $workerExitCode." | Add-Content -LiteralPath $LogPath
    }
    exit $workerExitCode
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
    $VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
        $Python = $VenvPython
    } else {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $PythonCommand) {
            throw 'Python was not found. Install Python 3.11 or newer, then rerun this setup.'
        }
        $Python = $PythonCommand.Source
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

    Protect-ServiceDataDirectory
    Sync-ServiceTlsIdentity
    Write-ServiceToolPaths
    Install-ServicePython -BootstrapPython $Python
    $env:ALPECCA_ROG_WORKER_PYTHON = $ServicePython

    $env:ALPECCA_ROG_WORKER_LAN = '1'
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $SetupScript -CheckWorker
    if ($LASTEXITCODE -ne 0) {
        throw 'Worker qualification failed; the dedicated task was not installed.'
    }
    & $Python $Runner --stage-secret-file $ServiceSecretPath
    if ($LASTEXITCODE -ne 0) {
        throw 'The dedicated ROG worker service secret could not be staged.'
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
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal `
        -UserId 'SYSTEM' `
        -LogonType ServiceAccount `
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
        $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($null -ne $existingTask -and $existingTask.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $TaskName
            $deadline = (Get-Date).AddSeconds(15)
            do {
                $listener = Get-NetTCPConnection -LocalPort 8788 -State Listen -ErrorAction SilentlyContinue
                if ($null -eq $listener) {
                    break
                }
                Start-Sleep -Seconds 1
            } while ((Get-Date) -lt $deadline)
            if ($null -ne $listener) {
                throw 'The existing ROG worker did not release TCP port 8788; it was not replaced.'
            }
        }
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
        -Description 'Boot-time compute-only Alpecca worker; no CoreMind, Discord, memory, or continuity authority.' `
            -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
    }
    Write-Host "Dedicated compute server installed and started: $TaskName" -ForegroundColor Green
    Write-Host 'It starts at system boot, survives user logout, and restarts after bounded failures.'
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
