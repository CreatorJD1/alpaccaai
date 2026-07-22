"""Regression coverage for the terminal-free desktop boot surface."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "apps" / "launcher" / "src" / "alpecca_launcher.py"
BUILD_LAUNCHER = ROOT / "apps" / "launcher" / "build_launcher.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("alpecca_launcher_test", LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gui_launch_defaults_keep_the_current_qwen35_model_and_preserve_overrides():
    launcher = _module()

    defaults = launcher.launch_environment({})
    custom = launcher.launch_environment({"ALPECCA_MODEL": "custom-local"})

    assert defaults["ALPECCA_MODEL"] == "qwen3.5:9b"
    assert defaults["ALPECCA_FAST_MODEL"] == "qwen3.5:9b"
    assert defaults["ALPECCA_NUM_CTX"] == "8192"
    assert custom["ALPECCA_MODEL"] == "custom-local"


def test_gui_starts_the_existing_singleton_full_stack_hidden(monkeypatch, tmp_path: Path):
    launcher = _module()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run_full.py").write_text("# fixture\n", encoding="utf-8")
    seen: dict[str, object] = {}

    class _Process:
        pass

    def fake_popen(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return _Process()

    monkeypatch.setattr(launcher, "_launcher_python", lambda: "pythonw.exe")
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)

    process = launcher._start_stack(tmp_path, environment={"ALPECCA_MODEL": "qwen3.5:9b"})

    assert isinstance(process, _Process)
    assert seen["command"] == ["pythonw.exe", "scripts\\run_full.py"]
    kwargs = seen["kwargs"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["creationflags"] & launcher.CREATE_NO_WINDOW
    assert kwargs["env"]["ALPECCA_MODEL"] == "qwen3.5:9b"
    assert (tmp_path / "data" / "logs" / "launcher_stack.log").is_file()


def test_gui_publishes_phone_endpoint_with_hidden_attach_only_relay(monkeypatch, tmp_path: Path):
    launcher = _module()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "share.py").write_text("# fixture\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(launcher, "_launcher_python", lambda: "pythonw.exe")
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)

    launcher._start_phone_relay(tmp_path)

    assert seen["command"] == ["pythonw.exe", "scripts\\share.py", "--tunnel"]
    assert seen["kwargs"]["creationflags"] & launcher.CREATE_NO_WINDOW
    assert (tmp_path / "data" / "logs" / "launcher_phone_relay.log").is_file()


def test_master_launcher_invokes_gui_source_directly_without_bat_delegation():
    source = (ROOT / "ALPECCA_LAUNCHER.bat").read_text(encoding="utf-8")

    assert 'pythonw "apps\\launcher\\src\\alpecca_launcher.py"' in source
    assert 'python "apps\\launcher\\src\\alpecca_launcher.py"' in source
    assert 'python "apps\\launcher\\build_launcher.py"' in source
    assert "ALPECCA_AUTOWAKE=1" in source
    for wrapper in (
        "START_HERE.bat",
        "SHARE_PHONE.bat",
        "START_DISCORD.bat",
        "RUN_VCS.bat",
        "ALPECCA_TOOLS.bat",
        "run_launcher.bat",
        "build_exe.bat",
    ):
        assert wrapper.lower() not in source.lower()


def test_master_launcher_preserves_cloud_first_discord_voice_auto_default():
    launcher = (ROOT / "ALPECCA_LAUNCHER.bat").read_text(encoding="utf-8")
    full_launcher = (ROOT / "scripts" / "run_full.py").read_text(encoding="utf-8")
    direct_launcher = (ROOT / "scripts" / "run_discord_bridge.py").read_text(
        encoding="utf-8"
    )

    assert "ALPECCA_DISCORD_TTS_ENGINE=f5" not in launcher
    assert 'set "ALPECCA_TTS_BACKEND=auto"' in launcher
    assert 'os.environ.setdefault("ALPECCA_DISCORD_TTS_ENGINE", "auto")' in full_launcher
    assert 'os.environ.setdefault("ALPECCA_DISCORD_TTS_ENGINE", "auto")' in direct_launcher


def test_python_build_driver_targets_single_file_no_console_executable():
    spec = importlib.util.spec_from_file_location("alpecca_launcher_build_test", BUILD_LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    command = module.pyinstaller_command("python-test")

    assert command[:3] == ["python-test", "-m", "PyInstaller"]
    assert "--onefile" in command
    assert "--noconsole" in command
    assert command[-1] == str(LAUNCHER)


def test_full_stack_pins_the_hosted_and_local_workload_split_with_overridable_defaults():
    source = (ROOT / "scripts" / "run_full.py").read_text(encoding="utf-8")

    expected_defaults = {
        "ALPECCA_MODEL": "qwen3.5:9b",
        "ALPECCA_FAST_MODEL": "qwen3.5:9b",
        "ALPECCA_CHAT_CLOUD_MODEL": "gemma4:cloud",
        "ALPECCA_CHAT_CLOUD_PAGED_MEMORY": "1",
        "ALPECCA_DEEP_BACKEND": "ollama-cloud",
        "ALPECCA_OLLAMA_CLOUD_MODEL": "gemma4:cloud",
        "ALPECCA_REFLECT_MODEL": "qwen3.5:9b",
        "ALPECCA_VISION_BACKEND": "local",
        "ALPECCA_VISION_CLOUD_MODEL": "gemma4:cloud",
        "ALPECCA_DISCORD_CREATOR_CLOUD_VISION": "1",
        "ALPECCA_VISION_CLOUD_TRANSPORT_ROUTE": "https://ollama.com/api/chat",
        "ALPECCA_VISION_CLOUD_DEPLOYMENT": "ollama-cloud",
        "ALPECCA_VISION_CLOUD_PROCESSING_LOCATION": "provider-managed",
        "ALPECCA_VISION_MODEL": "qwen3.5:4b",
        "ALPECCA_VISION_NUM_GPU": "99",
        "ALPECCA_VISION_TIMEOUT": "60",
    }
    for name, value in expected_defaults.items():
        assert f'os.environ.setdefault("{name}", "{value}")' in source


def test_full_stack_sidecars_use_no_window_background_flags():
    launcher = _module()
    source = (ROOT / "scripts" / "run_full.py").read_text(encoding="utf-8")

    assert "CREATE_NO_WINDOW" in source
    assert source.count('kwargs["creationflags"] = _background_creationflags()') >= 3
    assert launcher.CREATE_NO_WINDOW


def test_full_stack_offline_mode_is_local_only_and_does_not_wait_for_f5():
    source = (ROOT / "scripts" / "run_full.py").read_text(encoding="utf-8")

    assert 'os.environ["ALPECCA_CONTINUITY_OFFLINE_ISOLATED"] = "1"' in source
    assert 'os.environ["ALPECCA_REMOTE"] = "0"' in source
    assert 'os.environ["ALPECCA_CHAT_CLOUD_MODEL"] = ""' in source
    assert 'os.environ["ALPECCA_MINDSCAPE_VAULT"] = "0"' in source
    assert 'os.environ["ALPECCA_DISCORD_VOICE"] = "0"' in source
    assert "if _lease_transport_unavailable(exc):\n                raise" in source
    assert "for _ in range(45)" not in source

    mind_source = (ROOT / "alpecca" / "mind.py").read_text(encoding="utf-8")
    assert "cloud_history_eligible" in mind_source
    assert 'get("private_context")' in mind_source


def test_gui_phone_access_opens_an_actual_tunnel():
    source = LAUNCHER.read_text(encoding="utf-8")

    assert '"scripts\\\\share.py", "--tunnel"' in source


def test_gui_wakes_cloud_standby_and_repairs_an_absent_discord_bridge():
    source = LAUNCHER.read_text(encoding="utf-8")

    assert '"scripts\\\\wake_cloud_standby.py"' in source
    assert '"scripts\\\\run_discord_bridge.py"' in source
    assert "DISCORD_BRIDGE_LOCK_PORT" in source
    assert "_loopback_port_open" in source


def test_full_stack_wakes_the_passive_cloud_standby_without_promoting_it():
    source = (ROOT / "scripts" / "run_full.py").read_text(encoding="utf-8")

    assert 'os.environ.setdefault("ALPECCA_CLOUD_STANDBY_URL", "https://creatorjd-alpecca-survival-core.hf.space")' in source
    assert "def _wake_cloud_standby()" in source
    assert "_wake_cloud_standby()" in source
