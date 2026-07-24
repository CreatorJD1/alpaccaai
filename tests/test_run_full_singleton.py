"""Focused lifecycle coverage for the full-stack launcher singleton."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import threading
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUN_FULL = ROOT / "scripts" / "run_full.py"


def _load_launcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    monkeypatch.setenv("ALPECCA_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("run_full_singleton_test", RUN_FULL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Singleton lifecycle tests exercise the local process lock in isolation.
    # Production still discovers and acquires the cross-host continuity lease.
    monkeypatch.setattr(module, "client_from_env", lambda **_kwargs: None)
    return module


def test_full_launcher_acquires_and_releases_the_home_instance_lock() -> None:
    source = RUN_FULL.read_text(encoding="utf-8")
    main = source[source.index("def main() -> int:"):]

    assert '"alpecca.instance"' in source
    assert "LocalInstanceLock(_instance_lock_path())" in main
    acquire = main.index("lock.acquire()")
    lease = main.index("_start_continuity_guard()")
    run = main.index("return _run()")
    cleanup = main.index("finally:", run)
    stop_lease = main.index("continuity_guard.stop()", cleanup)
    release = main.index("lock.release()", stop_lease)

    assert acquire < lease < run < cleanup < stop_lease < release


def test_full_launcher_uses_validated_sqlite_snapshots_not_raw_file_copies() -> None:
    source = RUN_FULL.read_text(encoding="utf-8")

    assert "from alpecca.sqlite_backup import SQLiteBackupError, snapshot_database" in source
    assert "snapshot_database(" in source
    assert 'label="alpecca"' in source
    assert "retention=7" in source
    assert "shutil.copy2" not in source


def test_full_launcher_disables_rog_ssh_by_default_but_preserves_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ALPECCA_ROG_SSH_ENABLED", raising=False)
    launcher = _load_launcher(monkeypatch, tmp_path / "default")
    assert launcher.os.environ["ALPECCA_ROG_SSH_ENABLED"] == "0"

    monkeypatch.setenv("ALPECCA_ROG_SSH_ENABLED", "1")
    opted_in = _load_launcher(monkeypatch, tmp_path / "opted-in")
    assert opted_in.os.environ["ALPECCA_ROG_SSH_ENABLED"] == "1"


def test_full_launcher_prefers_magicdns_and_upgrades_only_legacy_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ALPECCA_ROG_WORKER_URL", raising=False)
    launcher = _load_launcher(monkeypatch, tmp_path / "default")
    assert launcher.os.environ["ALPECCA_ROG_WORKER_URL"] == (
        "https://jason-holyrog.tailda0108.ts.net:8788"
    )

    monkeypatch.setenv("ALPECCA_ROG_WORKER_URL", "https://Jason_HOLYROG:8788")
    migrated = _load_launcher(monkeypatch, tmp_path / "legacy")
    assert migrated.os.environ["ALPECCA_ROG_WORKER_URL"] == (
        "https://jason-holyrog.tailda0108.ts.net:8788"
    )

    custom_url = "https://127.0.0.1:9443"
    monkeypatch.setenv("ALPECCA_ROG_WORKER_URL", custom_url)
    custom = _load_launcher(monkeypatch, tmp_path / "custom")
    assert custom.os.environ["ALPECCA_ROG_WORKER_URL"] == custom_url


def test_second_full_launcher_never_enters_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    launcher = _load_launcher(monkeypatch, tmp_path)
    first_started = threading.Event()
    release_first = threading.Event()
    first_result: list[int] = []

    def hold_first_startup() -> int:
        first_started.set()
        assert release_first.wait(timeout=5)
        return 0

    launcher._run = hold_first_startup
    thread = threading.Thread(target=lambda: first_result.append(launcher.main()))
    thread.start()
    assert first_started.wait(timeout=5)

    def second_startup() -> int:
        raise AssertionError("a second launcher must fail before startup")

    launcher._run = second_startup
    assert launcher.main() == 1

    release_first.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert first_result == [0]


def test_full_launcher_releases_lock_after_normal_and_exceptional_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher = _load_launcher(monkeypatch, tmp_path)
    launcher._run = lambda: 0
    assert launcher.main() == 0

    def interrupted_startup() -> int:
        raise KeyboardInterrupt

    launcher._run = interrupted_startup
    with pytest.raises(KeyboardInterrupt):
        launcher.main()

    launcher._run = lambda: 0
    assert launcher.main() == 0
    assert (tmp_path / "alpecca.instance").exists()
