from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy" / "hf-cloud-core" / "cloud_entrypoint.py"
SPEC = importlib.util.spec_from_file_location("alpecca_hf_cloud_core", PATH)
assert SPEC and SPEC.loader
cloud = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cloud)
supervisor_module = cloud.supervisor


def test_cloud_core_uses_hosted_qwen35_and_keeps_private_capabilities_off():
    env = {"PORT": "7860"}
    cloud.configure_environment(env)
    assert env["ALPECCA_LLM_BACKEND"] == "hf"
    assert env["ALPECCA_HF_MODEL"] == "Qwen/Qwen3.5-9B"
    assert env["ALPECCA_MODEL"] == "qwen3.5:9b"
    assert ("qwen3" + ":8b") not in repr(env)
    assert env["ALPECCA_REFLECT_THINK"] == "0"
    assert env["ALPECCA_COMPUTER_USE"] == "0"
    assert env["ALPECCA_DISCORD"] == "0"
    assert env["ALPECCA_MINDSCAPE_VAULT"] == "0"
    assert env["ALPECCA_CONTINUITY_NODE_ID"].startswith("cloud-standby:")


def test_cloud_core_requires_every_private_recovery_input():
    env = {}
    cloud.configure_environment(env)
    missing = cloud.validate_configuration(env)
    assert set(cloud.REQUIRED_SECRETS).issubset(missing)
    assert set(cloud.REQUIRED_URLS).issubset(missing)


def test_cloud_core_requires_explicit_enable_switch():
    assert cloud.cloud_core_enabled({}) is False
    assert cloud.cloud_core_enabled({"ALPECCA_CLOUD_CORE_ENABLED": "0"}) is False
    assert cloud.cloud_core_enabled({"ALPECCA_CLOUD_CORE_ENABLED": "true"}) is True


def test_standby_promotes_only_after_positive_empty_authority_state():
    assert cloud.promotion_eligible({}) is False
    assert cloud.promotion_eligible({"ok": False}) is False
    assert cloud.promotion_eligible({
        "ok": True,
        "activeLeaseCount": 1,
        "activeLease": {"leaseId": "local"},
        "localPrimaryPreferred": True,
    }) is False
    assert cloud.promotion_eligible({
        "ok": True,
        "activeLeaseCount": 0,
        "activeLease": None,
        "localPrimaryPreferred": True,
    }) is False
    assert cloud.promotion_eligible({
        "ok": True,
        "activeLeaseCount": 0,
        "activeLease": None,
        "localPrimaryPreferred": False,
    }) is True


def test_standby_health_identity_is_not_coremind_and_releases_its_port():
    server = cloud.StandbyServer(0)
    port = server.port
    server.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz",
            timeout=2,
        ) as response:
            payload = json.loads(response.read())
        assert payload == {
            "service": "alpecca-continuity-standby",
            "version": 1,
            "state": "waiting-for-singleton-lease",
            "coreMind": False,
        }
    finally:
        server.stop()

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_supervisor_once_reports_clean_exit_vs_container_shutdown(monkeypatch):
    class FakeSupervisor:
        def __init__(self, *, vrm_installer):
            self.vrm_installer = vrm_installer
            self.shutdown_requested = False

        def install_signal_handlers(self):
            return None

        def run(self):
            return 0

    fake = FakeSupervisor(vrm_installer=None)
    monkeypatch.setattr(
        supervisor_module,
        "CloudCoreSupervisor",
        lambda *, vrm_installer: fake,
    )
    assert supervisor_module.run_supervisor_once(vrm_installer=None) == (0, False)
    fake.shutdown_requested = True
    assert supervisor_module.run_supervisor_once(vrm_installer=None) == (0, True)


class _Response:
    def __init__(self, data: bytes):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int):
        return self.data[:limit]


def test_vrm_install_rejects_a_body_that_does_not_match_locked_hash(tmp_path):
    def opener(_request, timeout):
        assert timeout == 90
        return _Response(b"not the locked V.4 body")

    try:
        cloud.install_vrm(tmp_path, opener=opener)
    except RuntimeError as exc:
        assert "integrity" in str(exc)
    else:
        raise AssertionError("invalid VRM was accepted")
    assert not (tmp_path / "avatar" / "vrm" / "alpecca.vrm").exists()


def test_cloud_space_build_is_pinned_to_current_branch_and_no_old_qwen():
    dockerfile = (PATH.parent / "Dockerfile").read_text(encoding="utf-8")
    readme = (PATH.parent / "README.md").read_text(encoding="utf-8")
    assert "codex/voice-session-audio-normalization" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=source /opt/runtime /opt/alpecca" in dockerfile
    assert "COPY --from=source /opt/alpecca /opt/alpecca" not in dockerfile
    for excluded in ("./.git", "./deploy", "./docs", "./scripts", "./tests"):
        assert f"--exclude='{excluded}'" in dockerfile
    assert "Qwen/Qwen3.5-9B" in readme
    assert ("qwen3" + ":8b") not in dockerfile + readme


_RESTORED_BYTES = b"verified sqlite fixture"


def _environment() -> dict[str, str]:
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(_RESTORED_BYTES).hexdigest()
    approval = {
        "approvalId": "restore-test-42",
        "purpose": "stage-passive-restore",
        "creatorPrincipal": "CreatorJD",
        "snapshotDigest": f"sha256:{digest}",
        "leaseEpoch": 42,
        "issuedAt": (now - timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        "expiresAt": (now + timedelta(seconds=240)).isoformat().replace("+00:00", "Z"),
        "oneUse": True,
        "verification": {
            "status": "verified",
            "verifier": "external-creator-verifier",
            "evidenceId": "creator-check-test-42",
        },
    }
    return {
        "SPACE_HOST": "creatorjd-alpecca-core.hf.space",
        "SPACE_ID": "CreatorJD/alpecca-core",
        "HF_TOKEN": "hf_test_token",
        "ALPECCA_MINDSCAPE_VAULT_URL": "https://vault.example.test",
        "ALPECCA_MINDSCAPE_VAULT_TOKEN": "v" * 32,
        "ALPECCA_MINDSCAPE_VAULT_KEY": "a" * 43,
        "ALPECCA_CONTINUITY_LEASE_URL": "https://lease.example.test",
        "ALPECCA_CONTINUITY_LEASE_TOKEN": "l" * 32,
        "ALPECCA_AUTH_SECRET": "s" * 48,
        "ALPECCA_CREATOR_PASSWORD": "creator-password",
        "ALPECCA_CLOUD_RESTORE_APPROVAL": json.dumps(approval),
    }


class _Vault:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    def load_or_create_encryption_key(self, environ):
        assert environ["ALPECCA_MINDSCAPE_VAULT_KEY"]
        return b"k" * 32, "environment"

    def load_or_create_transport_token(self, environ):
        return environ["ALPECCA_MINDSCAPE_VAULT_TOKEN"], "environment"

    def fetch_latest_archive(self, url, token, key, destination, *, timeout):
        self.events.append("restore")
        assert url == "https://vault.example.test"
        assert token == "v" * 32
        assert key == b"k" * 32
        assert timeout == 30.0
        if self.fail:
            return {"ok": False, "status": "fetch_failed"}
        destination.write_bytes(_RESTORED_BYTES)
        return {
            "ok": True,
            "status": "recovered",
            "path": str(destination),
            "sequence": 41,
            "created_at": "2026-07-15T20:00:00Z",
        }


class _Journal:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def fetch_and_merge(self, url, token, key, *, db_path, timeout):
        self.events.append("merge")
        assert url == "https://vault.example.test"
        assert token == "v" * 32
        assert key == b"k" * 32
        assert db_path.read_bytes() == _RESTORED_BYTES
        assert timeout == 12.0
        return {"ok": True, "status": "merged", "merged": 2, "duplicates": 1}


class _LeaseClient:
    def __init__(self, role: str, events: list[str]) -> None:
        self.role = role
        self.events = events

    def publish_endpoint(self, grant, endpoint):
        self.events.append("publish")
        assert grant.fencing_epoch == 42
        assert endpoint == "https://creatorjd-alpecca-core.hf.space"
        return {"ok": True}


class _Guard:
    def __init__(self, events, client, *, endpoint, on_loss, active_values=None):
        self.events = events
        self.client = client
        self.endpoint = endpoint
        self.on_loss = on_loss
        self.active_values = list(active_values or [True])

    @property
    def active(self):
        if len(self.active_values) > 1:
            return self.active_values.pop(0)
        return self.active_values[0]

    def start(self):
        self.events.append("acquire")
        assert self.client.role == "cloud-standby"
        assert self.endpoint == ""
        return SimpleNamespace(
            lease_id="lease-42",
            fencing_epoch=42,
            holder="cloud-standby:test",
        )

    def stop(self):
        self.events.append("release")


class _Child:
    def __init__(self, *, running: bool = False) -> None:
        self.exit_code = None if running else 0
        self.killed = False
        self.terminated = False

    def poll(self):
        return self.exit_code

    def kill(self):
        self.killed = True
        self.exit_code = -9

    def terminate(self):
        self.terminated = True
        self.exit_code = 0

    def wait(self, *, timeout):
        assert timeout > 0
        return self.exit_code


def _runtime_home(tmp_path: Path):
    def create(_environ):
        path = tmp_path / "runtime"
        path.mkdir()
        return path

    return create


def test_supervisor_restores_approves_publishes_then_starts(tmp_path):
    events: list[str] = []
    captured: dict[str, object] = {}

    def install_vrm(home: Path) -> Path:
        events.append("vrm")
        path = home / "avatar" / "vrm" / "alpecca.vrm"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"locked-v4")
        return path

    def client_factory(*, role):
        events.append("client")
        return _LeaseClient(role, events)

    def guard_factory(client, *, renew_seconds, endpoint, on_loss):
        assert renew_seconds == 10.0
        return _Guard(events, client, endpoint=endpoint, on_loss=on_loss)

    def process_factory(command, *, cwd, env, start_new_session):
        events.append("spawn")
        captured.update(command=command, cwd=cwd, env=env, session=start_new_session)
        return _Child()

    core = supervisor_module.CloudCoreSupervisor(
        environ=_environment(),
        vault_module=_Vault(events),
        journal_module=_Journal(events),
        lease_client_factory=client_factory,
        lease_guard_factory=guard_factory,
        process_factory=process_factory,
        runtime_home_factory=_runtime_home(tmp_path),
        vrm_installer=install_vrm,
        sleep=lambda _seconds: None,
    )

    assert core.run() == 0
    assert events == ["vrm", "restore", "merge", "client", "acquire", "publish", "spawn", "release"]
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert child_env["ALPECCA_LLM_BACKEND"] == "hf"
    assert child_env["ALPECCA_HF_MODEL"] == "Qwen/Qwen3.5-9B"
    assert child_env["ALPECCA_MODEL"] == "qwen3.5:9b"
    assert child_env["ALPECCA_REFLECT_THINK"] == "0"
    assert child_env["ALPECCA_MINDSCAPE_VAULT"] == "0"
    assert child_env["ALPECCA_CONTINUITY_FENCING_EPOCH"] == "42"
    assert "ALPECCA_CLOUD_RESTORE_APPROVAL" not in child_env
    assert captured["session"] is True
    assert not (tmp_path / "runtime").exists()


def test_supervisor_can_use_explicit_automatic_failover_policy(tmp_path):
    events: list[str] = []
    captured: dict[str, object] = {}
    environ = _environment()
    del environ["ALPECCA_CLOUD_RESTORE_APPROVAL"]
    environ["ALPECCA_CLOUD_AUTO_FAILOVER"] = "1"

    def process_factory(command, *, cwd, env, start_new_session):
        events.append("spawn")
        captured.update(command=command, cwd=cwd, env=env, session=start_new_session)
        return _Child()

    core = supervisor_module.CloudCoreSupervisor(
        environ=environ,
        vault_module=_Vault(events),
        journal_module=_Journal(events),
        lease_client_factory=lambda *, role: _LeaseClient(role, events),
        lease_guard_factory=lambda client, **kwargs: _Guard(
            events,
            client,
            endpoint=kwargs["endpoint"],
            on_loss=kwargs["on_loss"],
        ),
        process_factory=process_factory,
        runtime_home_factory=_runtime_home(tmp_path),
        sleep=lambda _seconds: None,
    )

    assert core.run() == 0
    assert events == ["restore", "merge", "acquire", "publish", "spawn", "release"]
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert child_env["ALPECCA_RESTORE_APPROVAL_ID"] == "deployment-auto-failover-v1"


def test_lease_loss_hard_kills_core_without_shutdown_hooks(tmp_path):
    events: list[str] = []
    child = _Child(running=True)

    def guard_factory(client, *, renew_seconds, endpoint, on_loss):
        return _Guard(
            events,
            client,
            endpoint=endpoint,
            on_loss=on_loss,
            active_values=[True, True, True, False],
        )

    core = supervisor_module.CloudCoreSupervisor(
        environ=_environment(),
        vault_module=_Vault(events),
        journal_module=_Journal(events),
        lease_client_factory=lambda *, role: _LeaseClient(role, events),
        lease_guard_factory=guard_factory,
        process_factory=lambda *_args, **_kwargs: child,
        runtime_home_factory=_runtime_home(tmp_path),
        sleep=lambda _seconds: None,
    )

    assert core.run() == supervisor_module.LEASE_LOST_EXIT
    assert child.killed is True
    assert child.terminated is False
    assert events == ["restore", "merge", "acquire", "publish", "release"]


def test_restore_or_approval_failure_never_starts_core(tmp_path):
    events: list[str] = []
    core = supervisor_module.CloudCoreSupervisor(
        environ=_environment(),
        vault_module=_Vault(events, fail=True),
        journal_module=_Journal(events),
        lease_client_factory=lambda **_kwargs: pytest.fail("lease unexpectedly requested"),
        process_factory=lambda *_args, **_kwargs: pytest.fail("child unexpectedly started"),
        runtime_home_factory=_runtime_home(tmp_path),
    )
    with pytest.raises(supervisor_module.CloudCoreStartupError, match="vault_restore_failed"):
        core.run()
    assert events == ["restore"]

    events.clear()
    environ = _environment()
    del environ["ALPECCA_CLOUD_RESTORE_APPROVAL"]
    core = supervisor_module.CloudCoreSupervisor(
        environ=environ,
        vault_module=_Vault(events),
        journal_module=_Journal(events),
        lease_client_factory=lambda **_kwargs: pytest.fail("lease unexpectedly requested"),
        process_factory=lambda *_args, **_kwargs: pytest.fail("child unexpectedly started"),
        runtime_home_factory=_runtime_home(tmp_path),
    )
    with pytest.raises(
        supervisor_module.CloudCoreStartupError,
        match="explicit_restore_approval_required",
    ):
        core.run()
    assert events == ["restore", "merge"]


def test_stale_approval_epoch_releases_without_publish_or_start(tmp_path):
    events: list[str] = []
    environ = _environment()
    approval = json.loads(environ["ALPECCA_CLOUD_RESTORE_APPROVAL"])
    approval["leaseEpoch"] = 41
    environ["ALPECCA_CLOUD_RESTORE_APPROVAL"] = json.dumps(approval)
    core = supervisor_module.CloudCoreSupervisor(
        environ=environ,
        vault_module=_Vault(events),
        journal_module=_Journal(events),
        lease_client_factory=lambda *, role: _LeaseClient(role, events),
        lease_guard_factory=lambda client, **kwargs: _Guard(
            events,
            client,
            endpoint=kwargs["endpoint"],
            on_loss=kwargs["on_loss"],
        ),
        process_factory=lambda *_args, **_kwargs: pytest.fail("child unexpectedly started"),
        runtime_home_factory=_runtime_home(tmp_path),
    )
    with pytest.raises(
        supervisor_module.CloudCoreStartupError,
        match="restore_approval_lease_epoch_mismatch",
    ):
        core.run()
    assert events == ["restore", "merge", "acquire", "release"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://creatorjd-alpecca-core.hf.space",
        "https://creatorjd-alpecca-core.hf.space/path",
        "https://creatorjd-alpecca-core.hf.space?token=secret",
    ],
)
def test_endpoint_publication_accepts_only_an_https_origin(endpoint):
    with pytest.raises(supervisor_module.CloudCoreStartupError, match="public_endpoint_invalid"):
        supervisor_module.resolve_public_endpoint({"ALPECCA_PUBLIC_ENDPOINT": endpoint})


def test_owned_scaffold_and_mind_keep_the_non_thinking_contract():
    readme = (PATH.parent / "README.md").read_text(encoding="utf-8")
    dockerfile = (PATH.parent / "Dockerfile").read_text(encoding="utf-8")
    start = (PATH.parent / "start.sh").read_text(encoding="utf-8")
    app_source = (PATH.parent / "app.py").read_text(encoding="utf-8")
    mind = (ROOT / "alpecca" / "mind.py").read_text(encoding="utf-8")
    retired = "qwen3" + ":8b"

    assert retired not in (readme + dockerfile + start + app_source).lower()
    assert "Qwen/Qwen3.5-9B" in dockerfile
    assert "ALPECCA_REFLECT_THINK=0" in dockerfile
    assert "cloud-standby" in start
    assert "sleep" in readme.lower()
    assert "not an always-on" in readme.lower()
    assert "snapshotDigest" in readme
    assert '"chat_template_kwargs": {"enable_thinking": False}' in mind
