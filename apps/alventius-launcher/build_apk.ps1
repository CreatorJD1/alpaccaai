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
$GradleWrapper = Join-Path $RepoRoot "apps\android-launcher\gradlew.bat"
if (-not (Test-Path $GradleWrapper)) {
    throw "The shared Gradle wrapper is missing: $GradleWrapper"
}

& $GradleWrapper --no-daemon -p $ProjectRoot assembleRelease
if ($LASTEXITCODE -ne 0) {
    throw "Gradle build failed with exit code $LASTEXITCODE."
}

$BuiltApk = Join-Path $ProjectRoot "app\build\outputs\apk\release\app-release.apk"
$OutputDir = Join-Path $RepoRoot "output\alventius-launcher"
$OutputApk = Join-Path $OutputDir "AlventiusExperimentusLauncher.apk"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Copy-Item -LiteralPath $BuiltApk -Destination $OutputApk -Force
$Sha256 = (Get-FileHash -LiteralPath $OutputApk -Algorithm SHA256).Hash.ToLowerInvariant()

$Gradle = Get-Content -LiteralPath (Join-Path $ProjectRoot "app\build.gradle") -Raw
$VersionCode = [int]([regex]::Match($Gradle, 'versionCode\s+(\d+)').Groups[1].Value)
$VersionName = [regex]::Match($Gradle, 'versionName\s+"([^"]+)"').Groups[1].Value
if (-not $VersionCode -or -not $VersionName) {
    throw "Could not read the release version from app\build.gradle."
}

$Metadata = [ordered]@{
    packageName = "games.alventius.experimentus.launcher"
    versionCode = $VersionCode
    versionName = $VersionName
    apkPath = $OutputApk
    apkBytes = (Get-Item -LiteralPath $OutputApk).Length
    sha256 = $Sha256
}
$MetadataPath = Join-Path $OutputDir "release-metadata.json"
$Metadata | ConvertTo-Json | Set-Content -LiteralPath $MetadataPath -Encoding utf8

Write-Host "APK ready: $OutputApk"
Write-Host "APK SHA-256: $Sha256"
Write-Host "Release metadata: $MetadataPath"

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
