# Alpecca Android Launcher

The Android home for the authenticated House HQ experience. A full-screen
native launch and recovery surface discovers the current live Alpecca endpoint,
then hands the screen to House HQ on that same authenticated origin. The app
stores the last verified HTTPS server URL, a random public device id, WebView's
device-local session, and a non-exportable Android Keystore signing key. It does
not contain creator passwords, API tokens, memories, or a second Alpecca
runtime.

## Phone capabilities

- Keeps the creator trusted-device cookie between launches.
- Discovers the exact endpoint owned by Alpecca's active continuity lease, then
  falls back to the stable credential-free R2 record, the stable Hugging Face
  standby wake URL, and the last verified URL. The standby is not accepted as
  Alpecca until it owns the lease and reports the exact active health identity.
- Requires an exact Alpecca `/healthz` identity before opening an endpoint.
- Plays House HQ voice and live audio through Android WebView.
- Bridges camera and microphone requests through Android runtime permissions
  plus a per-server confirmation inside the launcher.
- Uses Android's system file picker for explicit image or file selection.
- Rejects cleartext HTTP and cancels invalid TLS certificates.
- Opens off-server HTTPS links in the phone's regular browser.
- Checks a stable HTTPS release manifest at startup, at most once every 12
  hours, and exposes a native Update Center with persistent check, download,
  verification, and install progress.
- Downloads an accepted APK only after confirmation, keeps it in app-private
  cache, enforces a 250 MiB limit, and verifies its SHA-256, package name,
  version, and signing certificate before offering installation.
- Opens Android's package installer only after a second explicit confirmation.
  The launcher cannot silently install an update.
- Provides **Refresh House source** to clear stale WebView assets, add a
  cache-busting source revision, and rediscover the active fenced endpoint
  without deleting the trusted-device cookie.
- Rechecks the active Alpecca health identity while the app is in the foreground.
- Rediscovers and reloads House HQ after a tunnel failure, a main-frame WebView
  network error, or Android network recovery. Retries back off while Alpecca is
  unavailable and do not clear WebView cookies or the trusted-device session.
- After the first creator password sign-in, registers a P-256 public key whose
  private key remains non-exportable in Android Keystore. A rotating tunnel can
  then issue a short-lived challenge whose transcript is validated locally and
  bound to the device id, challenge id, expiry, nonce, and exact HTTPS origin.
  The resulting revocable HttpOnly session restores access without storing or
  replaying the password.

Camera, microphone, and permission to request package installs remain visible
in Android Settings and can be revoked at any time. The package-install
permission only lets the launcher hand a verified APK to Android's user-facing
installer. The launcher does not request Accessibility Service, screen-capture,
contacts, SMS, call, location, broad storage access, or silent-install
privileges.

## Launcher updates

Version 2.2.3 (code 9) reads the update manifest from:

```text
https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/alpecca-launcher-update.json
```

The response must be HTTPS JSON with these required fields:

```json
{
  "versionCode": 9,
  "versionName": "2.2.3",
  "apkUrl": "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/AlpeccaLauncher-v2.2.3.apk",
  "sha256": "<64 lowercase hexadecimal characters>",
  "packageName": "ai.alpecca.launcher"
}
```

Both manifest and APK requests reject redirects and non-HTTPS URLs. A release
is offered only when `versionCode` is greater than the installed code and the
manifest package is exactly `ai.alpecca.launcher`. The download is then checked
against the manifest digest and its own Android package metadata. Its current
signer set must exactly match the installed launcher's signer set.

Publish an update in this order:

1. Build with the same signing key as the installed release line.
2. Upload the immutable, versioned APK URL.
3. Use the SHA-256 printed by `build_apk.ps1` in the manifest.
4. Publish the manifest last, after the APK is reachable at its final URL.

The release build intentionally retains the existing
`signingConfig signingConfigs.debug` configuration for compatibility with
already-installed personal APKs. Do not replace or regenerate the signing key
for this release line. A differently signed APK is rejected by the launcher's
preflight and by Android's installer.

## Build

Requirements are JDK 17 and Android SDK platform/build tools 35. From the repo
root:

```powershell
powershell -ExecutionPolicy Bypass -File apps\android-launcher\build_apk.ps1
```

The installable, non-debuggable personal APK is copied to:

```text
output\alpecca-launcher\AlpeccaLauncher.apk
```

The previously reviewed 2.1.2 build is available from the credential-free mobile
distribution lane at
`https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/AlpeccaLauncher-v2.1.2.apk`.
The APK contains no creator password, runtime token, memory, or tunnel hostname.

Version 2.2.3 keeps the bounded, user-confirmed update flow and the
credential-free continuity-authority lookup. It also probes the stable cloud
standby URL to wake a sleeping Space when no active endpoint answers. The app
still requires the exact `alpecca` health identity, so the health-only standby
cannot be mistaken for an active companion before fencing succeeds. Its Update
Center keeps the download bar visible through package verification and exposes
the verified install action until Android's installer is opened.

With USB debugging enabled and the phone connected, build and install with:

```powershell
powershell -ExecutionPolicy Bypass -File apps\android-launcher\build_apk.ps1 -Install
```

The app contains no temporary tunnel hostname. The desktop phone-access action
publishes the latest validated tunnel to the stable discovery record. Manual
connection settings remain available as a fallback.
