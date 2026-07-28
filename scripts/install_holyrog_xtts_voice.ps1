[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$Install,
    [switch]$InstallSecret,
    [switch]$RemoveCredential,
    [switch]$Remove,
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$RunServer,
    [switch]$AcceptCoquiLicense,
    [string]$ReferencePath,
    [string]$PythonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedHost = 'Jason_HOLYROG'
$TaskName = 'Alpecca HOLYROG XTTS Voice'
$PrimaryTailscaleAddress = '100.96.54.97'
$FirewallRulePrefix = 'Alpecca HOLYROG voice 8790'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VoiceServer = Join-Path $PSScriptRoot 'run_holyrog_voice_server.py'
$SecretManager = Join-Path $PSScriptRoot 'manage_holyrog_voice_secret.py'
$ServiceDataDir = Join-Path $env:ProgramData 'Alpecca\holyrog-xtts'
$ServiceSecretPath = Join-Path $ServiceDataDir 'voice.secret'
$ConfigPath = Join-Path $ServiceDataDir 'runtime.json'
$LogDir = Join-Path $ServiceDataDir 'logs'
$LogPath = Join-Path $LogDir 'voice-server.log'
$DefaultReferencePath = Join-Path $RepoRoot 'data\voice_references\xtts_reference_set'
$ObservedHost = [System.Net.Dns]::GetHostName()

function Assert-VoiceHost {
    if (-not [string]::Equals($ObservedHost, $ExpectedHost, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The dedicated HOLYROG XTTS service is assigned to $ExpectedHost; this machine is $ObservedHost."
    }
}

function Protect-ServiceDataDirectory {
    New-Item -ItemType Directory -Path $ServiceDataDir -Force | Out-Null
    & icacls.exe $ServiceDataDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not restrict the HOLYROG XTTS service-data directory.'
    }
}

function Resolve-BootstrapPython {
    $repoVenv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $repoVenv -PathType Leaf) {
        return $repoVenv
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command -or -not (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
        throw 'Python with pywin32 was not found for protected XTTS secret staging.'
    }
    return $command.Source
}

function Resolve-VoicePython {
    param([string]$RequestedPath)

    $candidate = if ([string]::IsNullOrWhiteSpace($RequestedPath)) {
        Join-Path $RepoRoot '.venv-xtts\Scripts\python.exe'
    } else {
        $RequestedPath
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "The dedicated XTTS Python executable was not found: $candidate"
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Assert-VoicePython {
    param([Parameter(Mandatory = $true)][string]$Python)

    & $Python -c "import sys; assert (3, 9) <= sys.version_info[:2] <= (3, 11), sys.version; import fastapi, uvicorn, torch; from TTS.api import TTS; assert torch.cuda.is_available(), 'CUDA is unavailable'"
    if ($LASTEXITCODE -ne 0) {
        throw 'XTTS requires Python 3.9-3.11 with TTS, FastAPI, Uvicorn, Torch, and an available CUDA device.'
    }
}

function Resolve-ReferenceDirectory {
    param([string]$RequestedPath)

    $candidate = if ([string]::IsNullOrWhiteSpace($RequestedPath)) { $DefaultReferencePath } else { $RequestedPath }
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
        throw "The XTTS reference directory was not found: $candidate"
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    $clips = @(Get-ChildItem -LiteralPath $resolved -Filter '*.wav' -File -ErrorAction Stop)
    if ($clips.Count -eq 0) {
        throw 'The XTTS reference directory contains no direct .wav clips.'
    }
    return $resolved
}

function Stage-VoiceSecret {
    param([Parameter(Mandatory = $true)][string]$BootstrapPython)

    $existing = Get-Item -LiteralPath $ServiceSecretPath -ErrorAction SilentlyContinue
    if ($null -ne $existing -and $existing.Length -ge 32) {
        Write-Host 'Existing HOLYROG XTTS service secret retained without printing its value.'
        return
    }
    & $BootstrapPython $SecretManager --stage-secret-file $ServiceSecretPath
    if ($LASTEXITCODE -ne 0) {
        throw 'The HOLYROG XTTS service secret could not be staged.'
    }
}

function Write-RuntimeConfig {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$References
    )

    [pscustomobject]@{
        python = $Python
        references = $References
        bind = '0.0.0.0'
        port = 8790
        device = 'cuda'
        require_cuda = $true
        coqui_tos_agreed = $true
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $ConfigPath -Encoding utf8
}

function Set-VoiceFirewallRule {
    $existing = @(Get-NetFirewallRule -DisplayName "$FirewallRulePrefix*" -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        $existing | Remove-NetFirewallRule
    }
    New-NetFirewallRule `
        -DisplayName "$FirewallRulePrefix (primary only)" `
        -Description "Allow TCP 8790 only from the RygenART Tailscale address ($PrimaryTailscaleAddress)." `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 8790 `
        -RemoteAddress $PrimaryTailscaleAddress `
        -InterfaceAlias 'Tailscale' `
        -Profile Any | Out-Null
}

function Wait-VoiceListener {
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $listener = Get-NetTCPConnection -LocalPort 8790 -State Listen -ErrorAction SilentlyContinue
        if ($null -ne $listener) {
            return
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw 'The dedicated HOLYROG XTTS service did not begin listening on TCP 8790. Inspect its service log.'
}

if ($RunServer) {
    Assert-VoiceHost
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    "`n=== Dedicated HOLYROG XTTS start $(Get-Date -Format o) ===" | Add-Content -LiteralPath $LogPath
    $exitCode = 1
    try {
        if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf) -or
            -not (Test-Path -LiteralPath $ServiceSecretPath -PathType Leaf)) {
            throw 'The dedicated HOLYROG XTTS runtime configuration or service secret is missing.'
        }
        $runtime = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
        $python = [string]$runtime.python
        $references = [string]$runtime.references
        if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
            -not (Test-Path -LiteralPath $references -PathType Container)) {
            throw 'The dedicated HOLYROG XTTS runtime configuration is invalid.'
        }
        $env:ALPECCA_HOLYROG_VOICE_BIND = [string]$runtime.bind
        $env:ALPECCA_HOLYROG_VOICE_PORT = [string]$runtime.port
        $env:ALPECCA_HOLYROG_VOICE_REF = $references
        $env:ALPECCA_HOLYROG_VOICE_DEVICE = [string]$runtime.device
        $env:ALPECCA_HOLYROG_VOICE_REQUIRE_CUDA = if ([bool]$runtime.require_cuda) { '1' } else { '0' }
        $env:ALPECCA_HOLYROG_VOICE_SECRET_FILE = $ServiceSecretPath
        $env:COQUI_TOS_AGREED = if ([bool]$runtime.coqui_tos_agreed) { '1' } else { '0' }
        $priorErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $python $VoiceServer *>> $LogPath
            $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
        } finally {
            $ErrorActionPreference = $priorErrorActionPreference
        }
    } catch {
        "Dedicated HOLYROG XTTS failed: $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath
    } finally {
        "Dedicated HOLYROG XTTS exited with code $exitCode." | Add-Content -LiteralPath $LogPath
    }
    exit $exitCode
}

$selected = @($Install, $InstallSecret, $RemoveCredential, $Remove, $Start, $Stop, $Status | Where-Object { $_ }).Count
if ($selected -gt 1) {
    throw 'Choose exactly one task action.'
}
if ($selected -eq 0) {
    $Status = $true
}

if ($InstallSecret) {
    $bootstrapPython = Resolve-BootstrapPython
    & $bootstrapPython $SecretManager --install-secret
    exit $LASTEXITCODE
}

if ($RemoveCredential) {
    $bootstrapPython = Resolve-BootstrapPython
    & $bootstrapPython $SecretManager --remove-secret
    exit $LASTEXITCODE
}

if ($Install) {
    Assert-VoiceHost
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = ([System.Security.Principal.WindowsPrincipal]$identity).IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    )
    if (-not $isAdmin) {
        throw 'Run this installer from an Administrator PowerShell window on Jason_HOLYROG.'
    }
    if (-not $AcceptCoquiLicense) {
        throw 'XTTS installation requires explicit Coqui license acknowledgement; rerun with -AcceptCoquiLicense only if you agree to its terms.'
    }
    $bootstrapPython = Resolve-BootstrapPython
    $voicePython = Resolve-VoicePython -RequestedPath $PythonPath
    Assert-VoicePython -Python $voicePython
    $references = Resolve-ReferenceDirectory -RequestedPath $ReferencePath
    Protect-ServiceDataDirectory
    Stage-VoiceSecret -BootstrapPython $bootstrapPython
    Write-RuntimeConfig -Python $voicePython -References $references
    Set-VoiceFirewallRule

    $arguments = @(
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', ('"{0}"' -f $PSCommandPath),
        '-RunServer'
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
    if ($PSCmdlet.ShouldProcess($TaskName, 'install dedicated HOLYROG XTTS voice task')) {
        $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($null -ne $existingTask -and $existingTask.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $TaskName
        }
        $deadline = (Get-Date).AddSeconds(15)
        do {
            $listener = Get-NetTCPConnection -LocalPort 8790 -State Listen -ErrorAction SilentlyContinue
            if ($null -eq $listener) {
                break
            }
            Start-Sleep -Seconds 1
        } while ((Get-Date) -lt $deadline)
        if ($null -ne $listener) {
            throw 'The existing HOLYROG XTTS service did not release TCP port 8790; it was not replaced.'
        }
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Description 'Dedicated GPU-only XTTS voice synthesis for the primary Alpecca host; no CoreMind, Discord, memory, or continuity authority.' `
            -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
        Wait-VoiceListener
    }
    Write-Host "Dedicated HOLYROG XTTS voice service installed and started: $TaskName" -ForegroundColor Green
    Write-Host "TCP 8790 is restricted to $PrimaryTailscaleAddress on the Tailscale interface."
    Write-Host "Log: $LogPath"
    exit 0
}

if ($Remove) {
    if ($PSCmdlet.ShouldProcess($TaskName, 'stop and unregister dedicated HOLYROG XTTS voice task')) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        $rules = @(Get-NetFirewallRule -DisplayName "$FirewallRulePrefix*" -ErrorAction SilentlyContinue)
        if ($rules.Count -gt 0) {
            $rules | Remove-NetFirewallRule
        }
    }
    Write-Host 'Dedicated HOLYROG XTTS task and its firewall rule were removed. The secret, clips, model cache, and logs were preserved.'
    exit 0
}

if ($Start) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Dedicated HOLYROG XTTS voice task start requested."
    exit 0
}

if ($Stop) {
    Stop-ScheduledTask -TaskName $TaskName
    Write-Host "Dedicated HOLYROG XTTS voice task stopped."
    exit 0
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host 'Dedicated HOLYROG XTTS voice task is not installed.' -ForegroundColor Yellow
    exit 1
}
$info = Get-ScheduledTaskInfo -TaskName $TaskName
[PSCustomObject]@{
    TaskName = $TaskName
    State = $task.State
    LastRunTime = $info.LastRunTime
    LastTaskResult = $info.LastTaskResult
    NextRunTime = $info.NextRunTime
    Port = 8790
    Bind = '0.0.0.0 (Tailscale firewall restricted)'
    CudaRequired = $true
    LogPath = $LogPath
} | Format-List
