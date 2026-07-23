"""Bounded Google Workspace access for Alpecca's private assistance folder.

The adapter intentionally supports only status, new folders, and new Google
Docs. It cannot share, overwrite, move, or delete Drive data. OAuth material is
loaded from one dedicated Windows Credential Manager record (or explicit
deployment variables) and is never returned by status or receipts.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DRIVE_API = "https://www.googleapis.com/drive/v3"
DOCS_API = "https://docs.googleapis.com/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
CREDENTIAL_TARGET = "Alpecca/GoogleWorkspaceOAuth"
_TRUE = frozenset({"1", "true", "yes", "on"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,180}$")


class GoogleWorkspaceError(RuntimeError):
    """A bounded, user-safe Google Workspace failure."""


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    source: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get("ALPECCA_GOOGLE_WORKSPACE", "1")).strip().lower() in _TRUE


def _decode_blob(blob: object) -> str:
    if isinstance(blob, str):
        return blob
    if isinstance(blob, bytes):
        for encoding in ("utf-16-le", "utf-8"):
            try:
                return blob.decode(encoding).rstrip("\x00")
            except UnicodeDecodeError:
                continue
    raise GoogleWorkspaceError("the Google Workspace credential is invalid")


def _credential_payload() -> dict[str, Any] | None:
    if os.name != "nt":
        return None
    try:
        import win32cred
    except ImportError:
        return None
    try:
        row = win32cred.CredRead(CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception as exc:
        code = getattr(exc, "winerror", None)
        if code in {2, 1168} or (getattr(exc, "args", ()) and exc.args[0] in {2, 1168}):
            return None
        raise GoogleWorkspaceError("could not read the Google Workspace credential") from exc
    try:
        value = json.loads(_decode_blob(row.get("CredentialBlob")))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GoogleWorkspaceError("the Google Workspace credential is invalid") from exc
    return value if isinstance(value, dict) else None


def store_oauth_config(*, client_id: str, client_secret: str,
                       refresh_token: str, root_id: str) -> None:
    """Store one validated OAuth bundle without printing or writing a file."""
    fields = {
        "client_id": str(client_id or "").strip(),
        "client_secret": str(client_secret or "").strip(),
        "refresh_token": str(refresh_token or "").strip(),
        "root_folder_id": str(root_id or "").strip(),
    }
    if not all(fields.values()) or not _SAFE_ID.fullmatch(fields["root_folder_id"]):
        raise GoogleWorkspaceError("Google Workspace configuration is incomplete")
    if os.name != "nt":
        raise GoogleWorkspaceError("secure Google Workspace setup currently requires Windows")
    try:
        import win32cred
        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": CREDENTIAL_TARGET,
            "UserName": "Alpecca",
            "CredentialBlob": json.dumps(fields, separators=(",", ":")),
            "Comment": "Alpecca private Google Workspace OAuth",
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }, 0)
    except Exception as exc:
        raise GoogleWorkspaceError("could not store Google Workspace authorization") from exc


def oauth_config(environ: Mapping[str, str] | None = None) -> OAuthConfig:
    env = os.environ if environ is None else environ
    direct = {
        "client_id": str(env.get("ALPECCA_GOOGLE_CLIENT_ID", "")).strip(),
        "client_secret": str(env.get("ALPECCA_GOOGLE_CLIENT_SECRET", "")).strip(),
        "refresh_token": str(env.get("ALPECCA_GOOGLE_REFRESH_TOKEN", "")).strip(),
    }
    if all(direct.values()):
        return OAuthConfig(**direct, source="deployment")
    stored = _credential_payload() or {}
    return OAuthConfig(
        client_id=str(stored.get("client_id") or "").strip(),
        client_secret=str(stored.get("client_secret") or "").strip(),
        refresh_token=str(stored.get("refresh_token") or "").strip(),
        source="windows-credential-manager" if stored else "not-configured",
    )


def root_folder_id(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    value = str(env.get("ALPECCA_GOOGLE_ROOT_ID", "")).strip()
    if not value:
        try:
            value = str((_credential_payload() or {}).get("root_folder_id") or "").strip()
        except GoogleWorkspaceError:
            value = ""
    return value if _SAFE_ID.fullmatch(value) else ""


def status(*, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    try:
        auth = oauth_config(env)
        credential_state = "ready" if auth.configured else "missing"
        credential_source = auth.source
    except GoogleWorkspaceError:
        credential_state = "invalid"
        credential_source = "windows-credential-manager"
    active = enabled(env)
    root_ready = bool(root_folder_id(env))
    ready = active and credential_state == "ready" and root_ready
    return {
        "schema": "alpecca.google_workspace.status.v1",
        "enabled": active,
        "configured": credential_state == "ready",
        "root_configured": root_ready,
        "ready": ready,
        "state": "ready" if ready else (
            "disabled" if not active else
            "credential-missing" if credential_state == "missing" else
            "credential-invalid" if credential_state == "invalid" else
            "root-missing"
        ),
        "credential_source": credential_source,
        "capabilities": ["status", "create_private_folder", "create_private_document"],
        "destructive_actions": False,
        "sharing_actions": False,
    }


Transport = Callable[[str, str, bytes | None, Mapping[str, str], float], dict[str, Any]]


def _json_request(method: str, url: str, body: bytes | None,
                  headers: Mapping[str, str], timeout: float) -> dict[str, Any]:
    request = Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(1_000_000)
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read(32_000).decode("utf-8", errors="replace"))
            message = str(detail.get("error", {}).get("message") or "")
        except Exception:
            message = ""
        raise GoogleWorkspaceError(
            f"Google Workspace request failed ({exc.code})" + (f": {message[:240]}" if message else "")
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise GoogleWorkspaceError("Google Workspace is currently unreachable") from exc
    try:
        value = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoogleWorkspaceError("Google Workspace returned an invalid response") from exc
    if not isinstance(value, dict):
        raise GoogleWorkspaceError("Google Workspace returned an invalid response")
    return value


class GoogleWorkspaceClient:
    def __init__(self, *, environ: Mapping[str, str] | None = None,
                 transport: Transport | None = None,
                 token_provider: Callable[[], str] | None = None) -> None:
        self.environ = os.environ if environ is None else environ
        self.transport = transport or _json_request
        self.token_provider = token_provider
        self.timeout = max(3.0, min(30.0, float(self.environ.get("ALPECCA_GOOGLE_TIMEOUT", "12"))))
        self._token = ""
        self._token_deadline = 0.0

    def _access_token(self) -> str:
        if self.token_provider is not None:
            token = str(self.token_provider() or "").strip()
            if not token:
                raise GoogleWorkspaceError("Google Workspace authorization is unavailable")
            return token
        now = time.monotonic()
        if self._token and now < self._token_deadline:
            return self._token
        auth = oauth_config(self.environ)
        if not auth.configured:
            raise GoogleWorkspaceError("Google Workspace authorization is not configured")
        body = urlencode({
            "client_id": auth.client_id,
            "client_secret": auth.client_secret,
            "refresh_token": auth.refresh_token,
            "grant_type": "refresh_token",
        }).encode("ascii")
        response = self.transport(
            "POST", TOKEN_URL, body,
            {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            self.timeout,
        )
        token = str(response.get("access_token") or "").strip()
        if not token:
            raise GoogleWorkspaceError("Google Workspace authorization refresh failed")
        try:
            expires = max(60, min(3600, int(response.get("expires_in", 3600))))
        except (TypeError, ValueError):
            expires = 3600
        self._token = token
        self._token_deadline = now + max(30, expires - 90)
        return token

    def _api(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not enabled(self.environ):
            raise GoogleWorkspaceError("Google Workspace access is disabled")
        if not root_folder_id(self.environ):
            raise GoogleWorkspaceError("Alpecca's private Google Drive root is not configured")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        return self.transport(
            method, url, body,
            {"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json", "Accept": "application/json"},
            self.timeout,
        )

    @staticmethod
    def _name(value: object, *, label: str) -> str:
        clean = " ".join(str(value or "").split()).strip()
        if not clean:
            raise GoogleWorkspaceError(f"{label} is required")
        if len(clean) > 140:
            raise GoogleWorkspaceError(f"{label} is too long")
        return clean

    @staticmethod
    def _receipt(row: Mapping[str, Any], *, kind: str, name: str) -> dict[str, Any]:
        file_id = str(row.get("id") or "").strip()
        if not _SAFE_ID.fullmatch(file_id):
            raise GoogleWorkspaceError("Google Workspace did not return a valid file receipt")
        return {
            "ok": True,
            "kind": kind,
            "name": name,
            "file_id": file_id,
            "web_view_link": str(row.get("webViewLink") or f"https://drive.google.com/open?id={file_id}"),
            "verified_receipt": True,
        }

    def create_folder(self, name: object) -> dict[str, Any]:
        clean = self._name(name, label="folder name")
        row = self._api(
            "POST",
            f"{DRIVE_API}/files?fields=id,name,mimeType,webViewLink",
            {"name": clean, "mimeType": GOOGLE_FOLDER_MIME, "parents": [root_folder_id(self.environ)]},
        )
        return self._receipt(row, kind="folder", name=clean)

    def create_document(self, title: object, content: object = "") -> dict[str, Any]:
        clean_title = self._name(title, label="document title")
        clean_content = str(content or "").replace("\x00", "").strip()
        if len(clean_content) > 100_000:
            raise GoogleWorkspaceError("document content is too long")
        row = self._api(
            "POST",
            f"{DRIVE_API}/files?fields=id,name,mimeType,webViewLink",
            {"name": clean_title, "mimeType": GOOGLE_DOC_MIME, "parents": [root_folder_id(self.environ)]},
        )
        receipt = self._receipt(row, kind="document", name=clean_title)
        if clean_content:
            self._api(
                "POST",
                f"{DOCS_API}/documents/{receipt['file_id']}:batchUpdate",
                {"requests": [{"insertText": {"location": {"index": 1}, "text": clean_content}}]},
            )
        receipt["content_inserted"] = bool(clean_content)
        return receipt


def create_folder(name: object, *, client: GoogleWorkspaceClient | None = None) -> dict[str, Any]:
    return (client or GoogleWorkspaceClient()).create_folder(name)


def create_document(title: object, content: object = "", *,
                    client: GoogleWorkspaceClient | None = None) -> dict[str, Any]:
    return (client or GoogleWorkspaceClient()).create_document(title, content)
