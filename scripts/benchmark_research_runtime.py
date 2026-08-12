"""Deterministic, evaluation-only coverage for Alpecca research runtimes.

The harness exercises the real temporal-memory, observer-slot, and inference
scheduler APIs against generated evidence. Every SQLite file is created below
an owned temporary directory and removed at the end of the run. It never reads
runtime configuration, discovers a production database, changes a backend, or
performs model/network work.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import time

if __package__ in {None, ""}:
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from alpecca.inference_scheduler import InferenceScheduler, PriorityLane
from alpecca.observer_slots import ObserverSlot
from alpecca.temporal_memory import TemporalMemoryStore
from alpecca.temporal_runtime import TemporalRuntime


RESULT_SCHEMA = "alpecca.research-runtime.benchmark-result.v1"
MODE = "evaluation-only"
MAX_RELATION_CASES = 16
MAX_RETRIEVAL_SCALE = 4_096
MAX_RETRIEVAL_SCALES = 8
MAX_RETRIEVAL_QUERIES = 64
MAX_OBSERVER_UPDATES = 256

NanosecondClock = Callable[[], int]


class BenchmarkValidationError(ValueError):
    """The bounded benchmark definition or injected clock is invalid."""


def _positive_int(value: object, *, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise BenchmarkValidationError(
            f"{name} must be an integer from 1 to {maximum}"
        )
    return value


def _positive_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkValidationError(f"{name} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise BenchmarkValidationError(f"{name} must be a positive finite number")
    return result


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    seed: int = 20_260_722
    correction_cases: int = 4
    supersession_cases: int = 4
    retrieval_scales: tuple[int, ...] = (32, 128, 512)
    retrieval_queries: int = 7
    observer_updates: int = 12
    stale_attempts: int = 4
    max_retrieval_latency_ms: float = 100.0

    def __post_init__(self) -> None:
        if type(self.seed) is not int or not 0 <= self.seed <= 2**63 - 1:
            raise BenchmarkValidationError("seed must be a non-negative 63-bit integer")
        _positive_int(
            self.correction_cases,
            name="correction_cases",
            maximum=MAX_RELATION_CASES,
        )
        _positive_int(
            self.supersession_cases,
            name="supersession_cases",
            maximum=MAX_RELATION_CASES,
        )
        try:
            scales = tuple(self.retrieval_scales)
        except TypeError:
            raise BenchmarkValidationError("retrieval_scales must be a sequence") from None
        if not 1 <= len(scales) <= MAX_RETRIEVAL_SCALES:
            raise BenchmarkValidationError(
                f"retrieval_scales must contain 1 to {MAX_RETRIEVAL_SCALES} values"
            )
        if any(type(scale) is not int or not 1 <= scale <= MAX_RETRIEVAL_SCALE for scale in scales):
            raise BenchmarkValidationError(
                f"retrieval scales must be integers from 1 to {MAX_RETRIEVAL_SCALE}"
            )
        if len(set(scales)) != len(scales):
            raise BenchmarkValidationError("retrieval scales must be unique")
        object.__setattr__(self, "retrieval_scales", tuple(sorted(scales)))
        _positive_int(
            self.retrieval_queries,
            name="retrieval_queries",
            maximum=MAX_RETRIEVAL_QUERIES,
        )
        _positive_int(
            self.observer_updates,
            name="observer_updates",
            maximum=MAX_OBSERVER_UPDATES,
        )
        if self.observer_updates < 2:
            raise BenchmarkValidationError("observer_updates must be at least 2")
        _positive_int(
            self.stale_attempts,
            name="stale_attempts",
            maximum=MAX_OBSERVER_UPDATES,
        )
        object.__setattr__(
            self,
            "max_retrieval_latency_ms",
            _positive_number(
                self.max_retrieval_latency_ms,
                name="max_retrieval_latency_ms",
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "correction_cases": self.correction_cases,
            "supersession_cases": self.supersession_cases,
            "retrieval_scales": list(self.retrieval_scales),
            "retrieval_queries": self.retrieval_queries,
            "observer_updates": self.observer_updates,
            "stale_attempts": self.stale_attempts,
            "max_retrieval_latency_ms": self.max_retrieval_latency_ms,
        }


@dataclass(slots=True)
class _SyntheticClock:
    value: float = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += seconds


def _clock_read(clock: NanosecondClock) -> int:
    value = clock()
    if type(value) is not int or value < 0:
        raise BenchmarkValidationError(
            "latency clock must return non-negative integer nanoseconds"
        )
    return value


def _timed_call(callback: Callable[[], object], clock: NanosecondClock) -> tuple[object, float]:
    started = _clock_read(clock)
    result = callback()
    finished = _clock_read(clock)
    if finished < started:
        raise BenchmarkValidationError("latency clock must be monotonic")
    return result, round((finished - started) / 1_000_000.0, 6)


def _p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return round(ordered[index], 6)


def _drain(runtime: TemporalRuntime) -> tuple[object, ...]:
    outcomes: list[object] = []
    while runtime.status().pending_observations:
        batch = runtime.process_batch()
        outcomes.extend(batch.outcomes)
    return tuple(outcomes)


def _relation_fixture(
    root: Path,
    config: BenchmarkConfig,
) -> tuple[dict[str, object], dict[str, object]]:
    store = TemporalMemoryStore(root / "relations.sqlite3")
    runtime = TemporalRuntime(
        store,
        max_pending=2 * (config.correction_cases + config.supersession_cases),
    )
    rng = random.Random(config.seed)
    scope = "benchmark-evaluation"
    expected_by_uid: dict[str, dict[str, object]] = {}
    expected_signatures: set[tuple[str, str, str]] = set()
    update_cases: list[dict[str, object]] = []

    relations = (
        ("correction", config.correction_cases),
        ("supersession", config.supersession_cases),
    )
    sequence = 0
    for relation, count in relations:
        for index in range(count):
            sequence += 1
            subject = f"{relation}-subject-{index:03d}"
            predicate = "current_state"
            prior_value = f"old-{rng.randrange(1_000_000):06d}"
            current_value = f"new-{rng.randrange(1_000_000):06d}"
            actor = f"benchmark-actor-{index % 3}"
            original_at = 1_000.0 + sequence
            update_at = 10_000.0 + sequence
            original_uid = f"relation-{relation}-{index:03d}-original"
            update_uid = f"relation-{relation}-{index:03d}-update"
            original_text = (
                f"fact: {subject} | {predicate} | {prior_value} | 0.8"
            )
            update_text = (
                f"{relation}: {subject} | {predicate} | {current_value} | 0.95"
            )
            common = {
                "source": "benchmark-seed",
                "channel": "benchmark-temporal",
                "actor_id": actor,
                "scope": scope,
            }
            runtime.ingest_observation(
                original_text,
                observed_at=original_at,
                observation_uid=original_uid,
                raw_reference=f"fixture:{original_uid}",
                metadata={"fixture": "relation", "relation": "assertion"},
                **common,
            )
            expected_by_uid[original_uid] = {
                **common,
                "text": original_text,
                "signature": (subject, predicate, prior_value),
            }
            expected_signatures.add((subject, predicate, prior_value))
            update_cases.append(
                {
                    "relation": relation,
                    "subject": subject,
                    "predicate": predicate,
                    "value": current_value,
                    "actor_id": actor,
                    "observed_at": update_at,
                    "uid": update_uid,
                    "text": update_text,
                    "common": common,
                }
            )

    original_outcomes = _drain(runtime)
    for case in update_cases:
        common = case["common"]
        assert isinstance(common, dict)
        runtime.ingest_observation(
            str(case["text"]),
            observed_at=float(case["observed_at"]),
            observation_uid=str(case["uid"]),
            raw_reference=f"fixture:{case['uid']}",
            metadata={"fixture": "relation", "relation": case["relation"]},
            **common,
        )
        expected_by_uid[str(case["uid"])] = {
            **common,
            "text": case["text"],
            "signature": (
                case["subject"],
                case["predicate"],
                case["value"],
            ),
        }
        expected_signatures.add(
            (str(case["subject"]), str(case["predicate"]), str(case["value"]))
        )
    update_outcomes = _drain(runtime)
    all_outcomes = original_outcomes + update_outcomes
    outcomes_by_uid = {
        outcome.candidate.source_observation_uid: outcome
        for outcome in all_outcomes
    }

    relation_results: dict[str, object] = {}
    for relation, count in relations:
        selected = [case for case in update_cases if case["relation"] == relation]
        correct = 0
        for case in selected:
            outcome = outcomes_by_uid.get(str(case["uid"]))
            active = store.facts_valid_at(
                float(case["observed_at"]),
                scope=scope,
                subject=str(case["subject"]),
                predicate=str(case["predicate"]),
            )
            if (
                outcome is not None
                and outcome.candidate.relation == relation
                and outcome.fact.object_text == case["value"]
                and len(outcome.closed_fact_ids) == 1
                and len(outcome.contradiction_links) == 1
                and len(active) == 1
                and active[0].id == outcome.fact.id
                and active[0].object_text == case["value"]
            ):
                correct += 1
        relation_results[relation] = {
            "expected": count,
            "correct": correct,
            "accuracy": round(correct / count, 6),
            "passed": correct == count,
        }

    missing_evidence = 0
    provenance_mismatches = 0
    invented_signatures: list[str] = []
    observed_signatures: set[tuple[str, str, str]] = set()
    for outcome in all_outcomes:
        fact = outcome.fact
        signature = (fact.subject, fact.predicate, fact.object_text)
        observed_signatures.add(signature)
        if signature not in expected_signatures:
            invented_signatures.append(" | ".join(signature))
        expected = expected_by_uid.get(outcome.candidate.source_observation_uid)
        evidence = store.evidence_for_fact(fact.id)
        if not evidence:
            missing_evidence += 1
            continue
        if expected is None or len(evidence) != 1:
            provenance_mismatches += 1
            continue
        observation = evidence[0]
        expected_digest = hashlib.sha256(
            str(expected["text"]).encode("utf-8")
        ).hexdigest()
        if not (
            observation.id == fact.primary_observation_id
            and observation.observation_uid == outcome.candidate.source_observation_uid
            and observation.source == expected["source"]
            and observation.actor_id == expected["actor_id"] == fact.actor_id
            and observation.surface == expected["channel"] == fact.surface
            and observation.scope == expected["scope"] == fact.scope
            and observation.content_sha256 == expected_digest
        ):
            provenance_mismatches += 1

    no_invention = (
        not invented_signatures
        and observed_signatures == expected_signatures
        and len(all_outcomes) == len(expected_signatures)
    )
    provenance = {
        "facts_checked": len(all_outcomes),
        "missing_evidence": missing_evidence,
        "provenance_mismatches": provenance_mismatches,
        "passed": missing_evidence == 0 and provenance_mismatches == 0,
    }
    invention = {
        "expected_fact_count": len(expected_signatures),
        "observed_fact_count": len(observed_signatures),
        "invented_fact_count": len(invented_signatures),
        "invented_signatures": sorted(invented_signatures),
        "passed": no_invention,
    }
    return relation_results, {"provenance": provenance, "no_invention": invention}


def _duplicate_fixture(root: Path) -> dict[str, object]:
    store = TemporalMemoryStore(root / "duplicates.sqlite3")
    runtime = TemporalRuntime(store)
    kwargs = {
        "source": "benchmark-seed",
        "channel": "benchmark-observer",
        "actor_id": "benchmark-actor",
        "scope": "benchmark-duplicate",
        "observed_at": 500.0,
    }
    text = "fact: duplicate-subject | state | stable | 0.9"
    first = runtime.ingest_observation(text, **kwargs)
    duplicate = runtime.ingest_observation(text, **kwargs)
    pending_after_duplicate = runtime.status().pending_observations
    runtime.process_batch()
    facts_before_replay = store.facts_valid_at(
        500.0,
        scope="benchmark-duplicate",
        subject="duplicate-subject",
        predicate="state",
    )
    replay = runtime.ingest_observation(text, **kwargs)
    runtime.process_batch()
    facts_after_replay = store.facts_valid_at(
        500.0,
        scope="benchmark-duplicate",
        subject="duplicate-subject",
        predicate="state",
    )
    queued_duplicate_suppressed = bool(
        first.queued
        and duplicate.duplicate
        and not duplicate.queued
        and pending_after_duplicate == 1
    )
    durable_replay_idempotent = bool(
        first.observation is not None
        and replay.observation is not None
        and first.observation.id == replay.observation.id
        and len(facts_before_replay) == len(facts_after_replay) == 1
        and facts_before_replay[0].id == facts_after_replay[0].id
    )
    return {
        "scope": "pending-queue-and-durable-storage",
        "queued_duplicate_suppressed": queued_duplicate_suppressed,
        "pending_after_duplicate": pending_after_duplicate,
        "durable_replay_requeued_for_idempotent_processing": replay.queued,
        "durable_replay_idempotent": durable_replay_idempotent,
        "facts_before_replay": len(facts_before_replay),
        "facts_after_replay": len(facts_after_replay),
        "passed": queued_duplicate_suppressed and durable_replay_idempotent,
    }


def _retrieval_fixture(
    root: Path,
    config: BenchmarkConfig,
    clock_ns: NanosecondClock,
) -> dict[str, object]:
    scale_results: list[dict[str, object]] = []
    for scale in config.retrieval_scales:
        store = TemporalMemoryStore(root / f"retrieval-{scale}.sqlite3")
        scope = f"benchmark-retrieval-{scale}"
        order = list(range(scale))
        random.Random(config.seed ^ scale).shuffle(order)
        for index in order:
            subject = f"seeded-subject-{index:06d}"
            value = f"seeded-value-{index:06d}"
            observation = store.record_observation(
                source="benchmark-seed",
                actor_id=f"benchmark-actor-{index % 4}",
                surface="benchmark-retrieval",
                scope=scope,
                observed_at=float(index + 1),
                content=f"{subject}|state|{value}",
                observation_uid=f"retrieval-{scale}-{index:06d}",
                raw_reference=f"fixture:retrieval:{scale}:{index}",
                metadata={"scale": scale, "seed": config.seed},
                recorded_at=float(index + 1),
            )
            store.record_fact(
                subject=subject,
                predicate="state",
                object_text=value,
                confidence=0.9,
                actor_id=observation.actor_id,
                surface=observation.surface,
                scope=scope,
                valid_from=observation.observed_at,
                evidence_observation_ids=(observation.id,),
                fact_uid=f"retrieval-fact-{scale}-{index:06d}",
                recorded_at=observation.observed_at,
            )

        query_count = min(config.retrieval_queries, scale)
        targets = random.Random(config.seed + scale).sample(range(scale), query_count)
        latencies: list[float] = []
        correct = 0
        for index in targets:
            subject = f"seeded-subject-{index:06d}"
            expected_value = f"seeded-value-{index:06d}"
            raw, latency = _timed_call(
                lambda subject=subject: store.facts_valid_at(
                    float(scale + 1),
                    scope=scope,
                    subject=subject,
                    predicate="state",
                ),
                clock_ns,
            )
            facts = list(raw)  # type: ignore[arg-type]
            latencies.append(latency)
            if len(facts) == 1 and facts[0].object_text == expected_value:
                correct += 1
        maximum = max(latencies)
        passed = correct == query_count and maximum <= config.max_retrieval_latency_ms
        scale_results.append(
            {
                "seeded_fact_count": scale,
                "query_count": query_count,
                "correct_count": correct,
                "accuracy": round(correct / query_count, 6),
                "latency_ms": {
                    "mean": round(sum(latencies) / len(latencies), 6),
                    "p95": _p95(latencies),
                    "max": round(maximum, 6),
                },
                "max_latency_ms": config.max_retrieval_latency_ms,
                "passed": passed,
            }
        )
    return {
        "scales": scale_results,
        "all_scales_passed": all(item["passed"] is True for item in scale_results),
    }


def _observer_fixture(config: BenchmarkConfig) -> dict[str, object]:
    clock = _SyntheticClock()
    slot = ObserverSlot[int](int, wall_clock=clock, monotonic_clock=clock)
    scheduler = InferenceScheduler[int](clock=clock)
    admissions = []
    for index in range(config.observer_updates):
        clock.advance()
        published = slot.publish(
            index,
            source="benchmark-observer",
            observed_at=1_000.0 + index,
            event_id=f"observer-{index:04d}",
            metadata={"seed": config.seed},
        )
        admissions.append(
            scheduler.submit(
                index,
                PriorityLane.P2_BACKGROUND,
                source="benchmark-observer",
                coalesce_key="host-pressure",
                metadata={"observer_version": published.observation.version},
            )
        )
    pending = scheduler.pending()
    stats = scheduler.stats()
    latest = slot.read()
    coalescing_passed = bool(
        all(item.accepted for item in admissions)
        and stats.queued == 1
        and stats.accepted == 1
        and stats.coalesced == config.observer_updates - 1
        and len(pending) == 1
        and pending[0].payload == config.observer_updates - 1
        and pending[0].coalesced_count == config.observer_updates - 1
        and latest is not None
        and latest.version == config.observer_updates
        and latest.value == config.observer_updates - 1
    )

    stale_clock = _SyntheticClock(500.0)
    stale_slot = ObserverSlot[str](
        str,
        wall_clock=stale_clock,
        monotonic_clock=stale_clock,
    )
    newest = stale_slot.publish(
        "newest",
        source="benchmark-observer",
        observed_at=2_000.0,
        event_id="newest",
    )
    rejected = []
    for index in range(config.stale_attempts):
        stale_clock.advance()
        rejected.append(
            stale_slot.publish(
                f"stale-{index}",
                source="benchmark-observer",
                observed_at=1_999.0 - index,
                event_id=f"stale-{index}",
            )
        )
    current = stale_slot.read()
    rejected_count = sum(
        not item.accepted and item.reason == "out_of_order" for item in rejected
    )
    stale_passed = bool(
        newest.observation is not None
        and rejected_count == config.stale_attempts
        and current == newest.observation
    )
    return {
        "coalescing": {
            "updates": config.observer_updates,
            "queued_tasks": stats.queued,
            "new_tasks_accepted": stats.accepted,
            "coalesced_updates": stats.coalesced,
            "latest_value": latest.value if latest else None,
            "passed": coalescing_passed,
        },
        "stale_result_rejection": {
            "attempts": config.stale_attempts,
            "rejected": rejected_count,
            "latest_preserved": current == newest.observation,
            "passed": stale_passed,
        },
    }


def _gate(name: str, passed: bool, actual: object, expected: object) -> dict[str, object]:
    return {
        "name": name,
        "actual": actual,
        "expected": expected,
        "passed": passed,
    }


def run_benchmark(
    config: BenchmarkConfig | None = None,
    *,
    latency_clock_ns: NanosecondClock = time.perf_counter_ns,
) -> dict[str, object]:
    """Run all evaluations in owned temporary storage and return JSON-safe data."""

    selected = config or BenchmarkConfig()
    if not isinstance(selected, BenchmarkConfig):
        raise BenchmarkValidationError("config must be BenchmarkConfig")
    if not callable(latency_clock_ns):
        raise BenchmarkValidationError("latency_clock_ns must be callable")

    with tempfile.TemporaryDirectory(prefix="alpecca-research-runtime-") as directory:
        root = Path(directory)
        relations, integrity = _relation_fixture(root, selected)
        duplicates = _duplicate_fixture(root)
        retrieval = _retrieval_fixture(root, selected, latency_clock_ns)
        observers = _observer_fixture(selected)

    correction = relations["correction"]
    supersession = relations["supersession"]
    provenance = integrity["provenance"]
    no_invention = integrity["no_invention"]
    coalescing = observers["coalescing"]
    stale = observers["stale_result_rejection"]
    gates = [
        _gate("correction_accuracy", bool(correction["passed"]), correction["accuracy"], 1.0),
        _gate(
            "supersession_accuracy",
            bool(supersession["passed"]),
            supersession["accuracy"],
            1.0,
        ),
        _gate("provenance", bool(provenance["passed"]), provenance, "no-mismatch"),
        _gate("no_invention", bool(no_invention["passed"]), no_invention, "exact-set"),
        _gate(
            "bounded_retrieval_latency",
            bool(retrieval["all_scales_passed"]),
            [item["latency_ms"]["max"] for item in retrieval["scales"]],
            selected.max_retrieval_latency_ms,
        ),
        _gate("observer_coalescing", bool(coalescing["passed"]), coalescing, "latest-only"),
        _gate("stale_result_rejection", bool(stale["passed"]), stale, "all-rejected"),
        _gate(
            "duplicate_suppression",
            bool(duplicates["passed"]),
            duplicates,
            "queued-suppression-and-durable-idempotency",
        ),
    ]
    passed = all(gate["passed"] is True for gate in gates)
    return {
        "schema": RESULT_SCHEMA,
        "mode": MODE,
        "passed": passed,
        "config": selected.as_dict(),
        "safeguards": {
            "temporary_databases_only": True,
            "temporary_databases_removed_after_run": True,
            "production_database_used": False,
            "production_defaults_changed": False,
            "network_used": False,
            "model_calls": 0,
            "optional_packages_imported_by_harness": False,
        },
        "temporal_memory": {
            "relation_accuracy": relations,
            **integrity,
            "duplicate_suppression": duplicates,
            "retrieval": retrieval,
        },
        "observer_runtime": observers,
        "acceptance_gates": gates,
    }


def stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _parse_scales(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError:
        raise argparse.ArgumentTypeError("scales must be comma-separated integers") from None


def build_parser() -> argparse.ArgumentParser:
    defaults = BenchmarkConfig()
    parser = argparse.ArgumentParser(
        description="Run isolated temporal-memory and observer runtime evaluations."
    )
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--correction-cases", type=int, default=defaults.correction_cases)
    parser.add_argument(
        "--supersession-cases",
        type=int,
        default=defaults.supersession_cases,
    )
    parser.add_argument("--scales", type=_parse_scales, default=defaults.retrieval_scales)
    parser.add_argument("--queries", type=int, default=defaults.retrieval_queries)
    parser.add_argument("--observer-updates", type=int, default=defaults.observer_updates)
    parser.add_argument("--stale-attempts", type=int, default=defaults.stale_attempts)
    parser.add_argument(
        "--max-retrieval-ms",
        type=float,
        default=defaults.max_retrieval_latency_ms,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = BenchmarkConfig(
            seed=args.seed,
            correction_cases=args.correction_cases,
            supersession_cases=args.supersession_cases,
            retrieval_scales=args.scales,
            retrieval_queries=args.queries,
            observer_updates=args.observer_updates,
            stale_attempts=args.stale_attempts,
            max_retrieval_latency_ms=args.max_retrieval_ms,
        )
        result = run_benchmark(config)
    except BenchmarkValidationError as exc:
        print(
            stable_json(
                {
                    "schema": RESULT_SCHEMA,
                    "mode": MODE,
                    "passed": False,
                    "error": {"code": "invalid-benchmark", "message": str(exc)},
                }
            )
        )
        return 2
    print(stable_json(result))
    return 0 if result["passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BenchmarkConfig",
    "BenchmarkValidationError",
    "MODE",
    "RESULT_SCHEMA",
    "build_parser",
    "main",
    "run_benchmark",
    "stable_json",
]
