[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Status
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ServerHost = 'Jason_HOLYROG'
$Endpoint = 'http://jason-holyrog.tailda0108.ts.net:8790'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$SecretManager = Join-Path $PSScriptRoot 'manage_holyrog_voice_secret.py'
$ObservedHost = [System.Net.Dns]::GetHostName()

function Assert-PrimaryHost {
    if ([string]::Equals($ObservedHost, $ServerHost, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'This configures the authoritative primary voice client and must not run on Jason_HOLYROG.'
    }
}

function Resolve-ClientPython {
    $repoPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $repoPython -PathType Leaf) {
        return $repoPython
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command -or -not (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
        throw 'Python was not found for HOLYROG voice-client configuration.'
    }
    return $command.Source
}

function Test-AuthenticatedHealth {
    param([Parameter(Mandatory = $true)][string]$Python)

    $priorPythonPath = $env:PYTHONPATH
    $priorProcessSecret = $env:ALPECCA_HOLYROG_VOICE_SECRET
    try {
        $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($priorPythonPath)) {
            $RepoRoot
        } else {
            "$RepoRoot;$priorPythonPath"
        }
        $env:ALPECCA_HOLYROG_VOICE_URL = $Endpoint
        $env:ALPECCA_HOLYROG_VOICE_SECRET = $null
        & $Python -c "from alpecca.holyrog_voice import HolyrogVoiceClient; c=HolyrogVoiceClient(); ok=c.available(); print({'configured': c.enabled, 'authenticated_health': ok, 'state': c.status()['state']}); raise SystemExit(0 if ok else 2)"
        if ($LASTEXITCODE -ne 0) {
            throw 'The authenticated HOLYROG XTTS health check failed.'
        }
    } finally {
        $env:PYTHONPATH = $priorPythonPath
        $env:ALPECCA_HOLYROG_VOICE_SECRET = $priorProcessSecret
    }
}

$selected = @($Install, $Status | Where-Object { $_ }).Count
if ($selected -gt 1) {
    throw 'Choose exactly one action.'
}
if ($selected -eq 0) {
    $Status = $true
}

Assert-PrimaryHost
$python = Resolve-ClientPython

if ($Install) {
    & $python $SecretManager --derive-from-compute-worker
    if ($LASTEXITCODE -ne 0) {
        throw 'The dedicated XTTS credential could not be derived locally.'
    }
    [Environment]::SetEnvironmentVariable(
        'ALPECCA_HOLYROG_VOICE_URL',
        $Endpoint,
        [EnvironmentVariableTarget]::User
    )
    [Environment]::SetEnvironmentVariable(
        'ALPECCA_HOLYROG_VOICE_SECRET',
        $null,
        [EnvironmentVariableTarget]::User
    )
    Test-AuthenticatedHealth -Python $python
    Write-Host 'RygenART HOLYROG voice client configured without exposing its credential.' -ForegroundColor Green
    Write-Host "Endpoint: $Endpoint"
    Write-Host 'Restart the primary Alpecca launcher so it inherits the endpoint.'
    exit 0
}

$savedEndpoint = [Environment]::GetEnvironmentVariable(
    'ALPECCA_HOLYROG_VOICE_URL',
    [EnvironmentVariableTarget]::User
)
if (-not [string]::Equals($savedEndpoint, $Endpoint, [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Host 'RygenART HOLYROG voice client endpoint is not installed.' -ForegroundColor Yellow
    exit 1
}
Test-AuthenticatedHealth -Python $python
Write-Host 'RygenART HOLYROG voice client is configured and authenticated.' -ForegroundColor Green
