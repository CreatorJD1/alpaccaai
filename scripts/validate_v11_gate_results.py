#!/usr/bin/env python
"""Validate ALPECCA_V11_GATE_RESULTS.md and suggest the next manifest transition."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_FILE = ROOT / "docs" / "ALPECCA_V11_GATE_RESULTS.md"

VALID_STATUSES = {"PASS", "REWORK", "N/A", "NA"}
PASS_LIKE = {"PASS", "N/A", "NA"}


def normalize_status(raw: str) -> str:
    value = re.sub(r"\s+", "", raw).upper()
    value = value.replace("／", "/").replace("＄", "$")
    if not value:
        return ""
    if value in {"PASS", "PASS."}:
        return "PASS"
    if value in {"REWORK", "REWORK.", "RE-REWORK", "RETRY"}:
        return "REWORK"
    if value in {"NA", "N/A", "N.A.", "N/A", "N-1"}:
        return "N/A"
    return value


def parse_gate_markers(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        parts = [c.strip() for c in stripped.split("|")]
        if not parts:
            continue
        if parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]

        if len(parts) < 3:
            continue
        if all(set(p.replace(" ", "")) <= {"-", ":"} for p in parts):
            continue

        lc = [p.lower() for p in parts]
        if any(p in {"group", "check", "status", "notes"} for p in lc):
            continue

        if len(parts) == 4:
            check_cell = parts[1]
            status_cell = parts[2]
        elif len(parts) == 3:
            check_cell = parts[0]
            status_cell = parts[1]
        else:
            # Fallback: last table cell before notes.
            check_cell = parts[-3]
            status_cell = parts[-2]
            if check_cell.lower() in {"status", "check", "notes"}:
                continue

        rows.append((check_cell, normalize_status(status_cell)))
    return rows


def main() -> int:
    if not GATE_FILE.exists():
        print(f"Missing gate file: {GATE_FILE}")
        return 1

    rows = parse_gate_markers(GATE_FILE.read_text(encoding="utf-8"))
    total_checks = len(rows)
    completed = 0
    rework_count = 0
    invalid = 0

    for check_name, status in rows:
        if status == "":
            print(f"[INCOMPLETE] {check_name}: (blank)")
        elif status == "REWORK":
            rework_count += 1
            print(f"[REWORK]   {check_name}: {status}")
        elif status in PASS_LIKE:
            completed += 1
            print(f"[PASS]     {check_name}: {status}")
        else:
            invalid += 1
            print(f"[INVALID]  {check_name}: {status}")

    print("\nSummary:")
    print(f"  Total checks parsed: {total_checks}")
    print(f"  Completed:          {completed}")
    print(f"  Rework:             {rework_count}")
    print(f"  Invalid values:     {invalid}")

    if rework_count > 0:
        print("Status: FAILED (one or more REWORK entries).")
        print(
            'Next command: python scripts/update_v11_vroid_state.py --state base-gate-rework --notes "v11 qa check failed"'
        )
        return 1

    if completed < total_checks or invalid > 0:
        print("Status: INCOMPLETE (all checks must be PASS, REWORK, or N/A; blank is not allowed).")
        return 1

    print("Status: PASSABLE")
    print(
        'Next command: python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "v11 gates passed"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
