"""Cross-process coverage for the local CoreMind single-instance lock."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from alpecca.instance import (
    InstanceAlreadyRunning,
    InstanceLockRecoveryError,
    LocalInstanceLock,
)


ROOT = Path(__file__).resolve().parents[1]


def _start_lock_holder(path: Path) -> subprocess.Popen[str]:
    code = """
from alpecca.instance import LocalInstanceLock
import sys
import time

with LocalInstanceLock(sys.argv[1]):
    print('held', flush=True)
    time.sleep(30)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "held"
    return process


def test_live_cross_process_owner_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "coremind.lock"
    holder = _start_lock_holder(path)
    try:
        with pytest.raises(InstanceAlreadyRunning):
            LocalInstanceLock(path).acquire()
    finally:
        holder.terminate()
        holder.wait(timeout=10)


def test_release_keeps_lock_path_and_allows_a_new_owner(tmp_path: Path) -> None:
    path = tmp_path / "coremind.lock"
    first = LocalInstanceLock(path).acquire()
    assert first.is_held
    first.release()

    assert path.exists()
    with LocalInstanceLock(path) as second:
        assert second.is_held
        owner = second.read_owner()
        assert owner is not None
        assert owner["pid"] == process_id()


def test_same_process_second_owner_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "coremind.lock"
    first = LocalInstanceLock(path).acquire()
    try:
        with pytest.raises(InstanceAlreadyRunning):
            LocalInstanceLock(path).acquire()
    finally:
        first.release()


def test_dead_owner_metadata_is_recovered_only_after_process_exit(tmp_path: Path) -> None:
    path = tmp_path / "coremind.lock"
    holder = _start_lock_holder(path)
    holder.kill()
    holder.wait(timeout=10)

    with LocalInstanceLock(path) as recovered:
        assert recovered.is_held
        owner = recovered.read_owner()
        assert owner is not None
        assert owner["pid"] == process_id()


def test_unverified_live_stale_metadata_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "coremind.lock"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "pid": process_id(),
                "started_at": time.time(),
                "hostname": "test-host",
            }
        ),
        encoding="utf-8",
    )

    with LocalInstanceLock(path):
        pass

    other_live_pid = _start_sleeping_process()
    try:
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "pid": other_live_pid.pid,
                    "started_at": time.time(),
                    "hostname": "test-host",
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(InstanceLockRecoveryError):
            LocalInstanceLock(path).acquire()
    finally:
        other_live_pid.terminate()
        other_live_pid.wait(timeout=10)


def _start_sleeping_process() -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=ROOT,
        text=True,
    )


def process_id() -> int:
    import os

    return os.getpid()
