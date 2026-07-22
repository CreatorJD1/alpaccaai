"""Static contracts for the separate Alventius Experimentus Android launcher."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "alventius-launcher"
SOURCE = APP / "app" / "src" / "main" / "java" / "games" / "alventius" / "experimentus" / "launcher" / "MainActivity.java"


def test_game_launcher_is_a_separate_installable_android_app():
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")
    manifest = (APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")

    assert 'applicationId "games.alventius.experimentus.launcher"' in gradle
    assert 'namespace "games.alventius.experimentus.launcher"' in gradle
    assert "versionCode 3" in gradle
    assert 'versionName "1.0.2"' in gradle
    assert "minSdk 26" in gradle
    assert "targetSdk 35" in gradle
    assert 'android.intent.category.LAUNCHER' in manifest
    assert 'android:allowBackup="false"' in manifest
    assert 'android:usesCleartextTraffic="false"' in manifest
    assert "Alpecca" not in source
    assert "CoreMind" in source
    assert "House HQ" not in source


def test_game_launcher_has_no_companion_sensor_or_identity_permissions():
    manifest = (APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    for required in (
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.REQUEST_INSTALL_PACKAGES",
    ):
        assert required in manifest
    for absent in (
        "android.permission.CAMERA",
        "android.permission.RECORD_AUDIO",
        "READ_CONTACTS",
        "READ_SMS",
        "MANAGE_EXTERNAL_STORAGE",
        "android.permission.INSTALL_PACKAGES\"",
    ):
        assert absent not in manifest


def test_game_launcher_supports_private_vrm_file_selection_without_storage_permission():
    source = SOURCE.read_text(encoding="utf-8")
    manifest = (APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert "WebChromeClient" in source
    assert "onShowFileChooser" in source
    assert "Intent.ACTION_OPEN_DOCUMENT" in source
    assert '"model/gltf-binary"' in source
    assert '"application/octet-stream"' in source
    assert "MANAGE_EXTERNAL_STORAGE" not in manifest
    assert "READ_EXTERNAL_STORAGE" not in manifest


def test_game_launcher_discovers_a_verified_game_without_exposing_addresses():
    source = SOURCE.read_text(encoding="utf-8")
    gradle = (APP / "app" / "build.gradle").read_text(encoding="utf-8")

    assert "RELEASE_MANIFEST_URL" in gradle
    assert "alventius-experimentus-launcher.json" in gradle
    assert "RELEASE_CHECK_COOLDOWN_MS = 6L * 60L * 60L * 1000L" in source
    assert "periodicReleaseCheck" in source
    for field in ("versionCode", "versionName", "apkUrl", "sha256", "packageName", "gameUrl"):
        assert f'"{field}"' in source
    assert '"agentic-frontier".equals(payload.optString("appId"))' in source
    assert '"game".equals(payload.optString("kind"))' in source
    assert "payload.optBoolean(\"coreMind\", true)" in source
    assert '"https".equalsIgnoreCase(url.getProtocol())' in source
    assert "setInstanceFollowRedirects(false)" in source
    assert "MessageDigest.getInstance(\"SHA-256\")" in source
    assert "MessageDigest.isEqual(" in source
    assert "verifyDownloadedPackage(" in source
    assert "getPackageArchiveInfo(" in source
    assert "signerDigests(installed).equals(signerDigests(archive))" in source
    assert "PackageInstaller.Session" not in source
    assert "canRequestPackageInstalls()" in source
    assert "Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES" in source
    assert "FileProvider.getUriForFile(" in source
    assert "verifyDiscoveredGame(result.gameUrl)" in source
    assert "openDiscoveredGame()" in source
    assert "activeGameReady" in source
    assert "launchButton.setEnabled(!busy && activeGameReady && !activeGameUrl.isEmpty())" in source
    for removed_ui_surface in (
        "EditText",
        "gameUrlField",
        "endpointLabel",
        "connectManual",
        "https://game.example.com",
        "Game endpoint:",
    ):
        assert removed_ui_surface not in source


def test_release_publisher_keeps_immutable_apk_before_manifest_order():
    script = ROOT / "scripts" / "publish_alventius_launcher.py"
    source = script.read_text(encoding="utf-8")
    module = ast.parse(source)

    assert "AlventiusExperimentusLauncher-v{version_name}.apk" in source
    assert "mobile/alventius-experimentus-launcher.json" in source
    assert source.index("f\"{bucket}/{apk_key}\"") < source.index("f\"{bucket}/{manifest_key}\"")
    assert "probe_game_endpoint" in source
    assert "payload.get(\"appId\") == \"agentic-frontier\"" in source
    assert "payload.get(\"coreMind\") is False" in source
    assert any(isinstance(node, ast.FunctionDef) and node.name == "release_manifest" for node in module.body)


def test_game_launcher_build_and_release_docs_are_actionable():
    build_script = (APP / "build_apk.ps1").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")
    example = (ROOT / "deploy" / "mobile" / "alventius-experimentus-launcher.example.json").read_text(encoding="utf-8")

    assert "assembleRelease" in build_script
    assert "AlventiusExperimentusLauncher.apk" in build_script
    assert "Get-FileHash" in build_script
    assert "release-metadata.json" in build_script
    assert "cannot silently replace itself" in readme
    assert "publish_alventius_launcher.py" in readme
    assert '"gameUrl"' in example
    assert '"packageName": "games.alventius.experimentus.launcher"' in example
