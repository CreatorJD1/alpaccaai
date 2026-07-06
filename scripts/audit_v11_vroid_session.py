#!/usr/bin/env python

"""Audit VRoid v11 experiment session readiness.

This validates that the manual full-toolset pass can start safely and that
critical manifest/doc/asset references are available.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT / "data" / "alpecca_art_source" / "vrm_experiment_manifest.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit VRoid v11 manual pass readiness.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to vrm_experiment_manifest.json",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail (exit 1) if any required item is missing.",
    )
    return parser.parse_args()


def check_path(root: Path, rel: str, label: str, results: List[str], errors: List[str]) -> Path:
    path = Path(rel)
    if not path.is_absolute():
        path = root / path
    if path.exists():
        results.append(f"[OK] {label}: {path}")
        return path
    errors.append(f"[MISSING] {label}: {path}")
    return path


def exists_count(glob_pattern: str, base: Path) -> int:
    return len(list(base.glob(glob_pattern)))


def run(manifest_path: Path, strict: bool = False) -> int:
    failures: List[str] = []
    ok: List[str] = []

    if not manifest_path.exists():
        print(f"[ERROR] Manifest not found: {manifest_path}")
        return 1

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    v11 = manifest.get("v11Iteration", {})
    print(f"Manifest: {manifest_path}")
    print(f"v11 state: {v11.get('state', 'unknown')}")
    print(f"v11 note:  {str(v11.get('notes', ''))[:240]}")

    exe = Path(manifest.get("tool", {}).get("exe", ""))
    checkpoint = manifest.get("currentProbe", {}).get("savedProjectPath", "")
    passboard = manifest.get("v11Passboard", "")
    full_pass = manifest.get("v11FullToolsetPass", "")
    resume_log = manifest.get("v11ResumeLog", "")
    matrix = manifest.get("v11ControlMatrix", "")
    qa_checklist = manifest.get("v11QaChecklist", "")
    design_lock = manifest.get("designLock", "")
    custom_asset_dir = Path("data/alpecca_art_source/vrm_custom_assets")
    reference_dir = Path("data/alpecca_art_source/vrm_custom_assets/ac167033")

    if exe:
        check_path(ROOT, exe, "VRoid executable", ok, failures)
    check_path(ROOT, checkpoint, "v11 checkpoint", ok, failures)
    check_path(ROOT, passboard, "v11 passboard", ok, failures)
    if full_pass:
        check_path(ROOT, full_pass, "v11 full toolset pass", ok, failures)
    if qa_checklist:
        check_path(ROOT, qa_checklist, "v11 QA checklist", ok, failures)
    if resume_log:
        check_path(ROOT, resume_log, "v11 resume log", ok, failures)
    if matrix:
        check_path(ROOT, matrix, "v11 control matrix", ok, failures)
    if design_lock:
        check_path(ROOT, design_lock, "design lock", ok, failures)

    custom_asset_path = ROOT / custom_asset_dir
    reference_path = ROOT / reference_dir
    if reference_path.exists():
        photos = exists_count("1-Photo-1.jpg", reference_path) + \
                 exists_count("2-Photo-2.jpg", reference_path) + \
                 exists_count("3-Photo-3.jpg", reference_path) + \
                 exists_count("4-Photo-4.jpg", reference_path) + \
                 exists_count("5-Photo-5.jpg", reference_path)
        ok.append(f"[OK] Reference photos present: {photos}/5 required")
        if photos < 5:
            failures.append(
                f"[MISSING] Reference photos missing from {reference_path} (found {photos}/5)."
            )
    else:
        failures.append(f"[MISSING] Reference photo folder not found: {reference_path}")

    if custom_asset_path.exists():
        ok.append(f"[OK] VRoid custom asset root: {custom_asset_path}")
    else:
        failures.append(f"[MISSING] Custom asset folder not found: {custom_asset_path}")

    for asset in [
        "alpecca_blue_x_hair_clip.svg",
        "alpecca_lash_pair_reference_v2_2048x1024.png",
        "alpecca_blue_iris_pair_texture_v2_2048x1024.png",
    ]:
        check_path(custom_asset_path, asset, f"custom asset {asset}", ok, failures)

    print("-" * 80)
    for line in ok:
        print(line)
    for line in failures:
        print(line)

    if failures:
        print(f"\nReadiness: NOT READY ({len(failures)} missing/failed checks)")
        return 1 if strict else 0

    print("\nReadiness: READY")
    print("Next: run start_vroid_v11_session.ps1 to launch checklist-guided manual pass.")
    return 0


def main() -> int:
    args = parse_args()
    return run(args.manifest, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
