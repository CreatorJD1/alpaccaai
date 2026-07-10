"""Print a fresh one-use loopback bootstrap URL from the running Alpecca server.

This is the sanctioned path for local dev tooling (for example an automated
browser used for UI verification on this machine) to obtain an authorized
browser session without weakening the authorization boundary:

* It holds exactly the same trust as the launcher (``scripts/run_full.py``)
  and the Discord bridge: it reads the protected server authorization secret
  via ``alpecca.auth.load_or_create_authorization_secret`` (environment
  override or Windows Credential Manager -- never a plaintext file), and
* it exercises the EXISTING authorized, loopback-only server route
  ``POST /auth/bootstrap/request`` (server.py), which mints the same
  short-lived (60 s), strictly one-use bootstrap code that the launcher hands
  to the OS browser at startup.

Nothing new is exposed: that route already requires BOTH the protected
``X-Alpecca-Authorization`` header (it is not in the server's public-path
allowlist) AND a loopback peer address. The printed URL is consumed exactly
once by ``GET /auth/bootstrap`` -> ``POST /auth/bootstrap/exchange``, which
sets the HttpOnly, SameSite=Strict session cookie and redirects to ``next``.

Usage:
    python scripts/dev_bootstrap_url.py [next_path]

Prints ONLY the bootstrap URL on stdout (never the secret). Navigate the
automated browser to it within 60 seconds; after the auto-submitting exchange
and redirect the browser holds an authorized session and lands on
``next_path`` (default "/", e.g. pass "/house-hq" for the 3D house).

Non-browser flows (curl with a cookie jar) can skip the landing page and POST
the same ``code``/``next`` query directly to ``/auth/bootstrap/exchange``.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import HOME, PORT                     # noqa: E402
from alpecca import auth as auth_mod              # noqa: E402

_REQUEST_TIMEOUT_S = 5.0


def _fail(message: str) -> "None":
    print(f"dev_bootstrap_url: {message}", file=sys.stderr)
    raise SystemExit(1)


def _with_next_path(url: str, next_path: str) -> str:
    """Rewrite only the post-login ``next`` redirect path of the minted URL.

    The ``next`` value is not part of the one-use grant; the server re-checks
    it against ``_safe_local_path`` on every request, so pointing the redirect
    at a different local page keeps the exact same security properties.
    """
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query["next"] = next_path
    return urllib.parse.urlunsplit(
        parts._replace(query=urllib.parse.urlencode(query))
    )


def main(argv: list[str]) -> None:
    next_path = argv[1] if len(argv) > 1 else "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        _fail(f"next_path must be a local absolute path, got: {next_path!r}")

    # Same protected provider the server and Discord bridge use; the value is
    # deliberately never written to disk, logged, or printed by this script.
    secret = auth_mod.load_or_create_authorization_secret(HOME)

    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/auth/bootstrap/request",
        method="POST",
        headers={auth_mod.AUTHORIZATION_HEADER: secret},
    )
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        _fail(
            f"server refused the bootstrap request (HTTP {exc.code}); "
            "is this shell using the same secret provider as the server?"
        )
    except (urllib.error.URLError, OSError) as exc:
        _fail(
            f"could not reach the local server on 127.0.0.1:{PORT} "
            f"({exc}); start it first (scripts/run_full.py or server.py)."
        )

    url = payload.get("url") if isinstance(payload, dict) else None
    if not isinstance(url, str) or not url.strip():
        _fail("server response did not include a bootstrap url")

    if next_path != "/":
        url = _with_next_path(url, next_path)
    print(url)


if __name__ == "__main__":
    main(sys.argv)
