"""Cloudflare preview manager -- expose the local server on a public URL and,
crucially, make that URL DISCOVERABLE.

`scripts/share.py` and `app.py` already know how to open a Cloudflare quick
tunnel, but they only let cloudflared's public URL scroll past in the console.
Nothing captures it, so a tool (another agent, a test, the UI, *me*) can't answer
the one question that makes a tunnel usable as a preview system: "what is my
public URL right now?" This module closes that gap.

It does three small, honest things:

  1. starts (or reuses) a Cloudflare quick tunnel to the local port,
  2. parses the ``*.trycloudflare.com`` URL out of cloudflared's output and
     PERSISTS it to a small state file under ``HOME`` (the single source of
     truth for the preview URL -- ``preview.json`` plus a plain
     ``preview_url.txt`` for eyeballing), and
  3. health-checks the public URL so callers know it is actually live.

The pure helpers (URL parsing, state read/write, health check with an injectable
opener) carry the logic and are unit-tested without the network or cloudflared,
in keeping with the rest of the codebase. The process-spawning parts degrade
gracefully: no cloudflared on PATH, or a tunnel that never prints a URL, returns
``None`` rather than crashing.

PRIVACY: a quick-tunnel URL is random per run and the link is only as private as
the server's ``ALPECCA_ACCESS_TOKEN``. With a blank token (the private-local
default) anyone holding the URL can reach her -- so treat the URL as a secret and
set a token before sharing it. This mirrors the warning in ``scripts/share.py``.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import config
from config import HOME, PORT

# cloudflared prints its quick-tunnel URL inside a banner; this matches the URL
# wherever it appears in a line (it is surrounded by box-drawing or whitespace).
_TUNNEL_URL_RE = re.compile(r"https://(?=[a-z0-9-]*-)[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)

# Where the discovered URL lives. One JSON record of truth, plus a plain-text
# mirror so a human (or `cat`) can read the bare URL with zero parsing.
STATE_FILE = "preview.json"
URL_FILE = "preview_url.txt"
HOUSE_HQ_LIVE_URL_FILE = "house_hq_live_url.txt"

# Common Windows install location, so we find cloudflared even if a shell's PATH
# is stale (winget drops it here). PATH is still tried first.
_WINDOWS_FALLBACKS = (
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
)


@dataclass
class PreviewState:
    """The captured preview, as persisted. ``url`` is the public https link;
    ``port`` is the local port it fronts; ``ts`` is when it was captured."""

    url: str
    port: int
    ts: float
    provider: str = "cloudflare"


# --- pure helpers (no network, no subprocess) -- unit-tested -----------------

def parse_tunnel_url(line: str) -> str | None:
    """Return the ``*.trycloudflare.com`` URL in a cloudflared output line, if any.

    cloudflared emits the URL once, framed in a banner; every other line is noise.
    Kept pure so the parser is testable against real captured output samples.
    """
    if not line:
        return None
    match = _TUNNEL_URL_RE.search(line)
    return match.group(0) if match else None


def state_path(home: Path = HOME) -> Path:
    return Path(home) / STATE_FILE


def url_path(home: Path = HOME) -> Path:
    return Path(home) / URL_FILE


def house_hq_live_url_path(home: Path = HOME) -> Path:
    return Path(home) / HOUSE_HQ_LIVE_URL_FILE


def write_state(url: str, port: int = PORT, *, ts: float | None = None,
                provider: str = "cloudflare", home: Path = HOME) -> dict:
    """Persist the discovered URL as the single source of truth. Returns the dict.

    ``ts`` is injectable so tests stay deterministic (the codebase avoids wall
    clock in pure paths); production callers pass the real time.
    """
    state = PreviewState(url=url.strip(), port=int(port),
                         ts=float(ts if ts is not None else time.time()),
                         provider=provider)
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    state_path(home).write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    url_path(home).write_text(state.url + "\n", encoding="utf-8")
    return asdict(state)


def write_house_hq_live_url(shell_url: str, backend_url: str, *, home: Path = HOME) -> str:
    """Persist the static House HQ URL wired to this live backend and token."""
    live_url = with_backend_url(shell_url, backend_url)
    if not live_url:
        return ""
    path = house_hq_live_url_path(home)
    path.write_text(live_url + "\n", encoding="utf-8")

    r2_record = Path(home) / "r2_preview.json"
    try:
        record = json.loads(r2_record.read_text(encoding="utf-8"))
    except Exception:
        record = {}
    record["liveBackendUrl"] = backend_url.rstrip("/")
    record["houseHqLiveUrl"] = live_url
    record["tokenSharedWithHouse"] = bool(config.ACCESS_TOKEN)
    try:
        r2_record.write_text(json.dumps(record, indent=2), encoding="utf-8")
    except Exception:
        pass
    return live_url


def read_state(home: Path = HOME) -> dict | None:
    """Return the persisted preview record, or ``None`` if none has been captured."""
    path = state_path(home)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def clear_state(home: Path = HOME) -> None:
    """Forget the captured URL -- called when we tear down a tunnel we own, so a
    later reader doesn't trust a dead link."""
    for path in (state_path(home), url_path(home)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


# An opener is ``(url, timeout) -> int status`` so the health check is testable
# without touching the network. Production uses :func:`_urlopen_status`.
Opener = Callable[[str, float], int]


def _urlopen_status(url: str, timeout: float) -> int:
    """GET ``url`` and return its HTTP status.

    ``urllib.request.urlopen`` RAISES ``HTTPError`` on a 4xx/5xx instead of
    returning it -- but a 401/403/404 is the server *answering*, which is exactly
    what proves the tunnel is live. So we catch ``HTTPError`` and hand back its
    code; only true connection failures (``URLError`` without a code: dead tunnel,
    DNS, refused) propagate, to be caught by :func:`health_check` as unhealthy.
    Without this, a token-gated 401 would look dead and break tunnel reuse.
    """
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "alpecca-preview"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted URL)
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def health_check(url: str, *, route: str = "/system/doctor", timeout: float = 12.0,
                 opener: Opener | None = None) -> bool:
    """Is the public URL actually serving the app?

    "Reachable" means the tunnel forwarded our request and the server answered.
    A token-gated server replies ``401`` -- that still proves the link is live, so
    any HTTP status below ``500`` counts as healthy (mirrors ``app.py``'s
    ``_wait_until_up``, which treats even a 401 as "it's up"). Connection errors
    (dead tunnel, wrong URL) raise and are caught as unhealthy.
    """
    if not url:
        return False
    opener = opener or _urlopen_status
    target = url.rstrip("/") + route
    try:
        status = opener(target, timeout)
    except Exception:
        return False
    return 0 < status < 500


def find_cloudflared() -> str | None:
    """Locate the cloudflared binary on PATH, falling back to known install dirs."""
    exe = shutil.which("cloudflared")
    if exe:
        return exe
    for candidate in _WINDOWS_FALLBACKS:
        if Path(candidate).exists():
            return candidate
    return None


def link_is_gated(token: str | None = None) -> bool:
    """Whether a public link would actually be protected.

    With a blank ``ALPECCA_ACCESS_TOKEN`` the server's auth gate is fully open
    (``server.py`` ``_token_ok``: no token -> every request passes), so the random
    subdomain is the *only* secret -- which is not access control. Read live from
    ``config`` so a token set just before launch is honored.
    """
    tok = config.ACCESS_TOKEN if token is None else token
    return bool(tok)


def with_access_token(url: str, token: str | None = None) -> str:
    """Return a clean shareable Alpecca URL.

    This Alpecca instance carries its shared identity in the served app/cookie
    layer, so public preview links should not expose or ask for a credential in
    the address bar.
    """
    if not url:
        return url
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "token"]
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))


def with_backend_url(shell_url: str, backend_url: str, token: str | None = None) -> str:
    """Return a static House HQ shell URL wired to a live backend URL.

    The R2/static shell cannot infer the live FastAPI backend by itself. This
    helper builds the URL the mobile browser actually needs:
    ``/house-hq?backend=<live tunnel>``. The House HQ bundle carries the shared
    Alpecca app identity internally.
    """
    if not shell_url:
        return ""
    parsed = urllib.parse.urlsplit(shell_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key not in {"backend", "core", "alpeccaBackend", "alpecca", "token"}]
    if backend_url:
        query.append(("backend", backend_url.rstrip("/")))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))


def configured_public_url() -> str:
    """Return the stable configured public base URL, if any."""
    url = getattr(config, "PUBLIC_URL", "") or ""
    if not url and getattr(config, "CLOUDFLARE_HOSTNAME", ""):
        url = "https://" + str(config.CLOUDFLARE_HOSTNAME).strip().strip("/")
    return url.strip().rstrip("/")


def named_tunnel_config_path(home: Path = HOME) -> Path:
    configured = getattr(config, "CLOUDFLARE_CONFIG", None)
    return Path(configured) if configured else Path(home) / "cloudflared" / "config.yml"


def named_tunnel_ready(home: Path = HOME) -> dict:
    """Machine-readable status for the stable Cloudflare path."""
    url = configured_public_url()
    cfg = named_tunnel_config_path(home)
    return {
        "configured": bool(url),
        "url": url,
        "hostname": getattr(config, "CLOUDFLARE_HOSTNAME", ""),
        "tunnel": getattr(config, "CLOUDFLARE_TUNNEL_NAME", "alpecca"),
        "config": str(cfg),
        "config_exists": cfg.exists(),
        "cloudflared": find_cloudflared() or "",
    }


_INSECURE_WARNING = (
    "\n" + "!" * 60 + "\n"
    "  WARNING: this public link is UNAUTHENTICATED.\n"
    "  ALPECCA_ACCESS_TOKEN is blank, so anyone with the URL can reach\n"
    "  her memories, journal, live state -- and, if ALPECCA_FILES is on,\n"
    "  enumerate this machine's files. Set a token before sharing:\n"
    "      setx ALPECCA_ACCESS_TOKEN \"<a-long-secret>\"   (then restart her)\n"
    + "!" * 60 + "\n"
)


# --- tunnel lifecycle (spawns cloudflared) -----------------------------------

def start_tunnel(port: int = PORT, *, home: Path = HOME, exe: str | None = None,
                 log_file: Path | None = None) -> tuple[subprocess.Popen | None, threading.Event, dict]:
    """Open a Cloudflare quick tunnel to ``port`` and capture its URL.

    Returns ``(process, ready_event, holder)``. ``holder["url"]`` is filled and
    ``ready_event`` is set the moment cloudflared prints its public URL (which is
    also persisted via :func:`write_state` at that instant). The caller owns the
    process: keep it alive to keep the tunnel up, and terminate it to close it.

    Best effort: with no cloudflared installed, returns ``(None, set-event, {})``
    so callers can branch without exception handling.
    """
    exe = exe or find_cloudflared()
    holder: dict = {}
    ready = threading.Event()
    if not exe:
        ready.set()
        return None, ready, holder

    proc = subprocess.Popen(
        [exe, "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    log = open(log_file, "a", encoding="utf-8") if log_file else None

    def pump() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                if log:
                    log.write(line)
                    log.flush()
                if "url" not in holder:
                    found = parse_tunnel_url(line)
                    if found:
                        holder["url"] = found
                        write_state(found, port, home=home)
                        ready.set()
        finally:
            if log:
                log.close()

    threading.Thread(target=pump, daemon=True).start()
    return proc, ready, holder


def ensure(port: int = PORT, *, home: Path = HOME, reuse: bool = True,
           wait: float = 30.0) -> tuple[str | None, subprocess.Popen | None]:
    """Return a live public URL for ``port``, reusing a healthy persisted one.

    When ``reuse`` is on and the last captured URL is still healthy, it is
    returned with no new process (``proc is None`` -- the tunnel is owned
    elsewhere). Otherwise a fresh tunnel is opened; the returned process is the
    caller's to keep alive. Returns ``(None, None)`` if no URL appears within
    ``wait`` seconds or cloudflared is missing.
    """
    stable_url = configured_public_url()
    if stable_url and health_check(stable_url):
        write_state(stable_url, port, provider="cloudflare-named", home=home)
        return stable_url, None

    if reuse:
        prior = read_state(home)
        if prior and health_check(prior.get("url", "")):
            return prior["url"], None

    proc, ready, holder = start_tunnel(port, home=home)
    if proc is None:
        return None, None
    ready.wait(timeout=wait)
    url = holder.get("url")
    if not url:
        proc.terminate()
        return None, None
    return url, proc


def _cli(argv: list[str]) -> int:
    """Tiny entry used by ``scripts/preview.py``; kept here so the logic is one
    import away and the script stays a thin shim."""
    port = PORT
    reuse = "--no-reuse" not in argv
    once = "--once" in argv
    insecure = "--insecure" in argv
    for i, arg in enumerate(argv):
        if arg == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])

    # Safe-by-default: opening a fresh public tunnel with no token would create a
    # new unauthenticated exposure of her (and possibly this machine's files), so
    # refuse it unless the person explicitly accepts the risk with --insecure.
    # Reusing a tunnel that is already up creates no new exposure, so it proceeds
    # with a loud warning instead of a refusal.
    gated = link_is_gated()
    if not gated:
        print(_INSECURE_WARNING, file=sys.stderr)
    prior = read_state() if reuse else None
    reusing = bool(prior and health_check(prior.get("url", "")))
    if not gated and not reusing and not insecure:
        print("[preview] refusing to OPEN a new public tunnel without a token. "
              "Set ALPECCA_ACCESS_TOKEN (recommended) or pass --insecure to accept "
              "the risk.", file=sys.stderr)
        return 2

    url, proc = ensure(port, reuse=reuse)
    if not url:
        print("[preview] could not open a Cloudflare tunnel. Is cloudflared "
              "installed and the server running on port %d?" % port, file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("  CLOUDFLARE PREVIEW (open on any device -- works on mobile data):")
    print("   ", with_access_token(url.rstrip("/") + "/house-hq"))
    print("  Base app:")
    print("   ", with_access_token(url))
    print("  VRoid companion tool:")
    print("   ", with_access_token(url.rstrip("/") + "/vrm"))
    r2_record = config.HOME / "r2_preview.json"
    try:
        r2 = json.loads(r2_record.read_text(encoding="utf-8"))
        r2_house_hq = str(r2.get("houseHqUrl") or "").strip()
    except Exception:
        r2_house_hq = ""
    if r2_house_hq:
        live_shell_url = write_house_hq_live_url(r2_house_hq, url)
        print("  Static Cloudflare shell wired to this live backend:")
        print("   ", live_shell_url)
        print("  saved live shell URL to:", house_hq_live_url_path())
    print("  saved to:", url_path())
    print("=" * 60 + "\n")

    if proc is None or once:
        # Reusing a tunnel owned elsewhere, or asked only to capture: don't block.
        return 0

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        clear_state()
    return 0
