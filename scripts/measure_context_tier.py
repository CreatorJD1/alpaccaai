"""JSON-only CLI for one evidence-only local context-tier measurement."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence


sys.dont_write_bytecode = True
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from alpecca.context_tier_measurement import (
    DEFAULT_OLLAMA_HOST,
    LOCAL_QWEN_MODEL,
    ContextTierValidationError,
    rejected_measurement_report,
    run_context_tier_measurement,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure one local qwen3.5:9b context tier; dry-run is the default. "
            "Execution uses a read-only host-resource preflight."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Permit at most one loopback Ollama POST after preflight; requires --tier.",
    )
    parser.add_argument(
        "--tier",
        metavar="N",
        help="One allowed context tier. Dry-run defaults to 8192.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("ALPECCA_MODEL", LOCAL_QWEN_MODEL),
        help=argparse.SUPPRESS,
    )
    return parser


def _emit(report: dict) -> None:
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


def _contains_all(arguments: Sequence[str]) -> bool:
    return any(argument == "--all" or argument.startswith("--all=") for argument in arguments)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if _contains_all(arguments):
        _emit(
            rejected_measurement_report(
                "--all is intentionally unsupported; execute one explicit --tier only."
            )
        )
        return 2

    parser = _parser()
    args, unknown = parser.parse_known_args(arguments)
    if unknown:
        _emit(rejected_measurement_report(f"unsupported arguments: {' '.join(unknown)}"))
        return 2
    if args.execute and args.tier is None:
        _emit(
            rejected_measurement_report(
                "execution requires --execute --tier N; no default tier is executed.",
                model=args.model,
                host=args.host,
            )
        )
        return 2

    tier = args.tier if args.tier is not None else 8192
    try:
        report = run_context_tier_measurement(
            tier=tier,
            execute=args.execute,
            host=args.host,
            model=args.model,
        )
    except ContextTierValidationError as exc:
        _emit(
            rejected_measurement_report(
                str(exc), tier=tier, model=args.model, host=args.host
            )
        )
        return 2

    _emit(report)
    return 0 if report.get("status") in {"dry_run", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
