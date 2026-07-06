"""The Stage 4 conveyor: one command from returned tiles to live app assets.

Chains the existing, individually-runnable steps -- nothing new is invented
here, it just removes the hand-cranking between them:

  1. process_alpecca_stage4_returned_slice.py   (download + QA + import + stitch,
                                                 one frame index at a time)
  2. build_alpecca_animation_library.py         (compile atlases + refresh the
                                                 runtime manifest straight into
                                                 apps/house-hq/public/assets/)

Run it after any generation pass (nightly drip, Colab burst, ZeroGPU run):

    python scripts/run_alpecca_stage4_conveyor.py --outputs-root output/alpecca_stage4_tile_jobs/returned --apply

Without --apply every step runs in its audit/dry mode, so the default is a
safe "what would change" report. Idempotent: already-imported frames and
already-current atlases are skipped by the underlying steps' own gates.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
# The processor's own default (first-slice tile_job_manifest.json) is right
# for the proof slice; pass --manifest only to override for other targets.
DEFAULT_MANIFEST = None
DEFAULT_OUTPUTS_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "returned"


def run_step(label: str, command: list[str], dry_run: bool) -> dict:
    print(f"[conveyor] {label}: {' '.join(str(c) for c in command)}")
    if dry_run:
        return {"label": label, "skipped": "dry-run"}
    proc = subprocess.run(command, cwd=str(REPO_ROOT))
    return {"label": label, "returnCode": proc.returncode}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--outputs-root", type=Path, default=DEFAULT_OUTPUTS_ROOT)
    parser.add_argument("--frames", default="0-15",
                        help="Frame indexes to process, e.g. '0-15' or '3' or '0,4,8'.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually import/stitch/build; default is audit only.")
    parser.add_argument("--skip-build", action="store_true",
                        help="Stop after import/stitch; don't rebuild the runtime atlases.")
    args = parser.parse_args()

    frames: list[int] = []
    for part in str(args.frames).replace(" ", "").split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            frames.extend(range(int(lo), int(hi) + 1))
        elif part:
            frames.append(int(part))

    results = []
    for idx in frames:
        command = [
            sys.executable,
            str(SCRIPTS / "process_alpecca_stage4_returned_slice.py"),
            "--outputs-root", str(args.outputs_root),
            "--frame-index", str(idx),
        ]
        if args.manifest:
            command += ["--manifest", str(args.manifest)]
        if args.apply:
            command += ["--apply-import", "--apply-stitch"]
        results.append(run_step(f"frame {idx}", command, dry_run=False))

    if not args.skip_build:
        build = [sys.executable, str(SCRIPTS / "build_alpecca_animation_library.py")]
        # build already targets apps/house-hq/public/assets/alpecca-optimized;
        # audit mode when nothing was applied keeps this a pure report.
        results.append(run_step("animation library build", build,
                                dry_run=not args.apply))

    failed = [r for r in results if r.get("returnCode") not in (0, None)]
    summary = {
        "stage": "stage-4-conveyor",
        "applied": bool(args.apply),
        "frames": frames,
        "steps": results,
        "ok": not failed,
        "nextStep": ("None -- runtime assets are current; relaunch House HQ to see them."
                     if args.apply and not failed else
                     "Re-run with --apply to make these changes for real."),
    }
    out = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "conveyor_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[conveyor] {'OK' if summary['ok'] else 'FAILED STEPS PRESENT'} -> {out}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
