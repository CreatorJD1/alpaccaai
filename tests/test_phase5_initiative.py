"""Fake-clock coverage for the pure Phase 5 initiative budget."""
from __future__ import annotations

import pytest

from alpecca.initiative import InitiativeBudget, InitiativePolicy


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def policy(**overrides) -> InitiativePolicy:
    values = {
        "min_relevance": 0.6,
        "cooldown_seconds": 10.0,
        "window_seconds": 60.0,
        "max_per_window": 3,
        "dedupe_seconds": 30.0,
        "activity_quiet_seconds": 5.0,
        "ignored_backoff_factor": 2.0,
        "max_ignored_backoff_seconds": 80.0,
    }
    values.update(overrides)
    return InitiativePolicy(**values)


def test_relevance_threshold_is_deterministic_and_does_not_consume_budget():
    clock = FakeClock()
    budget = InitiativeBudget(policy(), clock=clock)

    deferred = budget.decide(
        scope="creator-private", relevance=0.59, dedupe_key="observation-1"
    )
    allowed = budget.decide(
        scope="creator-private", relevance=0.6, dedupe_key="observation-1"
    )

    assert deferred.decision == "defer"
    assert deferred.reason == "low_relevance"
    assert deferred.retry_at is None
    assert deferred.window_used == 0
    assert allowed.allowed is True
    assert allowed.reason == "allowed"
    assert allowed.window_used == 1


def test_cooldown_and_dedupe_budgets_are_isolated_per_scope():
    clock = FakeClock()
    budget = InitiativeBudget(policy(), clock=clock)

    creator = budget.decide(
        scope="creator-private", relevance=0.9, dedupe_key="same-evidence"
    )
    guest = budget.decide(
        scope="guest-private", relevance=0.9, dedupe_key="same-evidence"
    )
    creator_duplicate = budget.decide(
        scope="creator-private", relevance=0.9, dedupe_key="same-evidence"
    )
    creator_cooldown = budget.decide(
        scope="creator-private", relevance=0.9, dedupe_key="new-evidence"
    )

    assert creator.allowed and guest.allowed
    assert creator_duplicate.reason == "duplicate"
    assert creator_duplicate.retry_after == 30.0
    assert creator_cooldown.reason == "cooldown"
    assert creator_cooldown.retry_after == 10.0
    assert budget.snapshot("creator-private")["window_used"] == 1
    assert budget.snapshot("guest-private")["window_used"] == 1


def test_dedupe_key_expires_at_exact_ttl_boundary():
    clock = FakeClock()
    budget = InitiativeBudget(
        policy(cooldown_seconds=0.0, dedupe_seconds=30.0), clock=clock
    )

    assert budget.decide(
        scope="scope-a", relevance=1.0, dedupe_key="fact-v1"
    ).allowed
    clock.advance(29.999)
    assert budget.decide(
        scope="scope-a", relevance=1.0, dedupe_key="fact-v1"
    ).reason == "duplicate"
    clock.advance(0.001)
    assert budget.decide(
        scope="scope-a", relevance=1.0, dedupe_key="fact-v1"
    ).allowed


def test_per_window_cap_releases_at_exact_window_boundary():
    clock = FakeClock()
    budget = InitiativeBudget(
        policy(cooldown_seconds=0.0, max_per_window=2, window_seconds=20.0),
        clock=clock,
    )

    assert budget.decide(scope="scope-a", relevance=1, dedupe_key="one").allowed
    clock.advance(1)
    assert budget.decide(scope="scope-a", relevance=1, dedupe_key="two").allowed
    capped = budget.decide(scope="scope-a", relevance=1, dedupe_key="three")
    assert capped.reason == "window_cap"
    assert capped.retry_at == 20.0

    clock.advance(19)
    released = budget.decide(scope="scope-a", relevance=1, dedupe_key="three")
    assert released.allowed
    assert released.window_used == 2


def test_explicit_user_activity_defers_until_quiet_and_resets_backoff():
    clock = FakeClock()
    budget = InitiativeBudget(policy(), clock=clock)

    first = budget.decide(
        scope="scope-a", relevance=1, dedupe_key="outreach-1", outreach=True
    )
    assert budget.mark_ignored(scope="scope-a", dedupe_key="outreach-1") is True
    assert budget.snapshot("scope-a")["ignored_streak"] == 1

    active = budget.decide(
        scope="scope-a",
        relevance=1,
        dedupe_key="outreach-2",
        user_active=True,
        outreach=True,
    )
    assert first.allowed
    assert active.reason == "user_active"
    assert active.retry_after == 5.0
    assert active.ignored_streak == 0

    clock.advance(4.999)
    quiet_wait = budget.decide(
        scope="scope-a", relevance=1, dedupe_key="outreach-2"
    )
    assert quiet_wait.reason == "activity_quiet_period"
    clock.advance(0.001)
    after_quiet = budget.decide(
        scope="scope-a", relevance=1, dedupe_key="outreach-2"
    )
    assert after_quiet.reason == "cooldown"
    assert after_quiet.retry_at == 10.0


def test_ignored_outreach_backoff_is_scoped_capped_and_idempotent():
    clock = FakeClock()
    budget = InitiativeBudget(policy(), clock=clock)

    assert budget.decide(
        scope="scope-a", relevance=1, dedupe_key="outreach-1", outreach=True
    ).allowed
    clock.advance(2)
    assert budget.mark_ignored(scope="scope-a", dedupe_key="outreach-1") is True
    assert budget.mark_ignored(scope="scope-a", dedupe_key="outreach-1") is False

    backed_off = budget.decide(
        scope="scope-a", relevance=1, dedupe_key="outreach-2", outreach=True
    )
    other_scope = budget.decide(
        scope="scope-b", relevance=1, dedupe_key="outreach-2", outreach=True
    )
    assert backed_off.reason == "cooldown"
    assert backed_off.retry_at == 22.0
    assert backed_off.ignored_streak == 1
    assert other_scope.allowed

    clock.advance(20)
    assert budget.decide(
        scope="scope-a", relevance=1, dedupe_key="outreach-2", outreach=True
    ).allowed
    clock.advance(1)
    assert budget.mark_ignored(scope="scope-a", dedupe_key="outreach-2") is True
    second_backoff = budget.decide(
        scope="scope-a", relevance=1, dedupe_key="outreach-3", outreach=True
    )
    assert second_backoff.retry_at == 63.0
    assert second_backoff.ignored_streak == 2


def test_non_outreach_candidates_do_not_create_or_receive_ignored_backoff():
    clock = FakeClock()
    budget = InitiativeBudget(policy(), clock=clock)

    internal = budget.decide(
        scope="scope-a", relevance=1, dedupe_key="routine-1", outreach=False
    )
    assert internal.allowed
    assert budget.mark_ignored(scope="scope-a", dedupe_key="routine-1") is False

    clock.advance(10)
    assert budget.decide(
        scope="scope-a", relevance=1, dedupe_key="routine-2", outreach=False
    ).allowed


def test_note_user_activity_is_per_scope_and_does_not_consume_a_slot():
    clock = FakeClock(100)
    budget = InitiativeBudget(policy(), clock=clock)

    budget.note_user_activity("scope-a")
    a = budget.decide(scope="scope-a", relevance=1, dedupe_key="a")
    b = budget.decide(scope="scope-b", relevance=1, dedupe_key="b")

    assert a.reason == "activity_quiet_period"
    assert b.allowed
    assert budget.snapshot("scope-a")["window_used"] == 0


def test_same_inputs_and_clock_produce_identical_decisions():
    clock_a = FakeClock(50)
    clock_b = FakeClock(50)
    budget_a = InitiativeBudget(policy(), clock=clock_a)
    budget_b = InitiativeBudget(policy(), clock=clock_b)

    first_a = budget_a.decide(scope="scope", relevance=0.8, dedupe_key="key")
    first_b = budget_b.decide(scope="scope", relevance=0.8, dedupe_key="key")
    clock_a.advance(3)
    clock_b.advance(3)
    second_a = budget_a.decide(scope="scope", relevance=0.8, dedupe_key="next")
    second_b = budget_b.decide(scope="scope", relevance=0.8, dedupe_key="next")

    assert first_a == first_b
    assert second_a == second_b


def test_invalid_policy_inputs_and_backwards_clock_fail_closed():
    with pytest.raises(ValueError):
        InitiativePolicy(min_relevance=1.1)
    with pytest.raises(ValueError):
        InitiativePolicy(max_per_window=0)

    clock = FakeClock(5)
    budget = InitiativeBudget(policy(), clock=clock)
    budget.snapshot("scope")
    clock.now = 4
    with pytest.raises(ValueError, match="backwards"):
        budget.snapshot("scope")
