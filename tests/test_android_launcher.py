"""Static contracts for the installable Android launcher."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "android-launcher"


def _candidate_release(gradle: str) -> tuple[int, str]:
    code = re.search(r"\bversionCode\s+(\d+)", gradle)
    name = re.search(r'\bversionName\s+"([^"]+)"', gradle)
    assert code is not None and name is not None
    return int(code.group(1)), name.group(1)


def _android_aapt() -> Path | None:
    sdk_root = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if not sdk_root and os.environ.get("LOCALAPPDATA"):
        sdk_root = str(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
    if not sdk_root:
        return None
    candidates = sorted((Path(sdk_root) / "build-tools").glob("*/aapt.exe"), reverse=True)
    return candidates[0] if candidates else None


def test_android_published_manifest_is_valid_and_candidate_output_agrees():
    release = json.loads(
        (ROOT / "deploy" / "mobile" / "alpecca-launcher-update.json").read_text(
            encoding="utf-8"
        )
    )
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")
    candidate_code, candidate_name = _candidate_release(gradle)
    documented_size = re.search(r"review candidate is `([0-9,]+)` bytes", readme)
    documented_digest = re.search(r"\n([0-9a-f]{64})\n", readme)
    assert documented_size is not None and documented_digest is not None

    assert release["versionCode"] <= candidate_code
    if release["versionCode"] == candidate_code:
        assert release["versionName"] == candidate_name
    assert release["packageName"] == "ai.alpecca.launcher"
    assert release["apkUrl"].endswith(
        f'/mobile/AlpeccaLauncher-v{release["versionName"]}.apk'
    )
    assert release["apkUrl"].startswith("https://pub-")
    assert re.fullmatch(r"[0-9a-f]{64}", release["sha256"])

    built_apk = ROOT / "output" / "alpecca-launcher" / "AlpeccaLauncher.apk"
    if built_apk.is_file():
        aapt = _android_aapt()
        assert aapt is not None, "Android aapt is required to verify an existing release APK"
        result = subprocess.run(
            [str(aapt), "dump", "badging", str(built_apk)],
            check=True,
            capture_output=True,
            text=True,
        )
        package_line = result.stdout.splitlines()[0]
        assert "name='ai.alpecca.launcher'" in package_line
        assert f"versionCode='{candidate_code}'" in package_line
        assert f"versionName='{candidate_name}'" in package_line
        digest = hashlib.sha256(built_apk.read_bytes()).hexdigest()
        assert built_apk.stat().st_size == int(documented_size.group(1).replace(",", ""))
        assert digest == documented_digest.group(1)
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        if release["versionCode"] < candidate_code:
            assert digest != release["sha256"]


def test_android_launcher_has_installable_application_contract():
    manifest = (APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")

    assert 'applicationId "ai.alpecca.launcher"' in gradle
    assert "minSdk 26" in gradle
    assert "targetSdk 35" in gradle
    assert 'android.intent.category.LAUNCHER' in manifest
    assert 'android:usesCleartextTraffic="false"' in manifest
    assert 'android:allowBackup="false"' in manifest


def test_android_companion_candidate_is_2_2_6_and_excludes_other_release_lanes():
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")
    manifest = (APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    source = (APP / "app" / "src" / "main" / "java" / "ai" / "alpecca" / "launcher" / "MainActivity.java").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")

    assert _candidate_release(gradle) == (12, "2.2.6")
    assert "Version 2.2.6 (code 12)" in readme
    assert "Android companion launcher only" in readme
    assert "does not package Agentic Frontier" in readme
    assert "agentic-frontier" not in gradle.lower()
    assert "agentic-frontier" not in manifest.lower()
    assert "agentic-frontier" not in source.lower()
    assert ".exe" not in gradle.lower()
    assert ".exe" not in manifest.lower()


def test_android_launcher_permissions_are_bounded_and_user_visible():
    manifest = (APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    source = (APP / "app" / "src" / "main" / "java" / "ai" / "alpecca" / "launcher" / "MainActivity.java").read_text(encoding="utf-8")

    assert "android.permission.CAMERA" in manifest
    assert "android.permission.RECORD_AUDIO" in manifest
    assert "requestPermissions(" in source
    assert "PermissionRequest.RESOURCE_AUDIO_CAPTURE" in source
    assert "PermissionRequest.RESOURCE_VIDEO_CAPTURE" in source
    for forbidden in (
        "READ_CONTACTS",
        "READ_SMS",
        "CALL_PHONE",
        "ACCESS_FINE_LOCATION",
        "BIND_ACCESSIBILITY_SERVICE",
        "MANAGE_EXTERNAL_STORAGE",
    ):
        assert forbidden not in manifest


def test_android_launcher_keeps_auth_in_webview_and_embeds_no_credentials():
    source = (APP / "app" / "src" / "main" / "java" / "ai" / "alpecca" / "launcher" / "MainActivity.java").read_text(encoding="utf-8")
    project = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in APP.rglob("*")
        if path.is_file() and path.suffix.lower() in {".java", ".xml", ".gradle", ".md", ".ps1", ".properties"}
    )

    assert "CookieManager.getInstance().flush()" in source
    assert "ACTION_OPEN_DOCUMENT" in source
    assert '"https".equalsIgnoreCase' in source
    assert "DISCORD_BOT_TOKEN" not in project
    assert "ALPECCA_ACCESS_TOKEN" not in project
    assert "Creator_JD#2044" not in project


def test_android_launcher_distribution_is_non_debuggable_and_origin_bounded():
    source = (APP / "app" / "src" / "main" / "java" / "ai" / "alpecca" / "launcher" / "MainActivity.java").read_text(encoding="utf-8")
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")
    build_script = (APP / "build_apk.ps1").read_text(encoding="utf-8")

    assert "assembleRelease" in build_script
    assert "assembleDebug" not in build_script
    assert "signingConfig signingConfigs.debug" in gradle
    assert "setAcceptThirdPartyCookies(webView, false)" in source
    assert "PREF_MEDIA_ORIGIN" in source
    assert "confirmWebPermission()" in source
    assert "if (!isConfiguredOrigin(current))" in source
    assert "uri.getUserInfo() != null" in source


def test_android_launcher_discovers_live_endpoint_and_has_no_baked_quick_tunnel():
    source = (APP / "app" / "src" / "main" / "java" / "ai" / "alpecca" / "launcher" / "MainActivity.java").read_text(encoding="utf-8")
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")

    assert "ALPECCA_DISCOVERY_URL" in gradle
    assert "ALPECCA_CONTINUITY_DISCOVERY_URL" in gradle
    assert "ALPECCA_CLOUD_STANDBY_URL" in gradle
    assert "alpecca-continuity-lease.jasondixon1994.workers.dev/v1/endpoint" in gradle
    assert "creatorjd-alpecca-survival-core.hf.space" in gradle
    assert "creatorjd-alpecca-cloud-core.hf.space" not in gradle
    assert "trycloudflare.com" not in gradle
    assert '"/healthz"' in source
    assert '"alpecca-mobile-discovery"' in source
    assert 'payload.optString("service")' in source
    assert "discoverAndConnect()" in source
    assert "fetchContinuityCandidate(result);" in source
    assert source.index("fetchContinuityCandidate(result);") < source.index(
        "BuildConfig.ALPECCA_DISCOVERY_URL"
    )
    assert 'payload.optJSONObject("endpoint")' in source
    assert 'endpoint.optString("holderNodeId")' in source
    assert 'holderNodeId.startsWith("local-primary:")' in source
    assert 'holderNodeId.startsWith("cloud-standby:")' in source
    assert "BuildConfig.ALPECCA_CLOUD_STANDBY_URL," in source
    assert "RuntimeLocation.CLOUD," in source
    assert source.index("fetchContinuityCandidate(result);") < source.index(
        "BuildConfig.ALPECCA_CLOUD_STANDBY_URL,"
    )
    assert "R.drawable.alpecca_portrait" in source
    assert 'appendQueryParameter("view", "orthographic")' in source
    assert 'RELAY_BYPASS_HEADER = "bypass-tunnel-reminder"' in source
    assert 'RELAY_BYPASS_VALUE = "alpecca-android"' in source
    assert source.count("applyRelayHeaders(connection);") == 4
    assert "Collections.singletonMap(RELAY_BYPASS_HEADER, RELAY_BYPASS_VALUE)" in source


def test_android_reconnect_preempts_stale_discovery_and_separates_runtime_status():
    source = (APP / "app" / "src" / "main" / "java" / "ai" / "alpecca" / "launcher" / "MainActivity.java").read_text(encoding="utf-8")

    assert "Executors.newFixedThreadPool(2)" in source
    assert 'primaryButton("Reconnect endpoint")' in source
    assert 'secondaryButton("Reconnect current endpoint")' in source
    assert "rediscoverCurrentEndpoint()" in source
    assert "restartDiscovery(DiscoveryMode.RECONNECT);" in source
    restart = source[
        source.index("private void restartDiscovery"):
        source.index("private void cancelActiveDiscoveryTask")
    ]
    assert restart.index("connectionAttempt++;") < restart.index("cancelActiveDiscoveryTask();")
    assert restart.index("cancelActiveDiscoveryTask();") < restart.index("startDiscovery(mode);")
    assert "previous.cancel(true);" in source
    assert "activeDiscoveryTask = discoveryNetwork.submit" in source
    assert 'endpointLabel.setText("Endpoint reconnect:' in source
    assert 'runtimeLabel.setText("Runtime availability:' in source
    assert "runtimeCheckingMessage(candidate.runtimeLocation)" in source
    assert "runtimeReadyMessage(candidate.runtimeLocation)" in source
    assert "The laptop must already be powered on and running Alpecca for local access." in source


def test_android_device_trust_validates_transcript_and_fences_clear_races():
    source = (APP / "app" / "src" / "main" / "java" / "ai" / "alpecca" / "launcher" / "MainActivity.java").read_text(encoding="utf-8")
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")

    assert 'versionCode 12' in gradle
    assert 'versionName "2.2.6"' in gradle
    assert 'APP_USER_AGENT = "AlpeccaAndroid/" + BuildConfig.VERSION_NAME' in source
    assert "validateDeviceChallenge(" in source
    assert '"alpecca-device-auth-v2".equals(lines[0])' in source
    assert "!deviceId.equals(lines[1])" in source
    assert "!origin.equals(lines[5])" in source
    assert "expiresAt > now + 180L" in source
    assert "decodedNonce.length != 32" in source
    assert "generation != trustGeneration" in source
    assert "clearLocalDeviceRegistration()" in source
    assert "installDeviceCookies(" in source
    assert "manager.setCookie(origin, cookies.get(index), accepted ->" in source
    assert source.index("manager.flush();") < source.index("completion.run();", source.index("manager.flush();"))
    assert 'String deviceId = preferences.getString(PREF_DEVICE_ID, "");' in source
    assert "if (!deviceId.isEmpty() && hasDeviceKey())" in source
    assert source.index("pendingWebPermission.grant(pendingWebResources);") < source.index('String trustedOrigin = preferences.getString(PREF_MEDIA_ORIGIN, "");')
    assert "revokeDeviceRegistration(" in source
    assert "removeAllCookies(cleared ->" in source
    assert "removeAllCookies(null)" not in source


def test_android_launcher_update_flow_is_https_verified_and_user_confirmed():
    source = (APP / "app" / "src" / "main" / "java" / "ai" / "alpecca" / "launcher" / "MainActivity.java").read_text(encoding="utf-8")
    manifest = (APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    file_paths = (APP / "app" / "src" / "main" / "res" / "xml" / "update_file_paths.xml").read_text(encoding="utf-8")
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")
    build_script = (APP / "build_apk.ps1").read_text(encoding="utf-8")
    gradle_properties = (APP / "gradle.properties").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")

    assert 'ALPECCA_UPDATE_MANIFEST_URL' in gradle
    assert '"https://pub-' in gradle
    assert 'PREF_LAST_UPDATE_CHECK_MS = "last_update_check_ms"' in source
    assert "UPDATE_CHECK_COOLDOWN_MS = 12L * 60L * 60L * 1000L" in source
    assert "checkForUpdates(false);" in source
    assert "checkForUpdates(true);" in source
    for field in ("versionCode", "versionName", "apkUrl", "sha256", "packageName"):
        assert f'payload.opt("{field}")' in source or f'requiredManifestString(payload, "{field}")' in source

    assert '"https".equalsIgnoreCase(url.getProtocol())' in source
    assert "setInstanceFollowRedirects(false)" in source
    assert 'MessageDigest.getInstance("SHA-256")' in source
    assert "MessageDigest.isEqual(" in source
    assert "MAX_UPDATE_APK_BYTES" in source
    assert "verifyDownloadedPackage(" in source
    assert "getPackageArchiveInfo(" in source
    assert "installedSigners.equals(updateSigners)" in source
    assert 'text("ALPECCA APP UPDATES"' in source
    assert 'primaryButton("Install Alpecca update")' in source
    assert 'secondaryButton("Refresh House source")' in source
    assert 'showUpdateProgress("Update verified. Ready to install."' in source
    assert "listener.onProgress(100);" in source
    assert 'appendQueryParameter(\n                "source_refresh"' in source
    assert "webView.clearCache(true)" in source
    assert "startDiscovery(DiscoveryMode.SOURCE_REFRESH);" in source

    assert "android.permission.REQUEST_INSTALL_PACKAGES" in manifest
    assert 'android.permission.INSTALL_PACKAGES"' not in manifest
    assert "android.permission.DELETE_PACKAGES" not in manifest
    assert "androidx.core.content.FileProvider" in manifest
    assert 'android:authorities="${applicationId}.updates"' in manifest
    assert 'android:exported="false"' in manifest
    assert '<cache-path' in file_paths
    assert 'path="updates/"' in file_paths
    assert "FileProvider.getUriForFile(" in source
    assert "canRequestPackageInstalls()" in source
    assert "Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES" in source
    assert "Intent.ACTION_VIEW" in source
    assert "Intent.FLAG_GRANT_READ_URI_PERMISSION" in source
    assert '.setPositiveButton("Open installer"' in source
    assert "PackageInstaller.Session" not in source
    assert "getPackageInstaller(" not in source
    assert "android.useAndroidX=true" in gradle_properties
    assert 'exclude group: "androidx.profileinstaller"' in gradle

    assert "Get-FileHash" in build_script
    assert "APK SHA-256" in build_script
    assert "cannot silently install" in readme
    assert "Publish an update in this order" in readme
    assert "Version 2.2.6 (code 12)" in readme
