from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "scripts" / "run_holyrog_voice_server.py"
INSTALLER_PATH = ROOT / "scripts" / "install_holyrog_xtts_voice.ps1"
SECRET_MANAGER_PATH = ROOT / "scripts" / "manage_holyrog_voice_secret.py"


def _server_module():
    spec = importlib.util.spec_from_file_location("holyrog_voice_server_test", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _secret_manager_module():
    spec = importlib.util.spec_from_file_location("holyrog_voice_secret_test", SECRET_MANAGER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_holyrog_voice_server_supports_a_staged_secret_and_cuda_requirement(tmp_path, monkeypatch) -> None:
    module = _server_module()
    secret_path = tmp_path / "voice.secret"
    secret_path.write_text("v" * 32, encoding="utf-8")
    monkeypatch.setattr(module, "SECRET_FILE", str(secret_path))
    monkeypatch.delenv("ALPECCA_HOLYROG_VOICE_SECRET", raising=False)

    assert module._load_secret() == "v" * 32
    assert module.REQUIRE_CUDA is False
    source = SERVER_PATH.read_text(encoding="utf-8").lower()
    assert "alpecca_holyrog_voice_secret_file" in source
    assert "alpecca_holyrog_voice_require_cuda" in source
    assert "cuda is required for the dedicated holyrog xtts service" in source
    assert "model.to(\"cpu\")" in source
    assert "if require_cuda" in source


def test_holyrog_xtts_installer_is_separate_restricted_and_unattended() -> None:
    source = INSTALLER_PATH.read_text(encoding="utf-8").lower()

    assert "alpecca holyrog xtts voice" in source
    assert "manage_holyrog_voice_secret.py" in source
    assert "new-scheduledtasktrigger -atstartup" in source
    assert "-userid 'system'" in source
    assert "-logontype serviceaccount" in source
    assert "-restartcount 999" in source
    assert "acceptcoquilicense" in source
    assert "torch.cuda.is_available" in source
    assert "$env:tts_home = $modeldataroot" in source
    assert "$env:torch_force_no_weights_only_load = '1'" in source
    assert "tts_models--multilingual--multi-dataset--xtts_v2" in source
    assert "prepare-xttsmodelcache" in source
    assert "join-path $servicedatadir 'model-data'" in source
    assert "voice.secret" in source
    assert "new-netfirewallrule" in source
    assert "-localport 8790" in source
    assert "100.96.54.97" in source
    assert "-interfacealias 'tailscale'" in source
    assert "-remoteaddress $primarytailscaleaddress" in source
    for forbidden in ("run_full.py", "run_discord_bridge.py", "cloudflared", "continuity_lease"):
        assert forbidden not in source


def test_voice_secret_manager_uses_a_distinct_credential_record() -> None:
    source = SECRET_MANAGER_PATH.read_text(encoding="utf-8")

    assert 'TARGET = "Alpecca/Jason_HOLYROG/XTTSVoice"' in source
    assert "getpass.getpass" in source
    assert "--stage-secret-file" in source
    assert "cannot be stored in the repository" in source
    assert "without printing its value" in source
    assert "--derive-from-compute-worker" in source
    assert 'COMPUTE_WORKER_TARGET = "Alpecca/Jason_HOLYROG/ComputeWorker"' in source


def test_derived_voice_secret_is_domain_separated_and_never_echoes_parent() -> None:
    manager = _secret_manager_module()
    parent = "c" * 32

    first = manager._derive_voice_secret(parent)

    assert first == manager._derive_voice_secret(parent)
    assert first != parent
    assert len(first.encode("utf-8")) >= manager.MIN_SECRET_BYTES
    assert "+" not in first and "/" not in first and "=" not in first
