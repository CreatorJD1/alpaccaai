"""Recover the latest encrypted Mindscape Vault SQLite archive into a new file.

This does not replace Alpecca's live database. Stop the live stack, inspect the
verified recovered file, then make any promotion decision deliberately.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from alpecca import mindscape_vault
from config import HOME, MINDSCAPE_VAULT_URL


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover Alpecca's latest encrypted Mindscape Vault archive.")
    parser.add_argument("--destination", default="", help="New SQLite path; defaults below data/recovery.")
    args = parser.parse_args()
    if not MINDSCAPE_VAULT_URL:
        print("Mindscape Vault URL is not configured.")
        return 2
    if args.destination:
        destination = Path(args.destination)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = HOME / "recovery" / f"alpecca-mindscape-vault-{stamp}.sqlite3"
    try:
        recovery_key, _source = mindscape_vault.load_or_create_encryption_key()
        transport_token, _token_source = mindscape_vault.load_or_create_transport_token()
    except mindscape_vault.VaultError as exc:
        print(f"Could not load Vault recovery credentials: {type(exc).__name__}")
        return 2
    result = mindscape_vault.fetch_latest_archive(
        MINDSCAPE_VAULT_URL,
        transport_token,
        recovery_key,
        destination,
    )
    if not result.get("ok"):
        print(f"Vault recovery failed: {result.get('status', 'unknown')}")
        return 1
    print(f"Recovered verified SQLite archive: {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
