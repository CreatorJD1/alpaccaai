from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from alpecca import rog_remote_admin as remote


def _environment(tmp_path: Path) -> dict[str, str]:
    admin = tmp_path / "Alpecca" / "rog-admin"
    admin.mkdir(parents=True)
    (admin / "id_ed25519").write_text("private", encoding="ascii")
    (admin / "known_hosts").write_text("host key", encoding="ascii")
    return {
        "LOCALAPPDATA": str(tmp_path),
        remote.ENABLED_ENV: "1",
        remote.HOST_ENV: "Jason_HOLYROG",
        remote.USER_ENV: "Jason",
    }


def test_status_requires_explicit_enable_and_enrollment(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, "_ssh_executable", lambda: "ssh.exe")
    disabled = remote.status({"LOCALAPPDATA": str(tmp_path)})
    assert disabled["ready"] is False
    assert disabled["state"] == "setup-required"

    enabled = remote.status(_environment(tmp_path))
    assert enabled["ready"] is True
    assert enabled["house_access"] == "creator-unrestricted"
    assert enabled["discord_access"] == "creator-low-risk"


def test_execute_uses_argument_vector_and_redacts_command_from_audit(
    tmp_path, monkeypatch
):
    env = _environment(tmp_path)
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"ok\n", stderr=b"")

    monkeypatch.setattr(remote, "_ssh_executable", lambda: "ssh.exe")
    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    result = remote.execute(
        "Write-Output 'private command'",
        cwd=r"C:\work",
        timeout_seconds=10,
        request_id="request-12345678",
        environment=env,
    )
    assert result.exit_code == 0
    assert result.stdout == "ok\n"
    assert captured["kwargs"]["shell"] is False
    assert captured["argv"][0] == "ssh.exe"
    assert "Jason@Jason_HOLYROG" in captured["argv"]
    assert "private command" not in " ".join(captured["argv"])
    audit = (tmp_path / "Alpecca" / "rog-admin" / "audit.jsonl").read_text()
    assert "private command" not in audit
    assert "command_sha256" in audit


def test_discord_actions_are_fixed_and_unknown_action_is_rejected(tmp_path, monkeypatch):
    env = _environment(tmp_path)
    monkeypatch.setattr(remote, "_ssh_executable", lambda: "ssh.exe")
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=b"main\n", stderr=b""
        ),
    )
    assert remote.execute_low_risk("branch", environment=env).stdout == "main\n"
    with pytest.raises(remote.RemoteDevelopmentError, match="not allowed"):
        remote.execute_low_risk("remove files", environment=env)


def test_source_wires_creator_house_and_fixed_discord_paths():
    server = Path("server.py").read_text(encoding="utf-8")
    bridge = Path("alpecca/discord_bridge.py").read_text(encoding="utf-8")
    house = Path("apps/house-hq/src/main.ts").read_text(encoding="utf-8")
    assert '_require_creator_request(req)' in server
    assert '@app.post("/system/remote-development/execute")' in server
    assert '@app.post("/channel/discord/development")' in server
    assert 'allowed = "health|branch|log|resources"' in bridge
    assert 'data-system-id="development"' in house
    assert 'data-system-action="remote-execute"' in house
