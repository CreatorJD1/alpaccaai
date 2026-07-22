"""Focused coverage for the standalone initiative control policy."""
from __future__ import annotations

import json

from alpecca.initiative_policy import InitiativePolicy


def _policy() -> InitiativePolicy:
    return InitiativePolicy(
        long_quiet_seconds=60.0,
        check_in_cooldown_seconds=30.0,
    )


def test_initiative_origin_does_not_create_an_event_epoch_or_self_loop():
    policy = _policy()
    observed = policy.observe_event("message-1", now=0.0)
    first = policy.reserve_follow_up(event_epoch=observed.epoch, now=1.0)

    assert observed.accepted is True
    assert first.granted is True
    assert policy.record_outcome(first.reservation_id, "passed", now=2.0).recorded

    echo = policy.observe_event(
        "initiative-output-1",
        now=3.0,
        origin="initiative",
    )
    repeat = policy.reserve_follow_up(event_epoch=observed.epoch, now=4.0)
    status = policy.snapshot(now=4.0)

    assert echo.accepted is False
    assert echo.reason == "initiative_origin"
    assert echo.epoch is None
    assert repeat.granted is False
    assert repeat.reason == "event_already_reserved"
    assert status.event_epoch == 1
    assert status.observed_event_count == 1


def test_each_observed_event_allows_exactly_one_normal_follow_up():
    policy = _policy()
    first_event = policy.observe_event("message-1", now=0.0)
    second_event = policy.observe_event("message-2", now=1.0)

    first = policy.reserve_for_event(
        event_epoch=first_event.epoch,
        event_id="message-1",
        now=2.0,
    )
    first_repeat = policy.reserve_for_event(
        event_epoch=first_event.epoch,
        event_id="message-1",
        now=3.0,
    )
    second = policy.reserve_for_event(
        event_epoch=second_event.epoch,
        event_id="message-2",
        now=4.0,
    )

    assert first.granted is True
    assert first_repeat.granted is False
    assert first_repeat.reason == "event_already_reserved"
    assert second.granted is True
    assert second.event_epoch == 2


def test_quiet_check_in_becomes_eligible_only_after_the_long_quiet_interval():
    policy = _policy()
    policy.observe_event("message-1", now=0.0)

    too_soon = policy.reserve_quiet_check_in(now=59.0)
    eligible = policy.reserve_quiet_check_in(now=60.0)
    status = policy.snapshot(now=60.0)

    assert too_soon.granted is False
    assert too_soon.reason == "quiet_period"
    assert too_soon.retry_at == 60.0
    assert eligible.granted is True
    assert status.quiet_for_seconds == 60.0
    assert status.last_check_in_at == 60.0
    assert status.check_in_eligible is False
    assert status.next_check_in_at == 90.0


def test_quiet_check_ins_cannot_repeat_rapidly_and_release_at_cooldown_boundary():
    policy = _policy()
    policy.observe_event("message-1", now=0.0)

    first = policy.reserve_check_in(now=60.0)
    rapid_repeat = policy.reserve_check_in(now=60.1)
    released = policy.reserve_check_in(now=90.0)

    assert first.granted is True
    assert rapid_repeat.granted is False
    assert rapid_repeat.reason == "check_in_cooldown"
    assert rapid_repeat.retry_at == 90.0
    assert released.granted is True


def test_pass_and_failure_outcomes_both_consume_their_reservations():
    policy = _policy()
    passed_event = policy.observe_event("message-pass", now=0.0)
    passed = policy.reserve_follow_up(event_epoch=passed_event.epoch, now=1.0)
    passed_outcome = policy.record_outcome(passed.reservation_id, "pass", now=2.0)

    failed_event = policy.observe_event("message-fail", now=3.0)
    failed = policy.reserve_follow_up(event_epoch=failed_event.epoch, now=4.0)
    failed_outcome = policy.record_outcome(failed.reservation_id, "failure", now=5.0)

    passed_repeat = policy.reserve_follow_up(event_epoch=passed_event.epoch, now=6.0)
    failed_repeat = policy.reserve_follow_up(event_epoch=failed_event.epoch, now=7.0)
    conflicting_retry = policy.record_outcome(failed.reservation_id, "passed", now=8.0)
    status = policy.snapshot(now=8.0)

    assert passed_outcome.recorded is True
    assert passed_outcome.outcome == "passed"
    assert failed_outcome.recorded is True
    assert failed_outcome.outcome == "failed"
    assert passed_repeat.reason == "event_already_reserved"
    assert failed_repeat.reason == "event_already_reserved"
    assert conflicting_retry.reason == "outcome_conflict"
    assert conflicting_retry.consumed is True
    assert status.passed_follow_up_count == 1
    assert status.failed_follow_up_count == 1


def test_json_safe_state_round_trip_preserves_epochs_consumption_and_cooldown():
    policy = _policy()
    event = policy.observe_event("message-1", now=0.0, scope="creator")
    follow_up = policy.reserve_follow_up(
        event_epoch=event.epoch,
        event_id=event.event_id,
        now=1.0,
        scope="creator",
    )
    check_in = policy.reserve_quiet_check_in(now=60.0, scope="creator")

    encoded = json.dumps(policy.to_dict())
    restored = InitiativePolicy.from_dict(json.loads(encoded))

    assert restored.to_dict() == policy.to_dict()

    follow_up_outcome = restored.record_outcome(
        follow_up.reservation_id,
        "passed",
        now=61.0,
    )
    check_in_outcome = restored.record_outcome(
        check_in.reservation_id,
        "failed",
        now=62.0,
    )
    repeated_event = restored.reserve_follow_up(
        event_epoch=event.epoch,
        now=63.0,
        scope="creator",
    )
    repeated_check_in = restored.reserve_quiet_check_in(now=63.0, scope="creator")

    assert follow_up_outcome.recorded is True
    assert check_in_outcome.recorded is True
    assert repeated_event.reason == "event_already_reserved"
    assert repeated_check_in.reason == "check_in_cooldown"
    assert repeated_check_in.retry_at == 90.0


def test_empty_scope_snapshot_also_round_trips_through_json_state():
    policy = _policy()
    policy.snapshot(now=0.0, scope="empty")

    restored = InitiativePolicy.from_dict(json.loads(json.dumps(policy.to_dict())))

    assert restored.snapshot(now=0.0, scope="empty").to_dict() == (
        policy.snapshot(now=0.0, scope="empty").to_dict()
    )
