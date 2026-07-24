"""Bounded process supervisor for the cloud standby gateway and optional voice."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, Protocol, Sequence


POLL_SECONDS = 0.25
STOP_TIMEOUT_SECONDS = 5.0
KILL_TIMEOUT_SECONDS = 2.0


class ChildProcess(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


def stop_child(process: ChildProcess) -> None:
    """Stop one child with a bounded graceful window and hard-kill fallback."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=STOP_TIMEOUT_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
    except OSError:
        return
    try:
        process.wait(timeout=KILL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return


def supervise(
    *,
    process_factory: Callable[[Sequence[str]], ChildProcess] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    stop_event: threading.Event | None = None,
) -> int:
    """Keep the sparse gateway alive even when optional voice is unavailable."""
    requested = stop_event or threading.Event()
    python = sys.executable
    root = Path(__file__).resolve().parent
    gateway = process_factory([python, str(root / "cloud_entrypoint.py")])
    voice: ChildProcess | None = None
    try:
        voice = process_factory([python, str(root / "cloud_voice.py")])
    except Exception:
        voice = None

    while not requested.is_set():
        gateway_status = gateway.poll()
        if gateway_status is not None:
            if voice is not None:
                stop_child(voice)
            return int(gateway_status)
        if voice is not None and voice.poll() is not None:
            voice = None
        sleep(POLL_SECONDS)

    stop_child(gateway)
    if voice is not None:
        stop_child(voice)
    return 143


def main() -> int:
    stop_event = threading.Event()

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        candidate = getattr(signal, name, None)
        if candidate is not None:
            signal.signal(candidate, request_stop)
    os.chdir(os.environ.get("ALPECCA_SOURCE_ROOT", "/opt/alpecca"))
    return supervise(stop_event=stop_event)


if __name__ == "__main__":
    raise SystemExit(main())
