from scripts.run_discord_bridge import _continuity_fence_matches


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
