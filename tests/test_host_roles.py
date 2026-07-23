from __future__ import annotations

import pytest
from pathlib import Path

from alpecca import host_roles


def test_jason_holyrog_is_permanently_compute_only() -> None:
    assert host_roles.is_compute_only_host("JASON_HOLYROG") is True
    assert host_roles.is_compute_only_host("jason_holyrog") is True
    with pytest.raises(host_roles.ComputeOnlyHostError, match="compute-worker"):
        host_roles.require_primary_runtime_host("Jason_HOLYROG")


def test_primary_laptop_is_not_compute_only() -> None:
    assert host_roles.is_compute_only_host("RygenART") is False
    host_roles.require_primary_runtime_host("RygenART")


def test_every_authoritative_entrypoint_enforces_the_host_role() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "scripts/run_full.py",
        "scripts/run_discord_bridge.py",
        "server.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "require_primary_runtime_host" in source
