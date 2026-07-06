#!/usr/bin/env python
"""Generate a one-page operator session card for the current v11 VRoid pass."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "alpecca_art_source" / "vrm_experiment_manifest.json"
GATE_FILE = ROOT / "docs" / "ALPECCA_V11_GATE_RESULTS.md"
OUT_FILE = ROOT / "docs" / "ALPECCA_V11_SESSION_CARD.md"
USER_ADJUSTED_V12 = (
    ROOT
    / "data"
    / "alpecca_art_source"
    / "vrm_experiments"
    / "alpecca_vroid_proxy_v12_user_adjusted_from_v0.vroid"
)
BRANCH_DECISION = ROOT / "docs" / "ALPECCA_VROID_BRANCH_DECISION.md"


def safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def parse_gate_status(text: str) -> tuple[int, int, int, int]:
    """Return (total, incomplete, rework, invalid)."""
    total = incomplete = rework = invalid = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if "|" not in line[1:]:
            continue
        parts = [p.strip() for p in line.split("|")]
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]
        if len(parts) < 3:
            continue
        lowered = [p.lower() for p in parts]
        if any(p in {"group", "check", "status", "notes"} for p in lowered):
            continue
        if all(set(p.replace(" ", "")) <= {"-", ":"} for p in parts):
            continue

        if len(parts) == 4:
            status = parts[2].strip().upper()
        elif len(parts) == 3:
            status = parts[1].strip().upper()
        else:
            status = parts[-2].strip().upper()

        if status in {"", "(blank)"}:
            incomplete += 1
            total += 1
            continue

        if status == "REWORK":
            rework += 1
        elif status in {"PASS", "N/A", "NA"}:
            pass
        else:
            invalid += 1
        total += 1

    return total, incomplete, rework, invalid


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    v11 = manifest.get("v11Iteration", {})
    current_probe = manifest.get("currentProbe", {})
    export_gate = manifest.get("exportGate", {})

    gate_text = safe_read(GATE_FILE)
    total, incomplete, rework, invalid = parse_gate_status(gate_text)

    session = []
    session.append("# Alpecca VRoid v11 Session Card")
    session.append("")
    session.append(f"Generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S%z')}")
    session.append("")
    session.append("## Current State")
    session.append(f"- state: {v11.get('state', 'unknown')}")
    session.append(f"- checkpoint: {current_probe.get('savedProjectPath', 'unknown')}")
    session.append(f"- focus: {manifest.get('currentFocus', 'v11 base-model experiment')}")
    session.append(f"- target height: {manifest.get('targetDesign', {}).get('heightCm', '170.4')} cm")
    session.append("- status: **experimental only** (does not replace runtime systems)")
    session.append("")

    if USER_ADJUSTED_V12.exists():
        session.append("## Branch Caution")
        session.append("- Live VRoid was last observed open to `alpecca_vroid_proxy_v0.vroid`, not the v11 checkpoint.")
        session.append("- That open v0 file has been preserved as:")
        session.append("  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v12_user_adjusted_from_v0.vroid`")
        if BRANCH_DECISION.exists():
            session.append("- Branch decision: continue v11 as the main rework path; keep v12 as a preserved fallback/reference.")
            session.append("- Decision doc: `docs/ALPECCA_VROID_BRANCH_DECISION.md`")
        else:
            session.append("- Choose deliberately before further edits: continue v11 as the main rework path, or promote v12 as a new user-adjusted base.")
        session.append("- Do not validate v11 gates from v0/v12 screenshots.")
        session.append("")

    blockers = export_gate.get("doNotExportUntil", [])
    if blockers:
        session.append("## Design Gates Still Open")
        for item in blockers:
            session.append(f"- {item}")
        session.append("")

    session.append("## Gate Results Quick Check")
    session.append(f"- rows parsed: {total}")
    session.append(f"- incomplete: {incomplete}")
    session.append(f"- rework: {rework}")
    session.append(f"- invalid: {invalid}")
    gate_ok = total > 0 and incomplete == 0 and rework == 0 and invalid == 0
    session.append(f"- passable: {'YES' if gate_ok else 'NO'}")
    session.append("")

    session.append("## Next Required Actions")
    if gate_ok:
        session.append("1. `python scripts/update_v11_vroid_state.py --state base-gate-validated --notes \"v11 gates passed\"`")
        session.append("2. Export plan can move to outfit/asset detail pass.")
    else:
        session.append("1. Open `docs/ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md` and validate all 15-angle checks + mirror checks.")
        session.append("2. Fill `docs/ALPECCA_V11_GATE_RESULTS.md` with PASS/REWORK and one-line notes.")
        session.append("3. Re-run: `python scripts/validate_v11_gate_results.py`")
        session.append("4. If any check is REWORK: `python scripts/update_v11_vroid_state.py --state base-gate-rework --notes \"...\"`")
        session.append("5. If all check out: `python scripts/update_v11_vroid_state.py --state base-gate-validated --notes \"v11 gates passed\"`")
    session.append("")

    session.append("## One-Line Launch")
    session.append("```powershell")
    session.append('powershell -ExecutionPolicy Bypass -File scripts/start_vroid_v11_session.ps1 -StateNote "resume v11 full-toolset pass" -SkipStateTouch')
    session.append("```")
    session.append("")

    session.append("## Full Toolset Confirmed Scope")
    session.append("- Body, Face, Hairstyle, Ahoge, Outfit, Accessories, Texture Editor")
    session.append("- Focus is on VRoid model fidelity only; runtime/game code untouched during this pass.")

    OUT_FILE.write_text("\n".join(session), encoding="utf-8")
    print(f"Wrote {OUT_FILE}")


if __name__ == "__main__":
    main()
