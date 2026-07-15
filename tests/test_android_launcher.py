"""Static contracts for the installable Android launcher."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "android-launcher"


def test_android_launcher_has_installable_application_contract():
    manifest = (APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")

    assert 'applicationId "ai.alpecca.launcher"' in gradle
    assert "minSdk 26" in gradle
    assert "targetSdk 35" in gradle
    assert 'android.intent.category.LAUNCHER' in manifest
    assert 'android:usesCleartextTraffic="false"' in manifest
    assert 'android:allowBackup="false"' in manifest


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
    assert "addDiscoveryCandidate(result, BuildConfig.ALPECCA_CLOUD_STANDBY_URL);" in source
    assert source.index("fetchContinuityCandidate(result);") < source.index(
        "addDiscoveryCandidate(result, BuildConfig.ALPECCA_CLOUD_STANDBY_URL);"
    )
    assert "R.drawable.alpecca_portrait" in source
    assert 'appendQueryParameter("view", "orthographic")' in source
    assert 'RELAY_BYPASS_HEADER = "bypass-tunnel-reminder"' in source
    assert 'RELAY_BYPASS_VALUE = "alpecca-android"' in source
    assert source.count("applyRelayHeaders(connection);") == 4
    assert "Collections.singletonMap(RELAY_BYPASS_HEADER, RELAY_BYPASS_VALUE)" in source


def test_android_device_trust_validates_transcript_and_fences_clear_races():
    source = (APP / "app" / "src" / "main" / "java" / "ai" / "alpecca" / "launcher" / "MainActivity.java").read_text(encoding="utf-8")
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")

    assert 'versionCode 8' in gradle
    assert 'versionName "2.2.2"' in gradle
    assert 'APP_USER_AGENT = "AlpeccaAndroid/" + BuildConfig.VERSION_NAME' in source
    assert "validateDeviceChallenge(" in source
    assert '"alpecca-device-auth-v2".equals(lines[0])' in source
    assert "!deviceId.equals(lines[1])" in source
    assert "!origin.equals(lines[5])" in source
    assert "expiresAt > now + 180L" in source
    assert "decodedNonce.length != 32" in source
    assert "generation != trustGeneration" in source
    assert "clearLocalDeviceRegistration()" in source
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
