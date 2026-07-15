"""Create or update Alpecca's separate encrypted Mindscape Vault Worker.

This is intentionally a creator-run deployment helper, not a runtime task. It
creates an R2 bucket, gives the Worker the locally stored Vault transport token
without printing it, deploys the Worker, and persists only its non-secret URL
under ignored ``data/secrets`` for future local launches.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpecca import mindscape_vault
from config import HOME


WORKER_DIR = ROOT / "deploy" / "mindscape-vault-worker"
BUCKET = "alpecca-mindscape-vault"
WORKER_NAME = "alpecca-mindscape-vault"
_WORKER_URL = re.compile(r"https://[a-z0-9][a-z0-9-]*\.workers\.dev", re.IGNORECASE)
_ACCOUNT_ID = re.compile(r"\b[a-f0-9]{32}\b", re.IGNORECASE)


def _wrangler() -> str:
    return shutil.which("npx.cmd") or shutil.which("npx") or "npx.cmd"


def _run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_wrangler(), "wrangler", *args],
        cwd=WORKER_DIR,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _show_failure(label: str, result: subprocess.CompletedProcess[str]) -> int:
    print(f"{label} failed.", file=sys.stderr)
    if result.stdout:
        print(result.stdout.strip(), file=sys.stderr)
    return result.returncode or 1


def _save_endpoint(url: str) -> Path:
    path = HOME / "secrets" / "mindscape_vault.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.tmp")
    staging.write_text(f"ALPECCA_MINDSCAPE_VAULT_URL={url.rstrip('/')}\n", encoding="utf-8")
    staging.replace(path)
    return path


def _wrangler_oauth_token() -> str:
    """Read Wrangler's already-authenticated session without displaying it."""
    configured = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if configured:
        return configured
    config = Path(os.environ.get("APPDATA", "")) / "xdg.config" / ".wrangler" / "config" / "default.toml"
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("oauth_token") or "").strip()


def _cloudflare_json(account_id: str, suffix: str, token: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}{suffix}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("success"):
        raise ValueError("Cloudflare API did not confirm the Worker endpoint")
    return payload


def _discover_worker_url(auth_output: str) -> str:
    """Resolve workers.dev when Wrangler's deploy output omits the URL."""
    token = _wrangler_oauth_token()
    match = _ACCOUNT_ID.search(auth_output or "")
    if not token or not match:
        return ""
    try:
        account_id = match.group(0)
        subdomain = _cloudflare_json(account_id, "/workers/subdomain", token)["result"]["subdomain"]
        script = _cloudflare_json(
            account_id,
            f"/workers/scripts/{WORKER_NAME}/subdomain",
            token,
        )["result"]
        if not script.get("enabled"):
            _cloudflare_json(
                account_id,
                f"/workers/scripts/{WORKER_NAME}/subdomain",
                token,
                method="POST",
                body={"enabled": True, "previews_enabled": True},
            )
        if not isinstance(subdomain, str) or not subdomain:
            return ""
    except (KeyError, OSError, ValueError, urllib.error.URLError):
        return ""
    return f"https://{WORKER_NAME}.{subdomain}.workers.dev"


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy Alpecca's encrypted Mindscape Vault Worker.")
    parser.add_argument("--url", default="", help="Deployed Worker URL when Wrangler output is not workers.dev.")
    parser.add_argument("--skip-bucket", action="store_true", help="Use an existing R2 bucket without creating it.")
    args = parser.parse_args()

    auth = _run(["whoami"])
    if auth.returncode:
        return _show_failure("Cloudflare authentication check", auth)

    try:
        transport_token, _source = mindscape_vault.load_or_create_transport_token()
    except mindscape_vault.VaultError as exc:
        print(f"Could not load the Vault transport token: {type(exc).__name__}", file=sys.stderr)
        return 2

    if not args.skip_bucket:
        bucket = _run(["r2", "bucket", "create", BUCKET])
        if bucket.returncode and "already exists" not in (bucket.stdout or "").lower():
            return _show_failure("R2 bucket creation", bucket)

    # Pass the token through the child process's stdin. It is never included in
    # arguments, files, output, Git, or a browser-visible route.
    secret = _run(["secret", "put", "MINDSCAPE_VAULT_TOKEN"], input_text=f"{transport_token}\n")
    if secret.returncode:
        return _show_failure("Vault Worker secret update", secret)

    deploy = _run(["deploy"])
    if deploy.returncode:
        return _show_failure("Vault Worker deployment", deploy)
    url = args.url.strip().rstrip("/")
    if not url:
        match = _WORKER_URL.search(deploy.stdout or "")
        url = match.group(0).rstrip("/") if match else ""
    if not url:
        url = _discover_worker_url(auth.stdout or "")
    if not url.startswith("https://"):
        print("Worker deployed, but its URL was not found. Re-run with --url https://<worker>.workers.dev", file=sys.stderr)
        return 3

    endpoint_file = _save_endpoint(url)
    print(f"Mindscape Vault is deployed at {url}")
    print(f"Saved its local endpoint to {endpoint_file}")
    print("Restart Alpecca, then use /mindscape/vault/status to confirm encrypted sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
