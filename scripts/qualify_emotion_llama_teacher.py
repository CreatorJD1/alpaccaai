#!/usr/bin/env python3
"""Qualify or compare the opt-in Emotion-LLaMA ROG research teacher.

This script does not download assets or import Emotion-LLaMA. Run it only on
Jason_HOLYROG after separately obtaining licensed assets and recording their
absolute paths and SHA-256 digests in a private manifest copy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpecca.emotion_llama_teacher import (  # noqa: E402
    QualificationError,
    TeacherResult,
    compare_teacher_to_hyfuser,
    qualify_manifest,
)


def _read_object(path: str) -> dict[str, object]:
    value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--ack-research-only",
        action="store_true",
        help="Confirm this run is non-commercial research under the recorded licenses.",
    )
    parser.add_argument("--teacher-result")
    parser.add_argument("--hyfuser-advisory")
    parser.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        lane = qualify_manifest(
            args.manifest,
            repository_root=ROOT,
            acknowledge_research_only=args.ack_research_only,
        )
        if bool(args.teacher_result) != bool(args.hyfuser_advisory):
            raise ValueError("teacher result and HyFusER advisory must be provided together")
        payload: dict[str, object] = lane.as_dict()
        if args.teacher_result:
            teacher = TeacherResult.from_mapping(_read_object(args.teacher_result))
            payload = compare_teacher_to_hyfuser(
                teacher,
                _read_object(args.hyfuser_advisory),
                qualified_lane=lane,
            )
        rendered = json.dumps(payload, indent=2, sort_keys=True)
        if args.output:
            Path(args.output).expanduser().write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0
    except (OSError, ValueError, json.JSONDecodeError, QualificationError) as exc:
        print(json.dumps({"qualified": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
