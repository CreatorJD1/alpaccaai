"""One-time Google Workspace OAuth enrollment for Alpecca on Windows.

The browser receives Google's authorization page. The refresh token and app
secret are stored only in Windows Credential Manager; this script never prints
them and does not create a plaintext token file.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpecca import google_workspace


SCOPES = (
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
)


def _desktop_credentials(path: Path) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        installed = payload["installed"]
        client_id = str(installed["client_id"]).strip()
        client_secret = str(installed["client_secret"]).strip()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("The selected file is not a valid Google OAuth desktop client JSON.") from exc
    if not client_id or not client_secret:
        raise SystemExit("The Google OAuth desktop client JSON is incomplete.")
    return client_id, client_secret


class _Callback(BaseHTTPRequestHandler):
    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        query = parse_qs(urlparse(self.path).query)
        type(self).result = {key: values[0] for key, values in query.items() if values}
        body = b"Alpecca's private Google Workspace connection was received. You may close this tab."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _open_edge(url: str) -> None:
    candidates = (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    )
    edge = next((path for path in candidates if path.exists()), None)
    if edge is None:
        raise SystemExit("Microsoft Edge is not installed in a standard location.")
    subprocess.Popen([str(edge), url], close_fds=True)


def _exchange_code(*, client_id: str, client_secret: str, code: str,
                   verifier: str, redirect_uri: str) -> dict:
    body = urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }).encode("ascii")
    return google_workspace._json_request(  # enrollment owns this bounded exchange
        "POST",
        google_workspace.TOKEN_URL,
        body,
        {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        20.0,
    )


def _create_private_root(access_token: str, name: str) -> str:
    body = json.dumps({
        "name": " ".join(name.split())[:140] or "Alpecca Assistance",
        "mimeType": google_workspace.GOOGLE_FOLDER_MIME,
    }).encode("utf-8")
    row = google_workspace._json_request(
        "POST",
        f"{google_workspace.DRIVE_API}/files?fields=id",
        body,
        {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Accept": "application/json"},
        20.0,
    )
    root_id = str(row.get("id") or "").strip()
    if not google_workspace._SAFE_ID.fullmatch(root_id):
        raise google_workspace.GoogleWorkspaceError("Google did not return a valid private root receipt")
    return root_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect Alpecca to one private Google Workspace folder.")
    parser.add_argument("client_json", type=Path, help="Google OAuth desktop client JSON downloaded from Google Cloud.")
    parser.add_argument("--folder-name", default="Alpecca Assistance")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    client_id, client_secret = _desktop_credentials(args.client_json)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    state = secrets.token_urlsafe(24)
    server = HTTPServer(("127.0.0.1", 0), _Callback)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/oauth/callback"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    _Callback.result = {}
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    _open_edge(url)
    thread.join(timeout=max(30.0, min(600.0, args.timeout)))
    server.server_close()
    result = _Callback.result
    if result.get("state") != state or not result.get("code"):
        raise SystemExit("Google authorization was not completed or the callback was invalid.")
    tokens = _exchange_code(
        client_id=client_id,
        client_secret=client_secret,
        code=result["code"],
        verifier=verifier,
        redirect_uri=redirect_uri,
    )
    access_token = str(tokens.get("access_token") or "").strip()
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not access_token or not refresh_token:
        raise SystemExit("Google did not issue the required offline authorization.")
    root_id = _create_private_root(access_token, args.folder_name)
    google_workspace.store_oauth_config(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        root_id=root_id,
    )
    print("Alpecca's private Google Workspace connection is ready in Windows Credential Manager.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
