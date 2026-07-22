# Alventius Experimentus Android Launcher

This is an Android launcher for the separate **Alventius Experimentus** game.
It is not the Alpecca companion launcher and does not embed House HQ, CoreMind,
Alpecca memories, companion sessions, or the Alpecca continuity authority.

The launcher loads only a release-manifest-provided Agentic Frontier endpoint.
It verifies `/healthz` returns the exact separate-game identity before loading
the game in WebView:

```json
{
  "appId": "agentic-frontier",
  "kind": "game",
  "coreMind": false
}
```

## Update behavior

At launch, and at most once every six hours while the app is used, the launcher
checks this release record:

```text
https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/alventius-experimentus-launcher.json
```

The record includes the current game HTTPS URL and the latest launcher APK:

```json
{
  "schema": "alventius.android-release.v1",
  "versionCode": 2,
  "versionName": "1.0.1",
  "apkUrl": "https://public.example/mobile/AlventiusExperimentusLauncher-v1.0.1.apk",
  "sha256": "64 lowercase hexadecimal characters",
  "packageName": "games.alventius.experimentus.launcher",
  "gameUrl": "https://game.example"
}
```

When a higher version is published, the launcher shows the new release, can
download it with visible progress, and verifies the APK's HTTPS source,
SHA-256, package name, version, and signer set before it opens Android's normal
package installer. Android requires the phone owner to approve that final
install step; a normal APK cannot silently replace itself.

The manifest is published only after the immutable versioned APK is uploaded,
so a phone never discovers an incomplete release. A rotating game tunnel is not
treated as permanent: publish the current public HTTPS game endpoint in the
manifest whenever it changes, or deploy the game to a stable host.

## Build

Requires JDK 17 and Android SDK platform/build tools 35. The project reuses the
repository's pinned Gradle wrapper, so no separate wrapper copy is required.

```powershell
powershell -ExecutionPolicy Bypass -File apps\alventius-launcher\build_apk.ps1
```

The installable APK and its exact release metadata are written to:

```text
output\alventius-launcher\AlventiusExperimentusLauncher.apk
output\alventius-launcher\release-metadata.json
```

For a USB-connected phone with developer mode enabled:

```powershell
powershell -ExecutionPolicy Bypass -File apps\alventius-launcher\build_apk.ps1 -Install
```

## Publish a release

First host the separate Agentic Frontier game at a public HTTPS URL that passes
its exact `/healthz` identity. Then publish the new APK and manifest in one
ordered command:

```powershell
python scripts\publish_alventius_launcher.py `
  --apk output\alventius-launcher\AlventiusExperimentusLauncher.apk `
  --version-code 1 `
  --version-name 1.0.0 `
  --game-url https://your-public-agentic-frontier-endpoint.example
```

The command uploads the immutable APK first, then publishes
`mobile/alventius-experimentus-launcher.json` to the credential-free R2
distribution bucket. It uses the existing authenticated Wrangler setup but does
not read or embed deployment credentials in the app. Add `--print-manifest` to
generate and inspect the manifest locally without uploading.
