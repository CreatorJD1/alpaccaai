"""Command-line entry point for the inert release-soak harness."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
from typing import Sequence

from .core import (
    DEFAULT_MOBILE_APK_URL,
    DEFAULT_MOBILE_DISCOVERY_URL,
    ReleaseSoakHarness,
    SoakConfig,
    render_report,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.release_soak",
        description=(
            "Observe bounded P14 health evidence and emit JSON. This command does not run "
            "tests/builds, manage processes, access credentials, or deploy anything."
        ),
    )
    parser.add_argument(
        "--health-url",
        default="http://127.0.0.1:8765/healthz",
        help="Exact credential-free /healthz URL (default: %(default)s).",
    )
    parser.add_argument(
        "--offline-evidence-only",
        action="store_true",
        help="Disable all optional health, discovery, and APK network observations.",
    )
    parser.add_argument(
        "--mobile-discovery-url",
        default=DEFAULT_MOBILE_DISCOVERY_URL,
        help="Credential-free public discovery JSON URL (default: reviewed R2 object).",
    )
    parser.add_argument(
        "--no-mobile-discovery",
        action="store_true",
        help="Disable the public discovery and selected-endpoint health observation.",
    )
    parser.add_argument(
        "--mobile-apk-url",
        default=DEFAULT_MOBILE_APK_URL,
        help="Credential-free public APK URL for HEAD metadata (default: reviewed R2 object).",
    )
    parser.add_argument(
        "--no-mobile-apk",
        action="store_true",
        help="Disable the public APK HEAD metadata observation.",
    )
    parser.add_argument("--process-status", type=Path, help="Content-free process status JSON.")
    parser.add_argument("--runtime-status", type=Path, help="Captured /system/status JSON.")
    parser.add_argument("--brain-graph", type=Path, help="Captured /brain/graph JSON.")
    parser.add_argument("--vault-status", type=Path, help="Captured /mindscape/vault/status JSON.")
    parser.add_argument(
        "--instance-lock",
        type=Path,
        default=REPO_ROOT / "data" / "alpecca.instance",
        help="Read-only singleton owner-metadata path (default: repository data path).",
    )
    parser.add_argument(
        "--ignore-instance-lock",
        action="store_true",
        help="Do not read supplementary singleton owner metadata.",
    )
    parser.add_argument(
        "--test-result",
        action="append",
        default=[],
        type=Path,
        help="Test result receipt JSON; may be repeated.",
    )
    parser.add_argument(
        "--build-result",
        action="append",
        default=[],
        type=Path,
        help="Build result receipt JSON; may be repeated.",
    )
    parser.add_argument("--observations", type=int, default=1, help="Number of observations.")
    parser.add_argument(
        "--interval-seconds", type=float, default=0.0, help="Delay between observations."
    )
    parser.add_argument(
        "--endpoint-timeout-seconds", type=float, default=2.0, help="Per-health-probe timeout."
    )
    parser.add_argument(
        "--public-timeout-seconds",
        type=float,
        default=5.0,
        help="Per-request timeout for public mobile continuity observations.",
    )
    parser.add_argument(
        "--status-max-age-seconds", type=float, default=300.0, help="Process/status capture age bound."
    )
    parser.add_argument(
        "--vault-snapshot-max-age-seconds",
        type=float,
        default=900.0,
        help="Maximum accepted age of the last successful compact Vault snapshot.",
    )
    parser.add_argument(
        "--vault-archive-max-age-seconds",
        type=float,
        default=28_800.0,
        help="Maximum accepted age of the last successful Vault recovery archive.",
    )
    parser.add_argument(
        "--vault-max-pending",
        type=int,
        default=0,
        help="Maximum pending snapshot and archive items accepted for each outbox.",
    )
    parser.add_argument(
        "--result-max-age-seconds",
        type=float,
        default=86_400.0,
        help="Maximum accepted age of test/build result receipts.",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Report path, or - for stdout (default: %(default)s).",
    )
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    return parser


def _write_report(destination: str, rendered: str) -> None:
    if destination == "-":
        sys.stdout.write(rendered)
        return
    target = Path(destination)
    parent = target.parent if target.parent != Path("") else Path(".")
    if not parent.is_dir():
        raise OSError(f"report parent directory does not exist: {parent}")
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
        config = SoakConfig(
            health_url=None if args.offline_evidence_only else args.health_url,
            mobile_discovery_url=(
                None
                if args.offline_evidence_only or args.no_mobile_discovery
                else args.mobile_discovery_url
            ),
            mobile_apk_url=(
                None if args.offline_evidence_only or args.no_mobile_apk else args.mobile_apk_url
            ),
            process_status_path=args.process_status,
            runtime_status_path=args.runtime_status,
            brain_graph_path=args.brain_graph,
            vault_status_path=args.vault_status,
            instance_lock_path=None if args.ignore_instance_lock else args.instance_lock,
            test_result_paths=tuple(args.test_result),
            build_result_paths=tuple(args.build_result),
            observations=args.observations,
            interval_seconds=args.interval_seconds,
            endpoint_timeout_seconds=args.endpoint_timeout_seconds,
            public_timeout_seconds=args.public_timeout_seconds,
            status_max_age_seconds=args.status_max_age_seconds,
            vault_snapshot_max_age_seconds=args.vault_snapshot_max_age_seconds,
            vault_archive_max_age_seconds=args.vault_archive_max_age_seconds,
            result_max_age_seconds=args.result_max_age_seconds,
            vault_max_pending=args.vault_max_pending,
        )
    except ValueError as exc:
        parser.error(str(exc))
    report = ReleaseSoakHarness().run(config)
    try:
        _write_report(args.output, render_report(report, pretty=not args.compact))
    except OSError as exc:
        print(f"release-soak report write failed: {exc}", file=sys.stderr)
        return 2
    return 0 if report["assessment"]["status"] == "observed_checks_passed" else 1  # type: ignore[index]


__all__ = ["build_parser", "main"]
