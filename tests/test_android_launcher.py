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
