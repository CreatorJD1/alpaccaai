from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def _forbid(label: str):
    def fail(*_args, **_kwargs):
        raise AssertionError(f"read-only /soul called {label}")

    return fail


def test_soul_get_returns_only_cached_status_without_side_effects(monkeypatch):
    monkeypatch.setenv("ALPECCA_CONTINUITY_OFFLINE_ISOLATED", "true")
    from fastapi.testclient import TestClient
    import server

    cached = {
        "schema": "alpecca.soul-runtime-decision.v1",
        "roles": ("Feeler", "Expressor", "Carer", "Doer", "Wanderer", "Reflector", "Improver"),
        "scores": (0.2, 0.1, 0.4, 0.8, 0.3, 0.5, 0.6),
        "active": (1, 0, 1, 1, 0, 1, 1),
        "deterministic_role": "Doer",
        "selected_role": "Doer",
        "callback_invoked": False,
        "outcome": "not_eligible",
        "advisory_only": True,
    }
    monkeypatch.setattr(server.mind, "_last_soul_runtime", copy.deepcopy(cached))
    monkeypatch.setattr(server.mind, "soul_state", _forbid("soul_state"))
    monkeypatch.setattr(
        server.mind, "soul_perspective_evidence", _forbid("fresh perspective evidence")
    )
    monkeypatch.setattr(server.mind, "_soul_snapshot", _forbid("a fresh snapshot"))
    monkeypatch.setattr(
        server.mind, "_soul_textual_deliberator", _forbid("local inference")
    )
    monkeypatch.setattr(server.mind.llm, "generate", _forbid("model generation"))
    monkeypatch.setattr(
        server.cognition_mod, "record_observation", _forbid("cognition observation")
    )

    before_runtime = copy.deepcopy(server.mind._last_soul_runtime)
    before_location = server.mind._location
    before_state = server.mind.state.as_dict()

    response = TestClient(server.app).get(
        "/soul",
        headers={server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["read_only"] is True
    assert payload["fresh_deliberation"] is False
    assert payload["state"] == "cached"
    assert payload["focus"] == {
        "subagent": "Doer",
        "name": "Doer",
        "category": "actions",
        "kind": "reason",
        "reason": "Cached from the latest completed Soul arbitration.",
        "source": "cached_runtime",
    }
    assert len(payload["slate"]) == 7
    assert payload["soul_runtime"]["selected_role"] == "Doer"
    assert payload["soul_runtime"]["callback_invoked"] is False
    assert server.mind._last_soul_runtime == before_runtime
    assert server.mind._location == before_location
    assert server.mind.state.as_dict() == before_state


def _import_server(
    *,
    epoch: str | None,
    offline: str | None,
    lease_id: str | None = None,
    holder: str | None = None,
    same_process_launcher: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ALPECCA_CONTINUITY_LEASE_URL"] = "https://lease.example.test"
    if epoch is None:
        env.pop("ALPECCA_CONTINUITY_FENCING_EPOCH", None)
    else:
        env["ALPECCA_CONTINUITY_FENCING_EPOCH"] = epoch
    if offline is None:
        env.pop("ALPECCA_CONTINUITY_OFFLINE_ISOLATED", None)
    else:
        env["ALPECCA_CONTINUITY_OFFLINE_ISOLATED"] = offline
    for name, value in (
        ("ALPECCA_CONTINUITY_LEASE_ID", lease_id),
        ("ALPECCA_CONTINUITY_LEASE_HOLDER", holder),
    ):
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    env["ALPECCA_CONTINUITY_LAUNCHER_PID"] = "999999"
    command = "import server; print('SERVER_IMPORTED')"
    if same_process_launcher:
        command = (
            "import os; "
            "os.environ['ALPECCA_CONTINUITY_LAUNCHER_PID']=str(os.getpid()); "
            "import server; print('SERVER_IMPORTED')"
        )
    return subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_server_import_fails_closed_without_inherited_continuity_fence():
    result = _import_server(epoch=None, offline=None)

    assert result.returncode != 0
    assert "SERVER_IMPORTED" not in result.stdout
    assert "no valid inherited lease fence" in result.stderr
    assert "scripts/run_full.py" in result.stderr


def test_server_import_rejects_epoch_without_complete_inherited_tuple():
    result = _import_server(epoch="17", offline=None)

    assert result.returncode != 0
    assert "SERVER_IMPORTED" not in result.stdout
    assert "no valid inherited lease fence" in result.stderr


def test_server_import_accepts_complete_same_process_continuity_fence():
    result = _import_server(
        epoch="17",
        offline=None,
        lease_id="lease-current-17",
        holder="local-primary:test-host",
        same_process_launcher=True,
    )

    assert result.returncode == 0, result.stderr
    assert "SERVER_IMPORTED" in result.stdout


def test_server_import_rejects_stale_launcher_process_tuple():
    result = _import_server(
        epoch="17",
        offline=None,
        lease_id="lease-stale-17",
        holder="local-primary:test-host",
        same_process_launcher=False,
    )

    assert result.returncode != 0
    assert "SERVER_IMPORTED" not in result.stdout
    assert "no valid inherited lease fence" in result.stderr


def test_server_import_accepts_only_explicit_offline_isolation_without_fence():
    accepted = _import_server(epoch=None, offline="true")
    rejected = _import_server(epoch=None, offline="false")

    assert accepted.returncode == 0, accepted.stderr
    assert "SERVER_IMPORTED" in accepted.stdout
    assert rejected.returncode != 0
    assert "no valid inherited lease fence" in rejected.stderr
