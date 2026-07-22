"""Publish the current validated Alpecca endpoint to the stable R2 record."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpecca.mobile_endpoint import build_endpoint_document, probe_alpecca_endpoint  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUCKET = "alpeccaai"
DEFAULT_KEY = "mobile/alpecca-endpoint.json"


def wait_for_endpoint(
    url: str,
    *,
    attempts: int = 10,
    delay_seconds: float = 2.0,
    probe: Callable[[str], bool] = probe_alpecca_endpoint,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """Wait briefly for a newly issued tunnel hostname to reach the backend."""
    bounded_attempts = max(1, min(10, int(attempts)))
    bounded_delay = max(0.0, min(5.0, float(delay_seconds)))
    for attempt in range(bounded_attempts):
        if probe(url):
            return True
        if attempt + 1 < bounded_attempts and bounded_delay:
            sleeper(bounded_delay)
    return False


def _wrangler() -> list[str] | None:
    direct = shutil.which("wrangler")
    if direct:
        return [direct]
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    return [npx, "--yes", "wrangler"] if npx else None


def publish(url: str, *, kind: str, bucket: str, key: str, skip_probe: bool = False) -> Path:
    if not skip_probe and not wait_for_endpoint(url):
        raise RuntimeError("endpoint did not return Alpecca's exact /healthz identity")
    document = build_endpoint_document([(url, kind, 0 if kind == "named" else 10)])
    if not document["endpoints"]:
        raise ValueError("a valid HTTPS Alpecca endpoint is required")
    output = ROOT / "data" / "mobile_endpoint.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    wrangler = _wrangler()
    if not wrangler:
        raise RuntimeError("Wrangler was not found")
    subprocess.run(
        [
            *wrangler,
            "r2", "object", "put", f"{bucket}/{key}",
            "--file", str(output),
            "--content-type", "application/json; charset=utf-8",
            "--remote",
        ],
        cwd=ROOT,
        check=True,
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--kind", choices=("named", "quick"), default="quick")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--key", default=DEFAULT_KEY)
    parser.add_argument("--skip-probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    path = publish(args.url, kind=args.kind, bucket=args.bucket, key=args.key, skip_probe=args.skip_probe)
    print(f"Published mobile discovery record from {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
