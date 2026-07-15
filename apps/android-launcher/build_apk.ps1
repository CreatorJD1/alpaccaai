param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ProjectRoot "..\..")).Path
$SdkRoot = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { Join-Path $env:LOCALAPPDATA "Android\Sdk" }

if (-not $env:JAVA_HOME) {
    $PortableJdkRoot = Join-Path $RepoRoot "data\build-tools\jdk17"
    $JdkCandidates = @()
    if (Test-Path $PortableJdkRoot) {
        $JdkCandidates += Get-ChildItem $PortableJdkRoot -Directory -ErrorAction SilentlyContinue
        $JdkCandidates += Get-Item $PortableJdkRoot -ErrorAction SilentlyContinue
    }
    $JdkCandidates += Get-ChildItem "C:\Program Files\Microsoft" -Directory -Filter "jdk-17*" -ErrorAction SilentlyContinue
    $Jdk = $JdkCandidates |
        Where-Object { Test-Path (Join-Path $_.FullName "bin\java.exe") } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($Jdk) {
        $env:JAVA_HOME = $Jdk.FullName
    }
}
if (-not $env:JAVA_HOME -or -not (Test-Path (Join-Path $env:JAVA_HOME "bin\java.exe"))) {
    throw "JDK 17 was not found. Install Microsoft OpenJDK 17 or extract it under data\build-tools\jdk17."
}

$env:ANDROID_HOME = $SdkRoot
$env:ANDROID_SDK_ROOT = $SdkRoot
$env:Path = "$(Join-Path $env:JAVA_HOME 'bin');$(Join-Path $SdkRoot 'platform-tools');$env:Path"

Push-Location $ProjectRoot
try {
    & .\gradlew.bat --no-daemon assembleRelease
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle build failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

$BuiltApk = Join-Path $ProjectRoot "app\build\outputs\apk\release\app-release.apk"
$OutputDir = Join-Path $RepoRoot "output\alpecca-launcher"
$OutputApk = Join-Path $OutputDir "AlpeccaLauncher.apk"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Copy-Item -LiteralPath $BuiltApk -Destination $OutputApk -Force
Write-Host "APK ready: $OutputApk"
$Sha256 = (Get-FileHash -LiteralPath $OutputApk -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "APK SHA-256: $Sha256"

if ($Install) {
    $Adb = Join-Path $SdkRoot "platform-tools\adb.exe"
    if (-not (Test-Path $Adb)) {
        throw "adb was not found at $Adb."
    }
    & $Adb install -r $OutputApk
    if ($LASTEXITCODE -ne 0) {
        throw "adb install failed with exit code $LASTEXITCODE."
    }
}
