"""Standalone CLI for one content-free live-stack observation receipt."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
from typing import Sequence

from .live_stack import (
    DEFAULT_APK_URL,
    DEFAULT_BRAIN_GARDEN_URL,
    DEFAULT_DISCOVERY_URL,
    DEFAULT_F5_HEALTH_URL,
    DEFAULT_LOCAL_HEALTH_URL,
    LiveStackCollector,
    LiveStackConfig,
    REVIEWED_V4_NAME,
    render_receipt,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.release_soak.live_stack_cli",
        description=(
            "Collect one bounded, content-free P14 live-stack snapshot. The command "
            "does not control processes, execute commands, load credentials, speak, post, or send."
        ),
    )
    parser.add_argument("--observer-capture", type=Path, help="Fresh strict content-free capture JSON.")
    parser.add_argument("--local-health-url", default=DEFAULT_LOCAL_HEALTH_URL)
    parser.add_argument("--brain-garden-url", default=DEFAULT_BRAIN_GARDEN_URL)
    parser.add_argument("--f5-health-url", default=DEFAULT_F5_HEALTH_URL)
    parser.add_argument("--discovery-url", default=DEFAULT_DISCOVERY_URL)
    parser.add_argument("--apk-url", default=DEFAULT_APK_URL)
    parser.add_argument(
        "--v4-asset",
        type=Path,
        default=REPO_ROOT / "data" / "avatar" / "vrm" / REVIEWED_V4_NAME,
    )
    parser.add_argument(
        "--promoted-vrm",
        type=Path,
        default=REPO_ROOT / "data" / "avatar" / "vrm" / "alpecca.vrm",
    )
    parser.add_argument("--offline", action="store_true", help="Disable all network observations.")
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    parser.add_argument("--capture-max-age-seconds", type=float, default=300.0)
    parser.add_argument("--output", default="-", help="Receipt path, or - for stdout.")
    parser.add_argument("--compact", action="store_true")
    return parser


def _write(destination: str, rendered: str) -> None:
    if destination == "-":
        sys.stdout.write(rendered)
        return
    target = Path(destination)
    parent = target.parent if target.parent != Path("") else Path(".")
    if not parent.is_dir():
        raise OSError("receipt parent directory does not exist")
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=parent,
            delete=False,
        ) as temporary:
            temporary.write(rendered)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, target)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = LiveStackConfig(
            observer_capture_path=args.observer_capture,
            local_health_url=args.local_health_url,
            brain_garden_url=args.brain_garden_url,
            f5_health_url=args.f5_health_url,
            discovery_url=args.discovery_url,
            apk_url=args.apk_url,
            v4_asset_path=args.v4_asset,
            promoted_vrm_path=args.promoted_vrm,
            network_enabled=not args.offline,
            timeout_seconds=args.timeout_seconds,
            capture_max_age_seconds=args.capture_max_age_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))
    receipt = LiveStackCollector().collect(config)
    try:
        _write(args.output, render_receipt(receipt, pretty=not args.compact))
    except OSError as exc:
        print(f"live-stack receipt write failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0 if receipt["assessment"]["status"] == "snapshot_observed" else 1  # type: ignore[index]


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
