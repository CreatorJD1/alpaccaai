"""Focused CoreMind contract tests for Phase 5 unified initiative pacing."""
from __future__ import annotations

import inspect
import threading

from alpecca import mind as mind_mod
from alpecca.initiative import InitiativeBudget, InitiativePolicy


class FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _bare_mind(clock: FakeClock) -> mind_mod.CoreMind:
    """Build only the state needed by the initiative gateway, without DB setup."""
    mind = object.__new__(mind_mod.CoreMind)
    mind._initiative_budget = InitiativeBudget(
        InitiativePolicy(
            min_relevance=0.6,
            cooldown_seconds=10.0,
            window_seconds=60.0,
            max_per_window=10,
            dedupe_seconds=30.0,
            activity_quiet_seconds=5.0,
        ),
        clock=clock,
    )
    mind._initiative_lock = threading.Lock()
    mind._last_initiative_decision = None
    return mind


def _reserve(
    mind: mind_mod.CoreMind,
    *,
    event_kind: str,
    evidence_key: str,
    scope_key: str,
) -> dict:
    return mind.reserve_initiative(
        event_kind=event_kind,
        evidence_key=evidence_key,
        scope_key=scope_key,
        relevance=0.9,
        user_active=False,
        outreach=False,
    )


def test_reserve_initiative_shares_cooldown_across_event_kinds_per_scope():
    clock = FakeClock()
    mind = _bare_mind(clock)

    routine = _reserve(
        mind,
        event_kind="routine",
        evidence_key="daily-recap-v1",
        scope_key="creator-private",
    )
    same_scope_living = _reserve(
        mind,
        event_kind="living",
        evidence_key="hq-control-v2",
        scope_key="creator-private",
    )
    other_scope_living = _reserve(
        mind,
        event_kind="living",
        evidence_key="hq-control-v2",
        scope_key="guest-private",
    )

    assert routine["allowed"] is True
    assert routine["dedupe_key"] == "routine:daily-recap-v1"
    assert same_scope_living["allowed"] is False
    assert same_scope_living["reason"] == "cooldown"
    assert same_scope_living["retry_after"] == 10.0
    assert other_scope_living["allowed"] is True
    assert mind.initiative_snapshot("creator-private")["window_used"] == 1
    assert mind.initiative_snapshot("guest-private")["window_used"] == 1


def test_note_initiative_user_activity_quiets_only_the_matching_scope():
    clock = FakeClock()
    mind = _bare_mind(clock)

    activity = mind.note_initiative_user_activity("creator-private")
    creator = _reserve(
        mind,
        event_kind="volunteer",
        evidence_key="check-in-v1",
        scope_key="creator-private",
    )
    guest = _reserve(
        mind,
        event_kind="volunteer",
        evidence_key="check-in-v1",
        scope_key="guest-private",
    )

    assert activity["scope"] == "creator-private"
    assert activity["last_user_activity_at"] == 100.0
    assert creator["allowed"] is False
    assert creator["reason"] == "activity_quiet_period"
    assert creator["retry_after"] == 5.0
    assert guest["allowed"] is True
    assert mind.initiative_snapshot("creator-private")["window_used"] == 0

    clock.advance(5.0)
    after_quiet = _reserve(
        mind,
        event_kind="volunteer",
        evidence_key="check-in-v1",
        scope_key="creator-private",
    )
    assert after_quiet["allowed"] is True


def test_outreach_waits_for_delivery_outcome_then_explicit_ignore_backs_off():
    clock = FakeClock()
    mind = _bare_mind(clock)

    first = mind.reserve_initiative(
        event_kind="volunteer",
        evidence_key="first check-in",
        scope_key="creator-private",
        relevance=0.9,
        outreach=True,
    )
    immediate = mind.reserve_initiative(
        event_kind="volunteer",
        evidence_key="different check-in",
        scope_key="creator-private",
        relevance=0.9,
        outreach=True,
    )
    clock.advance(11.0)
    assert mind.mark_initiative_ignored(
        first["scope"], first["dedupe_key"],
    ) is True
    next_attempt = mind.reserve_initiative(
        event_kind="volunteer",
        evidence_key="different check-in",
        scope_key="creator-private",
        relevance=0.9,
        outreach=True,
    )

    assert first["allowed"] is True
    assert immediate["allowed"] is False
    assert immediate["reason"] == "awaiting_response"
    assert immediate["ignored_streak"] == 0
    assert next_attempt["allowed"] is False
    assert next_attempt["reason"] == "cooldown"
    assert next_attempt["ignored_streak"] == 1
    assert next_attempt["retry_after"] == 20.0
    assert mind.initiative_snapshot("creator-private")["pending_outreach_key"] is None


def test_living_world_tick_defers_before_db_or_cognition_work(monkeypatch):
    clock = FakeClock()
    mind = _bare_mind(clock)
    mind._location = "hq-control"

    first = _reserve(
        mind,
        event_kind="routine",
        evidence_key="already-reserved",
        scope_key="creator-private",
    )
    assert first["allowed"] is True

    touched: list[str] = []

    def forbidden(name: str):
        def call(*_args, **_kwargs):
            touched.append(name)
            raise AssertionError(f"deferred living tick reached {name}")

        return call

    for module, name in (
        (mind_mod.journal_mod, "open_questions"),
        (mind_mod.journal_mod, "ask"),
        (mind_mod.cognition_mod, "recent_observations"),
        (mind_mod.cognition_mod, "recent_chat_turns"),
        (mind_mod.cognition_mod, "record_observation"),
        (mind_mod.cognition_mod, "mark_observation_remembered"),
        (mind_mod.cognition_mod, "upsert_action_proposal"),
        (mind_mod.cognition_mod, "record_proposal_evaluation"),
        (mind_mod.cognition_mod, "set_intent"),
        (mind_mod.memory_store, "remember_with_id"),
    ):
        monkeypatch.setattr(module, name, forbidden(name))
    monkeypatch.setattr(
        mind,
        "_choose_living_system",
        forbidden("_choose_living_system"),
    )
    monkeypatch.setattr(
        mind,
        "_activate_living_system",
        forbidden("_activate_living_system"),
    )

    result = mind.living_world_tick(
        "background",
        {"memory": {"online": True}},
        initiative_scope="creator-private",
    )

    assert result["ok"] is True
    assert result["status"] == "deferred"
    assert result["deferred"] is True
    assert result["phase"] == "initiative_budget"
    assert result["initiative"]["scope"] == "creator-private"
    assert result["initiative"]["event_kind"] == "living"
    assert result["initiative"]["reason"] == "cooldown"
    assert touched == []
    assert mind.initiative_snapshot("creator-private")["window_used"] == 1


def test_living_world_tick_exposes_optional_empty_initiative_scope():
    parameter = inspect.signature(
        mind_mod.CoreMind.living_world_tick
    ).parameters["initiative_scope"]

    assert parameter.default == ""
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
