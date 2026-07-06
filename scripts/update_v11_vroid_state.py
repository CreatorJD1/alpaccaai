#!/usr/bin/env python

"""Update the VRoid v11 iteration state in ``vrm_experiment_manifest.json``.

Usage examples:
  python scripts/update_v11_vroid_state.py --state gui-resume-in-progress
  python scripts/update_v11_vroid_state.py --state base-gate-validating \
    --notes "Starting 16-angle hair pass; no edits applied yet."
  python scripts/update_v11_vroid_state.py --state base-gate-validated \
    --notes "Passed side/3/4 checks, ahoge single lock, clip on left." \
    --checkpoint-status "done"
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "alpecca_art_source" / "vrm_experiment_manifest.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Update v11 VRoid manifest checkpoints.")
    p.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help="Path to vrm_experiment_manifest.json",
    )
    p.add_argument(
        "--state",
        required=True,
        help="New v11Iteration.state value",
    )
    p.add_argument(
        "--notes",
        default=None,
        help="Status note to append to v11Iteration.notes",
    )
    p.add_argument(
        "--checkpoint-status",
        default=None,
        choices=["pending", "done", "needs-rework", "held"],
        help="Optional status for the v11 checkpoint entry",
    )
    p.add_argument(
        "--checkpoint-notes",
        default=None,
        help="Notes override for the v11 checkpoint entry",
    )
    p.add_argument(
        "--set-last-resume",
        action="store_true",
        help="Update lastResume to now (default: true when state is changed)",
    )
    return p.parse_args()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_manifest(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def sync_session_card(root: Path) -> None:
    card_script = root / "scripts" / "build_v11_session_card.py"
    if not card_script.exists():
        return
    try:
        subprocess.run(
            ["python", str(card_script)],
            cwd=str(root),
            check=False,
            capture_output=False,
        )
    except Exception:
        # Non-blocking: state updates should still succeed even if card generation fails.
        pass


def set_checkpoint(payload: dict, status: str | None, notes: str | None) -> None:
    if status is None and notes is None:
        return

    checkpoint = None
    for entry in payload.get("checkpoints", []):
        name = str(entry.get("name", "")).lower()
        if "v11" in name and "hair-gradient-ahoge" in name:
            checkpoint = entry
            break

    if checkpoint is None:
        return

    if status is not None:
        checkpoint["status"] = status

    if notes is not None:
        checkpoint["notes"] = notes


def main() -> int:
    args = parse_args()
    manifest_path: Path = args.manifest

    payload = load_manifest(manifest_path)
    v11 = payload.setdefault("v11Iteration", {})
    v11["state"] = args.state

    if args.set_last_resume or True:
        v11["lastResume"] = now_iso()

    if args.notes:
        previous = str(v11.get("notes", "")).strip()
        timestamp = now_iso()
        append_line = f"[{timestamp}] {args.notes}"
        v11["notes"] = f"{previous}\n{append_line}" if previous else append_line

    set_checkpoint(payload, args.checkpoint_status, args.checkpoint_notes)

    save_manifest(manifest_path, payload)
    sync_session_card(ROOT)
    print(f"Updated {manifest_path}")
    print(f"v11Iteration.state = {args.state}")
    if args.notes:
        print(f"Added note: {args.notes}")
    if args.checkpoint_status:
        print(f"Updated v11 checkpoint status = {args.checkpoint_status}")
    if args.checkpoint_notes:
        print("Updated v11 checkpoint notes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
