"""Attach a native desktop window to the already-running Alpecca instance.

This compatibility entry point never constructs CoreMind or starts the backend.
Use ``START_HERE.bat`` or ``python scripts/run_full.py`` first; this process then
verifies the exact local health identity and requests a one-use protected
loopback bootstrap before opening pywebview. An explicitly configured tunnel is
also attached only after that verification.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Launch is not consent for ambient capture or device control. Explicit caller
# values still win because config.py reads these variables after setdefault.
os.environ.setdefault("ALPECCA_COMPUTER_USE", "0")
os.environ.setdefault("ALPECCA_SIGHT", "0")    # periodic screen glimpses
os.environ.setdefault("ALPECCA_FACE", "0")     # webcam expression sense
os.environ.setdefault("ALPECCA_VOICE", "0")    # mic voice-tone sense
os.environ.setdefault("ALPECCA_APPS", "")      # explicit app allowlist only

import config  # noqa: E402  (after the env defaults above)
from alpecca import auth as auth_mod  # noqa: E402
from alpecca import instance as instance_mod  # noqa: E402
from alpecca import preview as preview_mod  # noqa: E402

_tunnel_proc = None
_MAX_BOOTSTRAP_BYTES = 16 * 1024


def _credential_free_url(url: str) -> str:
    """Strip legacy credential parameters before displaying a public URL."""
    parsed = urllib.parse.urlsplit(url)
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in {"token", "access_token", "authorization", "bootstrap"}
    ]
    return urllib.parse.urlunsplit(
        parsed._replace(query=urllib.parse.urlencode(query))
    )


def _valid_bootstrap_url(url: str, base_url: str) -> bool:
    try:
        candidate = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(base_url)
        candidate_port = candidate.port
        base_port = base.port
        query_pairs = urllib.parse.parse_qsl(
            candidate.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError:
        return False
    query = dict(query_pairs)
    return (
        candidate.scheme == "http"
        and candidate.hostname == base.hostname == "127.0.0.1"
        and candidate_port == base_port
        and candidate.path == "/auth/bootstrap"
        and not candidate.username
        and not candidate.password
        and not candidate.fragment
        and len(query_pairs) == 2
        and set(query) == {"code", "next"}
        and bool(query["code"])
        and query["next"].startswith("/")
        and not query["next"].startswith("//")
    )


def _issue_local_bootstrap_url(
    path: str = "/",
    timeout: float = 5.0,
    *,
    base_url: str | None = None,
    opener=None,
) -> str | None:
    """Request one protected bootstrap from a verified loopback instance."""
    if not path.startswith("/") or path.startswith("//"):
        return None
    base_url = base_url or instance_mod.existing_server_url(config.PORT)
    if not base_url:
        return None

    endpoint = base_url.rstrip("/") + "/auth/bootstrap/request"
    try:
        secret = auth_mod.load_or_create_authorization_secret(config.HOME)
        request = urllib.request.Request(
            endpoint,
            method="POST",
            headers={auth_mod.AUTHORIZATION_HEADER: secret},
        )
        if opener is None:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({})
            ).open
        with opener(request, timeout=timeout) as response:
            if int(response.status) != 200 or response.geturl() != endpoint:
                return None
            raw = response.read(_MAX_BOOTSTRAP_BYTES + 1)
    except Exception:
        return None

    if not raw or len(raw) > _MAX_BOOTSTRAP_BYTES:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return None
    url = payload.get("url") if isinstance(payload, dict) else None
    if not isinstance(url, str) or not _valid_bootstrap_url(url, base_url):
        return None
    if path == "/":
        return url

    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query["next"] = path
    return urllib.parse.urlunsplit(
        parts._replace(query=urllib.parse.urlencode(query))
    )


def _start_tunnel(kind: str, port: int) -> None:
    """Open a public internet URL to the local server via a tunnel CLI. Best
    effort: if the binary isn't installed we say so and stay local. The token
    still guards every request, so the public URL alone can't reach her."""
    global _tunnel_proc
    if kind == "cloudflare":
        url, proc = preview_mod.ensure(port, reuse=True)
        if not url:
            print("[app] Cloudflare tunnel unavailable or not installed. Use:\n"
                  "      python scripts\\preview.py", file=sys.stderr)
            return
        _tunnel_proc = proc
        print(f"[app] Cloudflare preview: {_credential_free_url(url)}")
        print("[app] Reused the existing tunnel." if proc is None else "[app] Opened one tunnel to the existing Alpecca server.")
        return
    elif kind == "ngrok":
        exe = shutil.which("ngrok")
        if not exe:
            print("[app] ngrok not on PATH -- internet tunnel skipped "
                  "(https://ngrok.com/download).", file=sys.stderr)
            return
        # ngrok draws a TUI instead of printing a copyable line, so we don't
        # scrape its output -- we ask its local inspection API for the URL.
        _tunnel_proc = subprocess.Popen([exe, "http", str(port)])
        url = _ngrok_public_url()
        if url:
            # Mirror the cloudflare path: persist the URL so tools can discover
            # it, and print the clean shareable link.
            preview_mod.write_state(url, port, provider="ngrok")
            print(f"[app] ngrok preview: {_credential_free_url(url)}")
        else:
            print("[app] ngrok is running, but its public URL couldn't be read from "
                  "its inspection API -- check the ngrok window for the https link.",
                  file=sys.stderr)
        return
    else:
        print(f"[app] unknown ALPECCA_TUNNEL={kind!r} (expected cloudflare|ngrok|off).",
              file=sys.stderr)
        return


def _ngrok_public_url(timeout: float = 15.0) -> str | None:
    """Ask ngrok's local inspection API (port 4040) for the public https URL.

    ngrok takes a moment to establish the tunnel, so poll until it answers or
    ``timeout`` runs out. Best effort: any failure just returns ``None`` and the
    caller falls back to pointing at ngrok's own window."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels",
                                        timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for tunnel in data.get("tunnels", []):
                url = str(tunnel.get("public_url", ""))
                if url.startswith("https://"):
                    return url
        except Exception:
            pass                       # not listening yet, or no tunnel yet
        time.sleep(0.5)
    return None


def main() -> int:
    existing = instance_mod.existing_server_url(config.PORT)
    if not existing:
        print(
            "[app] No verified Alpecca CoreMind is running. Start it with "
            "START_HERE.bat or python scripts\\run_full.py, then run app.py again.",
            file=sys.stderr,
        )
        return 2

    print(f"[app] Attaching to the existing Alpecca instance at {existing}.")
    window_url = _issue_local_bootstrap_url(base_url=existing)
    if not window_url:
        print("[app] local bootstrap unavailable; no window was opened.",
              file=sys.stderr)
        return 1

    if config.TUNNEL not in ("", "off", "none"):
        _start_tunnel(config.TUNNEL, config.PORT)

    try:
        import webview
    except Exception:
        print("[app] pywebview isn't installed -- opening her in your browser instead.\n"
              "      for the native app window:  python -m pip install pywebview",
              file=sys.stderr)
        import webbrowser
        webbrowser.open(window_url)
        return 0

    webview.create_window("Alpecca", window_url, width=1200, height=820,
                          min_size=(900, 640))
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
