# Alpecca Android Launcher

The Android home for the authenticated House HQ experience. A full-screen
native launch and recovery surface discovers the current live Alpecca endpoint,
then hands the screen to House HQ on that same authenticated origin. The app
stores only the last verified HTTPS server URL and WebView's device-local
trusted session. It does not contain creator passwords, API tokens, memories,
or a second Alpecca runtime.

## Phone capabilities

- Keeps the creator trusted-device cookie between launches.
- Discovers changing phone links from a stable, credential-free R2 record.
- Requires an exact Alpecca `/healthz` identity before opening an endpoint.
- Plays House HQ voice and live audio through Android WebView.
- Bridges camera and microphone requests through Android runtime permissions
  plus a per-server confirmation inside the launcher.
- Uses Android's system file picker for explicit image or file selection.
- Rejects cleartext HTTP and cancels invalid TLS certificates.
- Opens off-server HTTPS links in the phone's regular browser.

Camera and microphone access remain visible in Android Settings and can be
revoked at any time. The launcher does not request Accessibility Service,
screen-capture, contacts, SMS, call, location, or broad storage access.

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

With USB debugging enabled and the phone connected, build and install with:

```powershell
powershell -ExecutionPolicy Bypass -File apps\android-launcher\build_apk.ps1 -Install
```

The app contains no temporary tunnel hostname. The desktop phone-access action
publishes the latest validated tunnel to the stable discovery record. Manual
connection settings remain available as a fallback.
