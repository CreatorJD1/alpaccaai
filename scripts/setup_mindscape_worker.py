"""Bind the Alpecca Mindscape Worker to a Cloudflare KV namespace.

This helper is intentionally narrow: it only updates deploy/mindscape-worker's
MINDSCAPE_KV binding after the owner creates a KV namespace with Wrangler.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpecca import mindscape


def _clipboard_text() -> str:
    if sys.platform != "win32":
        return ""
    try:
        return subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind the Mindscape Worker KV namespace id.")
    parser.add_argument("--worker-dir", default=str(ROOT / "deploy" / "mindscape-worker"))
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--kv-id", help="KV namespace id, or pasted Wrangler output containing it.")
    source.add_argument("--from-file", help="Read pasted Wrangler output from a file.")
    source.add_argument("--from-clipboard", action="store_true", help="Read pasted Wrangler output from the clipboard.")
    parser.add_argument("--print-next", action="store_true", help="Print the next setup commands after patching.")
    args = parser.parse_args()

    text = args.kv_id or ""
    if args.from_file:
        text = Path(args.from_file).read_text(encoding="utf-8")
    if args.from_clipboard:
        text = _clipboard_text()
    namespace_id = mindscape.extract_kv_namespace_id(text)
    if not namespace_id:
        print("Could not find a valid KV namespace id.", file=sys.stderr)
        print("Run: npx wrangler kv namespace create MINDSCAPE_KV --json", file=sys.stderr)
        print("Then pass the returned id with --kv-id, --from-file, or --from-clipboard.", file=sys.stderr)
        return 2

    wrangler = Path(args.worker_dir) / "wrangler.toml"
    result = mindscape.bind_worker_kv_namespace(wrangler, namespace_id)
    if not result["ok"]:
        print(f"Mindscape Worker KV bind failed: {result['status']} ({result['path']})", file=sys.stderr)
        return 1

    print(f"Mindscape Worker KV bound: {namespace_id}")
    if args.print_next:
        print("")
        print("Next:")
        print("  npx wrangler secret put MINDSCAPE_TOKEN")
        print("  npx wrangler deploy")
        print("  $env:ALPECCA_MINDSCAPE_URL=\"https://alpecca-mindscape.<your-subdomain>.workers.dev/sync\"")
        print("  $env:ALPECCA_MINDSCAPE_TOKEN=\"same-secret-as-cloudflare\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
