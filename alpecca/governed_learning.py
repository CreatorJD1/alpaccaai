"""Read-only projections of the bounded Phase 8 behavior-trial lifecycle.

The Phase 8 stores remain the authority for candidates, trials, settlements,
and creator profile decisions. This module accepts their already-verified
status snapshot and reduces it to small deterministic facts for cognition and
Soul. It has no database handle and no lifecycle mutation methods.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any


SIGNAL_SCHEMA = "alpecca.governed-learning-signal.v1"
CANDIDATE_CARD_SCHEMA = "alpecca.governed-learning-card.v1"
CREATOR_SCOPE = "creator-personal"
PARAMETER = "chatter_chance"

_CANDIDATE_STATES = frozenset(
    {"pending_creator_plan", "ready_for_registration", "registered"}
)
_SETTLEMENT_STATUSES = frozenset(
    {"ready_for_creator_review", "inconclusive_insufficient_samples"}
)
_OUTCOMES = frozenset({"improved", "degraded", "inconclusive"})
_DECISIONS = frozenset({"retain_trial_value", "revert_to_baseline"})
_PHASES = frozenset(
    {
        "unavailable",
        "idle",
        "candidate",
        "registered",
        "approved",
        "running",
        "settling",
        "creator_review",
        "decided",
    }
)


class _InvalidStatus(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class GovernedLearningSignal:
    """One bounded, content-free lifecycle fact for observational consumers."""

    available: bool
    phase: str
    evidence_code: str
    proposal_id: int | None = None
    trial_id: int | None = None
    candidate_state: str | None = None
    trial_state: str | None = None
    parameter: str | None = None
    started_at: float | None = None
    planned_end_at: float | None = None
    settlement_status: str | None = None
    outcome: str | None = None
    decision: str | None = None
    creator_action_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"schema": SIGNAL_SCHEMA, **asdict(self)}

    @property
    def transition_key(self) -> str:
        raw = json.dumps(
            self.as_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def observation_text(self) -> str:
        proposal = f" proposal #{self.proposal_id}" if self.proposal_id else ""
        trial = f" trial #{self.trial_id}" if self.trial_id else ""
        if self.phase == "candidate":
            if self.candidate_state == "ready_for_registration":
                return (
                    f"Governed chatter{proposal} has creator plan acceptance and is "
                    "waiting for a separate registration decision."
                )
            return (
                f"Governed chatter{proposal} is waiting for creator plan review; "
                "it cannot start itself."
            )
        if self.phase == "registered":
            return (
                f"Governed chatter{trial} is registered but not approved or running; "
                "later lifecycle steps remain separate creator decisions."
            )
        if self.phase == "approved":
            return (
                f"Governed chatter{trial} is approved but stopped; only a separate "
                "creator start can apply its bounded runtime value."
            )
        if self.phase == "running":
            return (
                f"Governed chatter{trial} is running under its fixed exposure "
                "contract; the current task is observation, not retention."
            )
        if self.phase == "settling":
            return (
                f"Governed chatter{trial} has closed and is waiting for immutable "
                "evidence settlement."
            )
        if self.phase == "creator_review":
            return (
                f"Governed chatter{trial} settled as {self.outcome}; only the creator "
                "can choose the retained behavior profile."
            )
        if self.phase == "decided":
            selected = (
                "the trial value"
                if self.decision == "retain_trial_value"
                else "the pre-trial value"
            )
            return (
                f"The creator selected {selected} for governed chatter{trial}; no "
                "runtime trial remains active."
            )
        if self.phase == "idle":
            return "No governed chatter candidate, trial, or creator review is pending."
        return "Governed learning status is unavailable and no lifecycle claim is made."

    def candidate_card(self) -> dict[str, Any] | None:
        """Return a read-only link to the authoritative Workshop proposal."""
        if not self.available or self.proposal_id is None:
            return None
        waiting_for = {
            "candidate": (
                "creator_registration"
                if self.candidate_state == "ready_for_registration"
                else "creator_plan_review"
            ),
            "registered": "creator_approval",
            "approved": "creator_start",
            "running": "evidence_collection",
            "settling": "settlement",
            "creator_review": "creator_profile_decision",
            "decided": "none",
        }.get(self.phase, "none")
        return {
            "schema": CANDIDATE_CARD_SCHEMA,
            "proposal_id": self.proposal_id,
            "trial_id": self.trial_id,
            "phase": self.phase,
            "candidate_state": self.candidate_state,
            "trial_state": self.trial_state,
            "waiting_for": waiting_for,
            "creator_action_required": self.creator_action_required,
            "read_only": True,
        }


@dataclass(frozen=True, slots=True)
class GovernedLearningCue:
    action: str
    reason: str
    urgency: float


def _unavailable(code: str) -> GovernedLearningSignal:
    return GovernedLearningSignal(False, "unavailable", code)


def _mapping(value: object, *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _InvalidStatus(code)
    return value


def _sequence(value: object, *, code: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise _InvalidStatus(code)
    return value


def _positive_id(value: object, *, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _InvalidStatus(code)
    return value


def _optional_timestamp(value: object, *, code: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise _InvalidStatus(code)
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise _InvalidStatus(code)
    return stamp


def _candidate(status: Mapping[str, Any]) -> dict[str, Any] | None:
    if status.get("registration_candidate_available", True) is not True:
        return None
    raw = status.get("registration_candidate")
    if raw is None:
        return None
    value = _mapping(raw, code="candidate_invalid")
    state = value.get("state")
    if not isinstance(state, str) or state not in _CANDIDATE_STATES:
        raise _InvalidStatus("candidate_invalid")
    result: dict[str, Any] = {
        "proposal_id": _positive_id(
            value.get("proposal_id"), code="candidate_invalid"
        ),
        "state": state,
        "trial_id": None,
        "trial_state": None,
    }
    if state != "registered":
        return result
    result["trial_id"] = _positive_id(
        value.get("registered_trial_id"), code="candidate_invalid"
    )
    trial = value.get("trial")
    if trial is None:
        return result
    trial_map = _mapping(trial, code="candidate_trial_invalid")
    if _positive_id(trial_map.get("id"), code="candidate_trial_invalid") != result["trial_id"]:
        raise _InvalidStatus("candidate_trial_invalid")
    trial_state = trial_map.get("state")
    if not isinstance(trial_state, str) or trial_state not in {
        "registered",
        "approved",
        "running",
        "rolled_back",
    }:
        raise _InvalidStatus("candidate_trial_invalid")
    result["trial_state"] = trial_state
    return result


def _active_signal(status: Mapping[str, Any]) -> GovernedLearningSignal | None:
    raw = status.get("active_trial")
    if raw is None:
        return None
    trial = _mapping(raw, code="active_trial_invalid")
    trial_id = _positive_id(trial.get("id"), code="active_trial_invalid")
    proposal_id = _positive_id(
        trial.get("proposal_id"), code="active_trial_invalid"
    )
    state = trial.get("state")
    if state not in {"approved", "running"}:
        raise _InvalidStatus("active_trial_invalid")
    if trial.get("scope") != CREATOR_SCOPE or trial.get("parameter") != PARAMETER:
        raise _InvalidStatus("active_trial_invalid")
    if trial.get("creator_binding_present") is not True:
        raise _InvalidStatus("active_trial_unbound")
    started_at = _optional_timestamp(
        trial.get("started_at"), code="active_trial_invalid"
    )
    planned_end_at = _optional_timestamp(
        trial.get("planned_end_at"), code="active_trial_invalid"
    )
    runtime = status.get("runtime_override")
    if state == "approved":
        if runtime is not None or started_at is not None or planned_end_at is not None:
            raise _InvalidStatus("approved_trial_runtime_present")
        return GovernedLearningSignal(
            True,
            "approved",
            "verified_active_trial",
            proposal_id=proposal_id,
            trial_id=trial_id,
            candidate_state="registered",
            trial_state=state,
            parameter=PARAMETER,
            creator_action_required=True,
        )
    runtime_map = _mapping(runtime, code="running_override_missing")
    if (
        _positive_id(runtime_map.get("trial_id"), code="running_override_invalid")
        != trial_id
        or runtime_map.get("scope") != CREATOR_SCOPE
        or runtime_map.get("parameter") != PARAMETER
        or started_at is None
        or planned_end_at is None
        or planned_end_at <= started_at
    ):
        raise _InvalidStatus("running_override_invalid")
    return GovernedLearningSignal(
        True,
        "running",
        "verified_active_trial",
        proposal_id=proposal_id,
        trial_id=trial_id,
        candidate_state="registered",
        trial_state=state,
        parameter=PARAMETER,
        started_at=started_at,
        planned_end_at=planned_end_at,
    )


def _decisions(status: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    if status.get("profile_decisions_available", True) is not True:
        return None
    result: list[dict[str, Any]] = []
    for raw in _sequence(status.get("profile_decisions", []), code="decisions_invalid"):
        value = _mapping(raw, code="decisions_invalid")
        decision = value.get("decision")
        if decision not in _DECISIONS:
            raise _InvalidStatus("decisions_invalid")
        result.append(
            {
                "trial_id": _positive_id(
                    value.get("trial_id"), code="decisions_invalid"
                ),
                "decision": decision,
            }
        )
    return result


def _settlements(status: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    if status.get("review_settlements_available", True) is not True:
        return None
    result: list[dict[str, Any]] = []
    for raw in _sequence(
        status.get("review_settlements", []), code="settlements_invalid"
    ):
        value = _mapping(raw, code="settlements_invalid")
        settlement_status = value.get("status")
        outcome = value.get("outcome")
        if settlement_status not in _SETTLEMENT_STATUSES or outcome not in _OUTCOMES:
            raise _InvalidStatus("settlements_invalid")
        result.append(
            {
                "trial_id": _positive_id(
                    value.get("trial_id"), code="settlements_invalid"
                ),
                "status": settlement_status,
                "outcome": outcome,
            }
        )
    return result


def build_signal(status: object) -> GovernedLearningSignal:
    """Normalize a recovery-gated Phase 8 status snapshot without side effects."""
    if not isinstance(status, Mapping):
        return _unavailable("status_invalid")
    if status.get("recovery_ready", True) is not True:
        return _unavailable("recovery_not_ready")
    try:
        active = _active_signal(status)
        if active is not None:
            return active

        candidate_available = status.get(
            "registration_candidate_available", True
        ) is True
        candidate = _candidate(status)
        if candidate is not None and candidate["trial_state"] in {
            "approved",
            "running",
        }:
            raise _InvalidStatus("active_trial_missing")

        settlements = _settlements(status)
        decisions = _decisions(status)
        if settlements is not None:
            if settlements and decisions is None:
                raise _InvalidStatus("decisions_unavailable")
            decided_ids = {
                int(item["trial_id"]): str(item["decision"])
                for item in (decisions or [])
            }
            for settlement in settlements:
                trial_id = int(settlement["trial_id"])
                if trial_id in decided_ids:
                    continue
                if candidate is not None and (
                    candidate["state"] != "registered"
                    or candidate["trial_id"] != trial_id
                ):
                    raise _InvalidStatus("candidate_settlement_conflict")
                proposal_id = None
                if candidate is not None and candidate["trial_id"] == trial_id:
                    proposal_id = int(candidate["proposal_id"])
                return GovernedLearningSignal(
                    True,
                    "creator_review",
                    "verified_settlement",
                    proposal_id=proposal_id,
                    trial_id=trial_id,
                    candidate_state=(
                        None if candidate is None else str(candidate["state"])
                    ),
                    trial_state="rolled_back",
                    parameter=PARAMETER,
                    settlement_status=str(settlement["status"]),
                    outcome=str(settlement["outcome"]),
                    creator_action_required=True,
                )

        if candidate is not None and candidate["state"] != "registered":
            return GovernedLearningSignal(
                True,
                "candidate",
                "verified_candidate",
                proposal_id=int(candidate["proposal_id"]),
                candidate_state=str(candidate["state"]),
                parameter=PARAMETER,
                creator_action_required=True,
            )

        if candidate is not None:
            phase = (
                "settling"
                if candidate["trial_state"] == "rolled_back"
                else "registered"
            )
            return GovernedLearningSignal(
                True,
                phase,
                "verified_registered_candidate",
                proposal_id=int(candidate["proposal_id"]),
                trial_id=int(candidate["trial_id"]),
                candidate_state="registered",
                trial_state=(
                    None
                    if candidate["trial_state"] is None
                    else str(candidate["trial_state"])
                ),
                parameter=PARAMETER,
                creator_action_required=phase == "registered",
            )

        if decisions:
            latest = decisions[0]
            return GovernedLearningSignal(
                True,
                "decided",
                "verified_profile_decision",
                trial_id=int(latest["trial_id"]),
                parameter=PARAMETER,
                decision=str(latest["decision"]),
            )

        if not candidate_available or settlements is None:
            return _unavailable("optional_status_unavailable")
        return GovernedLearningSignal(True, "idle", "verified_idle")
    except _InvalidStatus as exc:
        return _unavailable(exc.code)


def _signal_is_valid(signal: GovernedLearningSignal) -> bool:
    if (
        type(signal.available) is not bool
        or signal.phase not in _PHASES
        or not isinstance(signal.evidence_code, str)
        or not signal.evidence_code
        or len(signal.evidence_code) > 80
        or type(signal.creator_action_required) is not bool
    ):
        return False
    if not signal.available:
        return signal == _unavailable(signal.evidence_code)
    if signal.phase == "unavailable":
        return False
    for value in (signal.proposal_id, signal.trial_id):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            return False
    for value in (signal.started_at, signal.planned_end_at):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(float(value))
            or float(value) < 0.0
        ):
            return False
    for value in (
        signal.candidate_state,
        signal.trial_state,
        signal.parameter,
        signal.settlement_status,
        signal.outcome,
        signal.decision,
    ):
        if value is not None and not isinstance(value, str):
            return False
    if signal.phase == "idle":
        return signal == GovernedLearningSignal(True, "idle", signal.evidence_code)
    if signal.parameter != PARAMETER:
        return False
    if signal.phase == "candidate":
        return bool(
            signal.proposal_id
            and signal.trial_id is None
            and signal.candidate_state
            in {"pending_creator_plan", "ready_for_registration"}
            and signal.trial_state is None
            and signal.creator_action_required
        )
    if signal.phase == "registered":
        return bool(
            signal.proposal_id
            and signal.trial_id
            and signal.candidate_state == "registered"
            and signal.trial_state in {None, "registered"}
            and signal.creator_action_required
        )
    if signal.phase == "approved":
        return bool(
            signal.proposal_id
            and signal.trial_id
            and signal.candidate_state == "registered"
            and signal.trial_state == "approved"
            and signal.started_at is None
            and signal.planned_end_at is None
            and signal.creator_action_required
        )
    if signal.phase == "running":
        return bool(
            signal.proposal_id
            and signal.trial_id
            and signal.candidate_state == "registered"
            and signal.trial_state == "running"
            and signal.started_at is not None
            and signal.planned_end_at is not None
            and float(signal.planned_end_at) > float(signal.started_at)
            and not signal.creator_action_required
        )
    if signal.phase == "settling":
        return bool(
            signal.proposal_id
            and signal.trial_id
            and signal.candidate_state == "registered"
            and signal.trial_state == "rolled_back"
            and not signal.creator_action_required
        )
    if signal.phase == "creator_review":
        return bool(
            signal.trial_id
            and signal.trial_state == "rolled_back"
            and signal.settlement_status in _SETTLEMENT_STATUSES
            and signal.outcome in _OUTCOMES
            and signal.creator_action_required
        )
    if signal.phase == "decided":
        return bool(
            signal.trial_id
            and signal.decision in _DECISIONS
            and not signal.creator_action_required
        )
    return False


def coerce_signal(value: object) -> GovernedLearningSignal:
    """Accept an adapter value or its exact public mapping; otherwise fail closed."""
    if isinstance(value, GovernedLearningSignal):
        return value if _signal_is_valid(value) else _unavailable("signal_invalid")
    expected_fields = {
        "schema",
        "available",
        "phase",
        "evidence_code",
        "proposal_id",
        "trial_id",
        "candidate_state",
        "trial_state",
        "parameter",
        "started_at",
        "planned_end_at",
        "settlement_status",
        "outcome",
        "decision",
        "creator_action_required",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected_fields
        or value.get("schema") != SIGNAL_SCHEMA
    ):
        return _unavailable("signal_invalid")
    try:
        available = value.get("available")
        phase = value.get("phase")
        evidence_code = value.get("evidence_code")
        creator_action_required = value.get("creator_action_required")
        if (
            type(available) is not bool
            or not isinstance(phase, str)
            or not isinstance(evidence_code, str)
            or type(creator_action_required) is not bool
        ):
            raise _InvalidStatus("signal_invalid")
        signal = GovernedLearningSignal(
            available=available,
            phase=phase,
            evidence_code=evidence_code,
            proposal_id=(
                None
                if value.get("proposal_id") is None
                else _positive_id(value.get("proposal_id"), code="signal_invalid")
            ),
            trial_id=(
                None
                if value.get("trial_id") is None
                else _positive_id(value.get("trial_id"), code="signal_invalid")
            ),
            candidate_state=value.get("candidate_state"),
            trial_state=value.get("trial_state"),
            parameter=value.get("parameter"),
            started_at=_optional_timestamp(
                value.get("started_at"), code="signal_invalid"
            ),
            planned_end_at=_optional_timestamp(
                value.get("planned_end_at"), code="signal_invalid"
            ),
            settlement_status=value.get("settlement_status"),
            outcome=value.get("outcome"),
            decision=value.get("decision"),
            creator_action_required=creator_action_required,
        )
        return signal if _signal_is_valid(signal) else _unavailable("signal_invalid")
    except _InvalidStatus:
        return _unavailable("signal_invalid")


def soul_cue(value: object) -> GovernedLearningCue | None:
    """Map verified status to one non-mutating Improver cue."""
    signal = coerce_signal(value)
    if not signal.available:
        return None
    cue = {
        "candidate": GovernedLearningCue(
            "keep the governed candidate visible",
            "a server-issued candidate is waiting for a creator lifecycle decision",
            0.46,
        ),
        "registered": GovernedLearningCue(
            "hold the governed trial at registration",
            "registration is complete but approval and start remain creator decisions",
            0.48,
        ),
        "approved": GovernedLearningCue(
            "wait for a creator trial start",
            "the governed trial is approved but its runtime override is not active",
            0.50,
        ),
        "running": GovernedLearningCue(
            "observe governed trial evidence",
            "a verified bounded trial is running and no retention decision is due yet",
            0.52,
        ),
        "settling": GovernedLearningCue(
            "wait for governed trial settlement",
            "the runtime value is restored and immutable outcome evidence is pending",
            0.50,
        ),
        "creator_review": GovernedLearningCue(
            "hold the governed result for creator review",
            "settled evidence cannot select a retained behavior value autonomously",
            0.56,
        ),
    }.get(signal.phase)
    return cue


__all__ = [
    "CANDIDATE_CARD_SCHEMA",
    "CREATOR_SCOPE",
    "GovernedLearningCue",
    "GovernedLearningSignal",
    "PARAMETER",
    "SIGNAL_SCHEMA",
    "build_signal",
    "coerce_signal",
    "soul_cue",
]
