from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import threading


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy" / "hf-cloud-core" / "cloud_process_supervisor.py"
SPEC = importlib.util.spec_from_file_location("alpecca_cloud_process_supervisor", PATH)
assert SPEC and SPEC.loader
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)


class Process:
    def __init__(self, status: int | None, *, ignores_term: bool = False) -> None:
        self.status = status
        self.ignores_term = ignores_term
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_timeouts: list[float | None] = []

    def poll(self) -> int | None:
        return self.status

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self.ignores_term:
            self.status = -15

    def kill(self) -> None:
        self.kill_calls += 1
        self.status = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        if self.status is None:
            raise subprocess.TimeoutExpired("child", timeout)
        return self.status


def factory_for(*processes: Process):
    queue = list(processes)
    commands: list[list[str]] = []

    def factory(command):
        commands.append(list(command))
        return queue.pop(0)

    return factory, commands


def test_voice_exit_fails_container_and_stops_gateway() -> None:
    voice = Process(0)
    gateway = Process(None)
    factory, commands = factory_for(voice, gateway)

    result = supervisor.supervise(process_factory=factory, sleep=lambda _: None)

    assert result == 1
    assert gateway.terminate_calls == 1
    assert commands[0][-1].endswith("cloud_voice.py")
    assert commands[1][-1].endswith("cloud_entrypoint.py")


def test_gateway_exit_preserves_status_and_stops_voice() -> None:
    voice = Process(None)
    gateway = Process(7)
    factory, _commands = factory_for(voice, gateway)

    result = supervisor.supervise(process_factory=factory, sleep=lambda _: None)

    assert result == 7
    assert voice.terminate_calls == 1


def test_stop_child_escalates_after_bounded_grace() -> None:
    process = Process(None, ignores_term=True)

    supervisor.stop_child(process)

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_timeouts == [
        supervisor.STOP_TIMEOUT_SECONDS,
        supervisor.KILL_TIMEOUT_SECONDS,
    ]


def test_requested_shutdown_stops_both_children() -> None:
    voice = Process(None)
    gateway = Process(None)
    factory, _commands = factory_for(voice, gateway)
    stopped = threading.Event()
    stopped.set()

    result = supervisor.supervise(
        process_factory=factory,
        sleep=lambda _: None,
        stop_event=stopped,
    )

    assert result == 143
    assert voice.terminate_calls == gateway.terminate_calls == 1
