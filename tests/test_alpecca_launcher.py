"""Regression coverage for the terminal-free desktop boot surface."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "apps" / "launcher" / "src" / "alpecca_launcher.py"


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
    assert defaults["ALPECCA_FAST_MODEL"] == "qwen3.5:4b"
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


def test_start_here_delegates_to_the_gui_without_a_terminal_prompt():
    source = (ROOT / "START_HERE.bat").read_text(encoding="utf-8")

    assert "apps\\launcher\\src\\run_launcher.bat" in source
    assert "set /p choice" not in source
    assert "cmd /k python scripts\\run_full.py" not in source
