"""Milestone 1 deliverable: the background sense.

Run this in the background and it quietly captures what window has focus on a
fixed interval, timestamps it, and appends a line to telemetry.jsonl. That log
is both Alpacca's raw memory of your day and the input that keeps its mood in
touch with reality.

Usage:
    python scripts/run_telemetry.py            # poll every 5s
    python scripts/run_telemetry.py --interval 10

On Windows this reads real window titles via pywin32. On other systems it still
runs (writing empty observations) so you can develop the pipeline anywhere.

Stop it with Ctrl+C.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Make the project root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TELEMETRY_LOG
from alpacca.sensory import WindowSensor


def main() -> None:
    ap = argparse.ArgumentParser(description="Alpacca background telemetry logger")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="seconds between samples (default 5)")
    args = ap.parse_args()

    sensor = WindowSensor()
    mode = "Windows window titles" if sensor.available else "stub (no pywin32 / non-Windows)"
    print(f"Alpacca telemetry running -- mode: {mode}")
    print(f"Writing to: {TELEMETRY_LOG}")
    print("Ctrl+C to stop.\n")

    try:
        while True:
            obs = sensor.observe()
            record = {
                "ts": obs.timestamp,
                "title": obs.window_title,
                "app": obs.app,
                "idle_seconds": round(obs.idle_seconds, 1),
                "error_context": obs.is_error_context(),
            }
            with open(TELEMETRY_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  {time.strftime('%H:%M:%S')}  {obs.window_title[:60]!r}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped. Your telemetry is saved.")


if __name__ == "__main__":
    main()
