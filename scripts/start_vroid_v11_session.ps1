param(
    [string]$ManifestPath = 'data/alpecca_art_source/vrm_experiment_manifest.json',
    [switch]$NoManifestTouch,
    [switch]$NoLaunch,
    [switch]$SkipStateTouch,
    [string]$StateNote = 'Launched v11 VRoid GUI session for manual passbook execution.',
    [int]$WaitSeconds = 6
)

$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    $candidate = Resolve-Path -Path (Split-Path -Path $PSScriptRoot -Parent)
    return $candidate.Path
}

function Read-Manifest {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Manifest not found at: $Path"
    }
    return (Get-Content -Raw $Path | ConvertFrom-Json)
}

function Invoke-ManifestState {
    param(
        [Parameter(Mandatory)][string]$Manifest,
        [Parameter(Mandatory)][string]$State,
        [string]$Note
    )
    if ($NoManifestTouch.IsPresent) {
        return
    }

    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Warning "Python is not available on PATH; skipping automatic manifest state update."
        return
    }

    $manifestScript = Join-Path -Path (Resolve-RepoRoot) -ChildPath 'scripts/update_v11_vroid_state.py'
    if (Test-Path $manifestScript) {
        & python $manifestScript --manifest $Manifest --state $State --notes $Note | Write-Output
    } else {
        Write-Warning "Manifest helper missing: $manifestScript"
    }
}

$repoRoot = Resolve-RepoRoot
$manifestFile = Join-Path $repoRoot $ManifestPath
$manifest = Read-Manifest $manifestFile

$vroidExe = $manifest.tool.exe
$v11Checkpoint = $manifest.currentProbe.savedProjectPath
$passboard = $manifest.v11Passboard
$fullToolsetPass = $manifest.v11FullToolsetPass
$resumeLog = $manifest.v11ResumeLog
$controlMatrix = $manifest.v11ControlMatrix
$qaChecklist = $manifest.v11QaChecklist
$referenceDir = Join-Path $repoRoot 'data\alpecca_art_source\vrm_custom_assets\ac167033'
$checkpointPath = Join-Path $repoRoot $v11Checkpoint
$passbookPath = Join-Path $repoRoot $passboard
$fullPassPath = if ($fullToolsetPass) { Join-Path $repoRoot $fullToolsetPass } else { $null }
$qaChecklistPath = if ($qaChecklist) { Join-Path $repoRoot $qaChecklist } else { $null }
$logPath = Join-Path $repoRoot $resumeLog
$sessionCardPath = Join-Path $repoRoot 'docs\ALPECCA_V11_SESSION_CARD.md'
$matrixPath = Join-Path $repoRoot $controlMatrix
$referenceSheet = Join-Path $repoRoot 'docs\ALPECCA_V11_REFERENCE_CONTACT_SHEET.jpg'

if (-not (Test-Path $vroidExe)) {
    throw "VRoid Studio executable not found: $vroidExe"
}
if (-not (Test-Path $checkpointPath)) {
    throw "Working v11 checkpoint missing: $checkpointPath"
}
if (-not (Test-Path $passbookPath)) {
    throw "Passboard missing: $passbookPath"
}
if ($fullPassPath -and -not (Test-Path $fullPassPath)) {
    throw "Full toolset passbook missing: $fullPassPath"
}
if (-not (Test-Path $matrixPath)) {
    throw "Control matrix missing: $matrixPath"
}
if (-not (Test-Path $logPath)) {
    throw "Resume log missing: $logPath"
}
if ($qaChecklistPath -and -not (Test-Path $qaChecklistPath)) {
    Write-Warning "QA checklist missing: $qaChecklistPath (continuing)"
}

if ($NoLaunch) {
    Write-Host "Dry-run: validating only, no app/doc launches." -ForegroundColor DarkYellow
}

Write-Host "Launching Alpecca VRoid v11 design pass (experimental path)." -ForegroundColor Cyan
Write-Host "Repository : $repoRoot"
Write-Host "Checkpoint: $checkpointPath"
Write-Host "Passbook  : $passbookPath"
if ($fullPassPath) {
    Write-Host "Toolset  : $fullPassPath"
}
if ($qaChecklistPath) {
    Write-Host "QA       : $qaChecklistPath"
}
Write-Host "Control  : $matrixPath"
Write-Host "Resume log: $logPath"
Write-Host "Ref assets: $referenceDir`n"

if (-not $NoLaunch) {
    Start-Process -FilePath $vroidExe -ArgumentList ('"' + $checkpointPath + '"')
    Write-Host "VRoid Studio launched."
}

$hasReferenceSheet = Test-Path $referenceSheet
if (-not $hasReferenceSheet) {
    Write-Warning "Reference sheet missing: $referenceSheet. Run python scripts/build_v11_reference_sheet.py before editing."
}

$openedRefs = (Test-Path $referenceDir)
if (-not $NoLaunch -and $openedRefs) {
    try {
        Start-Process -FilePath explorer.exe -ArgumentList ("`"$referenceDir`"")
        $openedRefs = $true
    } catch {
        Write-Warning "Could not open reference image folder: $_"
    }
}

if ($NoLaunch) {
    Write-Host "Pass documents (not opened):" -ForegroundColor DarkGray
    Write-Host "  - $passbookPath"
    Write-Host "  - $sessionCardPath"
    Write-Host "  - $referenceSheet"
    Write-Host "  - $matrixPath"
    if ($fullPassPath) { Write-Host "  - $fullPassPath" }
    if ($qaChecklistPath) { Write-Host "  - $qaChecklistPath" }
    Write-Host "  - $logPath"
} else {
    try {
        Start-Process -FilePath explorer.exe -ArgumentList ("`"$passbookPath`"")
        Start-Process -FilePath explorer.exe -ArgumentList ("`"$sessionCardPath`"")
        Start-Process -FilePath explorer.exe -ArgumentList ("`"$referenceSheet`"")
        Start-Process -FilePath explorer.exe -ArgumentList ("`"$matrixPath`"")
        if ($fullPassPath) {
            Start-Process -FilePath explorer.exe -ArgumentList ("`"$fullPassPath`"")
        }
        if ($qaChecklistPath) {
            Start-Process -FilePath explorer.exe -ArgumentList ("`"$qaChecklistPath`"")
        }
        Start-Process -FilePath explorer.exe -ArgumentList ("`"$logPath`"")
    } catch {
        Write-Verbose "Unable to open doc explorer windows: $_"
    }
}

if (-not $SkipStateTouch) {
    Invoke-ManifestState -Manifest $manifestFile -State 'gui-resume-in-progress' -Note $StateNote
}

Write-Host "Session helper complete."
Write-Host "Keep base-model scope only during v11: face/body proportions, hair, ahoge, and blue clip." -ForegroundColor Yellow
Write-Host "Suggested flow:" -ForegroundColor Yellow
Write-Host "  1) Follow v11 passboard in-place in VRoid"
Write-Host "  2) Validate 3/4, side, full side, and back angle checks"
Write-Host "  3) Save over existing v11 checkpoint only when gates pass"
Write-Host '  4) Call: python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "v11 base lock complete"'
if (-not $openedRefs) {
    Write-Host "Reference image folder not found at data/alpecca_art_source/vrm_custom_assets/ac167033." -ForegroundColor Red
}

if (-not $NoLaunch) {
    Start-Sleep -Seconds $WaitSeconds
}
