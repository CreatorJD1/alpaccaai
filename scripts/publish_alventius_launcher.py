"""Publish one verified Alventius Experimentus Android launcher release.

The immutable APK is uploaded before the small release manifest. The Android
launcher sees only complete releases and verifies the published digest and
signer before handing an update to Android's package installer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUCKET = "alpeccaai"
DEFAULT_PUBLIC_BASE = "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev"
PACKAGE_NAME = "games.alventius.experimentus.launcher"
MAX_APK_BYTES = 250 * 1024 * 1024


def _https_url(value: str, *, label: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a credential-free HTTPS URL")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _wrangler() -> list[str] | None:
    direct = shutil.which("wrangler")
    if direct:
        return [direct]
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    return [npx, "--yes", "wrangler"] if npx else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_game_endpoint(game_url: str, *, timeout_seconds: float = 8.0) -> bool:
    """Confirm that a public endpoint is the separate Agentic Frontier game."""
    root = _https_url(game_url, label="game URL").rstrip("/")
    request = urllib.request.Request(
        f"{root}/healthz",
        headers={"Accept": "application/json", "User-Agent": "AlventiusReleasePublisher/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200 or response.url != request.full_url:
                return False
            payload = json.loads(response.read(16 * 1024).decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return (
        payload.get("ok") is True
        and payload.get("appId") == "agentic-frontier"
        and payload.get("kind") == "game"
        and payload.get("coreMind") is False
    )


def release_manifest(
    *, apk: Path, version_code: int, version_name: str, game_url: str, public_base: str
) -> dict[str, object]:
    if not apk.is_file() or apk.stat().st_size <= 0:
        raise ValueError("APK file is required")
    if apk.stat().st_size > MAX_APK_BYTES:
        raise ValueError("APK exceeds the 250 MiB launcher limit")
    if version_code <= 0:
        raise ValueError("version code must be positive")
    if not version_name or len(version_name) > 64:
        raise ValueError("version name is required and must be at most 64 characters")
    base = _https_url(public_base, label="public base").rstrip("/")
    game = _https_url(game_url, label="game URL")
    return {
        "schema": "alventius.android-release.v1",
        "versionCode": version_code,
        "versionName": version_name,
        "apkUrl": f"{base}/mobile/AlventiusExperimentusLauncher-v{version_name}.apk",
        "sha256": sha256_file(apk),
        "packageName": PACKAGE_NAME,
        "gameUrl": game,
    }


def publish(
    *, apk: Path, version_code: int, version_name: str, game_url: str,
    bucket: str, public_base: str, skip_game_probe: bool = False,
) -> dict[str, object]:
    game = _https_url(game_url, label="game URL")
    if not skip_game_probe and not probe_game_endpoint(game):
        raise RuntimeError("game endpoint did not return the exact Agentic Frontier /healthz identity")
    manifest = release_manifest(
        apk=apk,
        version_code=version_code,
        version_name=version_name,
        game_url=game,
        public_base=public_base,
    )
    wrangler = _wrangler()
    if not wrangler:
        raise RuntimeError("Wrangler was not found")

    apk_key = f"mobile/AlventiusExperimentusLauncher-v{version_name}.apk"
    manifest_key = "mobile/alventius-experimentus-launcher.json"
    with tempfile.TemporaryDirectory(prefix="alventius-release-") as temp_dir:
        manifest_path = Path(temp_dir) / "alventius-experimentus-launcher.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        subprocess.run(
            [
                *wrangler, "r2", "object", "put", f"{bucket}/{apk_key}",
                "--file", str(apk),
                "--content-type", "application/vnd.android.package-archive",
                "--remote",
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [
                *wrangler, "r2", "object", "put", f"{bucket}/{manifest_key}",
                "--file", str(manifest_path),
                "--content-type", "application/json; charset=utf-8",
                "--remote",
            ],
            cwd=ROOT,
            check=True,
        )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--version-code", type=int, required=True)
    parser.add_argument("--version-name", required=True)
    parser.add_argument("--game-url", required=True)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--public-base", default=DEFAULT_PUBLIC_BASE)
    parser.add_argument("--skip-game-probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--print-manifest", action="store_true")
    args = parser.parse_args()
    if args.print_manifest:
        document = release_manifest(
            apk=args.apk,
            version_code=args.version_code,
            version_name=args.version_name,
            game_url=args.game_url,
            public_base=args.public_base,
        )
    else:
        document = publish(
            apk=args.apk,
            version_code=args.version_code,
            version_name=args.version_name,
            game_url=args.game_url,
            bucket=args.bucket,
            public_base=args.public_base,
            skip_game_probe=args.skip_game_probe,
        )
    print(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
