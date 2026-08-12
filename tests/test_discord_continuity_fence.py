from scripts.run_discord_bridge import (
    _continuity_fence_matches,
    _watch_continuity_fence,
)


def _status(**overrides):
    active = {
        "holderNodeId": "local-primary:laptop",
        "leaseId": "lease-7",
        "fencingEpoch": 7,
        "ttlRemainingSeconds": 20,
    }
    active.update(overrides)
    return {"ok": True, "activeLease": active}


def test_discord_bridge_requires_the_exact_active_fence():
    assert _continuity_fence_matches(
        _status(),
        holder_node_id="local-primary:laptop",
        lease_id="lease-7",
        fencing_epoch=7,
    )
    assert not _continuity_fence_matches(
        _status(fencingEpoch=8),
        holder_node_id="local-primary:laptop",
        lease_id="lease-7",
        fencing_epoch=7,
    )
    assert not _continuity_fence_matches(
        _status(ttlRemainingSeconds=2),
        holder_node_id="local-primary:laptop",
        lease_id="lease-7",
        fencing_epoch=7,
    )


class _ImmediateWait:
    def wait(self, _seconds: float) -> bool:
        return False


class _StatusClient:
    def __init__(self, statuses):
        self._statuses = iter(statuses)

    def status(self):
        return next(self._statuses)


def test_discord_watchdog_terminates_after_sustained_fence_mismatch():
    exits = []
    client = _StatusClient([
        _status(fencingEpoch=8),
        _status(fencingEpoch=8),
    ])

    _watch_continuity_fence(
        client,
        holder_node_id="local-primary:laptop",
        lease_id="lease-7",
        fencing_epoch=7,
        tolerated_misses=1,
        stop=_ImmediateWait(),
        on_loss=lambda: exits.append(75),
    )

    assert exits == [75]


def test_discord_watchdog_resets_transient_miss_before_failing_closed():
    exits = []
    client = _StatusClient([
        _status(fencingEpoch=8),
        _status(),
        _status(fencingEpoch=8),
        _status(fencingEpoch=8),
    ])

    _watch_continuity_fence(
        client,
        holder_node_id="local-primary:laptop",
        lease_id="lease-7",
        fencing_epoch=7,
        tolerated_misses=1,
        stop=_ImmediateWait(),
        on_loss=lambda: exits.append(75),
    )

    assert exits == [75]
