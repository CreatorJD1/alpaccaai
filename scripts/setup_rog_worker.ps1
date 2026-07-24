[CmdletBinding()]
param(
    [switch]$InstallSecret,
    [switch]$InstallTls,
    [switch]$RotateTls,
    [switch]$RemoveCredential,
    [switch]$CheckWorker,
    [switch]$StartWorker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedHost = 'Jason_HOLYROG'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runner = Join-Path $RepoRoot 'scripts\run_rog_compute_worker.py'
$Qualifier = Join-Path $RepoRoot 'scripts\qualify_rog_worker.py'
$DefaultModel = 'qwen3.5:9b'
$WorkerDataDir = Join-Path $env:LOCALAPPDATA 'Alpecca\rog-worker'
$TlsDir = Join-Path $WorkerDataDir 'tls'
if ([string]::IsNullOrWhiteSpace($env:ALPECCA_ROG_WORKER_TLS_CERT)) {
    $env:ALPECCA_ROG_WORKER_TLS_CERT = Join-Path $TlsDir 'jason-holyrog.crt'
}
if ([string]::IsNullOrWhiteSpace($env:ALPECCA_ROG_WORKER_TLS_KEY)) {
    $env:ALPECCA_ROG_WORKER_TLS_KEY = Join-Path $TlsDir 'jason-holyrog.key'
}
if ([string]::IsNullOrWhiteSpace($env:ALPECCA_ROG_WORKER_REPLAY_DB)) {
    $env:ALPECCA_ROG_WORKER_REPLAY_DB = Join-Path $WorkerDataDir 'worker-ops.sqlite3'
}

if ($InstallSecret -and $RemoveCredential) {
    throw 'Choose either -InstallSecret or -RemoveCredential, not both.'
}
if ($RotateTls -and ($InstallSecret -or $InstallTls -or $RemoveCredential -or $CheckWorker -or $StartWorker)) {
    throw 'Run -RotateTls by itself after manually stopping the scheduled worker.'
}

$ObservedHost = [System.Net.Dns]::GetHostName()
if (-not [string]::Equals($ObservedHost, $ExpectedHost, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "ROG worker setup is assigned to $ExpectedHost; this machine is $ObservedHost."
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

Write-Host "Checking $ExpectedHost as an isolated compute worker..." -ForegroundColor Cyan
$LanValue = [string]$env:ALPECCA_ROG_WORKER_LAN
$LanRequested = @('1', 'true', 'yes', 'on') -contains $LanValue.Trim().ToLowerInvariant()
$WorkerBindHost = if ($LanRequested) { '0.0.0.0' } else { '127.0.0.1' }
$WorkerPort = if ([string]::IsNullOrWhiteSpace($env:ALPECCA_ROG_WORKER_PORT)) {
    '8788'
} else {
    $env:ALPECCA_ROG_WORKER_PORT.Trim()
}
$QualificationArgs = @(
    $Qualifier,
    '--repo', $RepoRoot,
    '--expected-host', $ExpectedHost,
    '--worker-bind-host', $WorkerBindHost,
    '--worker-port', $WorkerPort,
    '--compact'
)
$QualificationJson = & $Python @QualificationArgs
if ($LASTEXITCODE -ne 0) {
    throw 'The read-only ROG qualification command failed.'
}
try {
    $Qualification = $QualificationJson | ConvertFrom-Json
} catch {
    throw 'The read-only ROG qualification report was not valid JSON.'
}

if (-not $Qualification.host.matches_target) {
    throw 'The qualification report did not confirm the assigned hostname.'
}

$WorkerReady = [bool]$Qualification.qualification.worker_ready
$Reasons = @($Qualification.qualification.attention_reasons)
if ($WorkerReady) {
    Write-Host 'Qualification: qualified-worker-only.' -ForegroundColor Green
} else {
    $ReasonText = if ($Reasons.Count -gt 0) { $Reasons -join ', ' } else { 'unknown' }
    Write-Warning "Qualification needs attention: $ReasonText"
}

if ($RemoveCredential) {
    & $Python $Runner --remove-secret
    if ($LASTEXITCODE -ne 0) {
        throw 'The dedicated ROG worker credential could not be removed.'
    }
    Write-Host 'No files, services, tasks, firewall rules, or models were removed.' -ForegroundColor Green
    exit 0
}

if ($InstallSecret) {
    & $Python $Runner --install-secret
    if ($LASTEXITCODE -ne 0) {
        throw 'The dedicated ROG worker credential was not installed.'
    }
}

if ($InstallTls) {
    & $Python $Runner --install-tls
    if ($LASTEXITCODE -ne 0) {
        throw 'The dedicated ROG TLS identity could not be installed.'
    }
}

if ($RotateTls) {
    Write-Host 'Rotating the stopped worker TLS identity; scheduled tasks are not stopped or started by this command.' -ForegroundColor Cyan
    & $Python $Runner --rotate-tls $ExpectedHost
    if ($LASTEXITCODE -ne 0) {
        throw 'The dedicated ROG TLS identity could not be rotated.'
    }
    Write-Host "Copy only '$env:ALPECCA_ROG_WORKER_TLS_CERT' to the primary computer, then start and verify the worker manually." -ForegroundColor Green
    exit 0
}

$Model = if ([string]::IsNullOrWhiteSpace($env:ALPECCA_ROG_WORKER_MODEL)) {
    $DefaultModel
} else {
    $env:ALPECCA_ROG_WORKER_MODEL.Trim()
}

$OllamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
$ModelReady = $false
if ($null -ne $OllamaCommand) {
    & $OllamaCommand.Source show $Model *> $null
    $ModelReady = $LASTEXITCODE -eq 0
}
if ($ModelReady) {
    Write-Host "Ollama model ready: $Model" -ForegroundColor Green
} else {
    Write-Warning "Ollama model is not ready: $Model"
}

if ($CheckWorker) {
    & $Python $Runner --check
    if ($LASTEXITCODE -ne 0) {
        throw 'The isolated worker readiness check failed.'
    }
}

if ($StartWorker) {
    if (-not $WorkerReady) {
        throw 'Startup is blocked until the read-only qualification report is ready.'
    }
    if (-not $ModelReady) {
        throw "Startup is blocked until Ollama has $Model."
    }
    if ($LanRequested) {
        if (-not (Test-Path -LiteralPath $env:ALPECCA_ROG_WORKER_TLS_CERT -PathType Leaf)) {
            throw 'LAN startup requires -InstallTls first.'
        }
        if (-not (Test-Path -LiteralPath $env:ALPECCA_ROG_WORKER_TLS_KEY -PathType Leaf)) {
            throw 'LAN startup requires -InstallTls first.'
        }
    }
    & $Python $Runner
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host 'Setup is non-destructive by default. Nothing was installed or started.' -ForegroundColor Green
Write-Host 'Next commands:' -ForegroundColor Cyan
Write-Host "  Install Python packages:  & '$Python' -m pip install -r '$RepoRoot\requirements.txt'"
Write-Host "  Install the local model:  ollama pull $DefaultModel"
Write-Host "  Store the shared secret: powershell -ExecutionPolicy Bypass -File '$PSCommandPath' -InstallSecret"
Write-Host "  Create the TLS identity: powershell -ExecutionPolicy Bypass -File '$PSCommandPath' -InstallTls"
Write-Host "  Rotate stopped-worker TLS: powershell -ExecutionPolicy Bypass -File '$PSCommandPath' -RotateTls"
Write-Host "  Validate the worker:     powershell -ExecutionPolicy Bypass -File '$PSCommandPath' -CheckWorker"
Write-Host "  Start loopback-only:     powershell -ExecutionPolicy Bypass -File '$PSCommandPath' -StartWorker"
Write-Host '  Enable private LAN for this terminal before startup:'
Write-Host "    `$env:ALPECCA_ROG_WORKER_LAN = '1'"
Write-Host "  Copy only '$env:ALPECCA_ROG_WORKER_TLS_CERT' to the primary computer."
Write-Host '  On the primary, set ALPECCA_ROG_WORKER_CA_CERT to that copied public certificate.'
Write-Host '  Stop the foreground worker with Ctrl+C.'
Write-Host "  Remove its credential:   powershell -ExecutionPolicy Bypass -File '$PSCommandPath' -RemoveCredential"
Write-Host ''
Write-Host 'This setup does not create a service, scheduled task, tunnel, firewall rule, or speaking instance.'
