"""Single-instance helpers for the local Alpecca server.

Cloudflare links and desktop windows should point at the same local mind. These
helpers let launchers detect an already-awake server before importing server.py,
because importing server.py constructs CoreMind.
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any, BinaryIO
import urllib.error
import urllib.request


HEALTHZ_PATH = "/healthz"
HEALTHZ_SERVICE = "alpecca"
HEALTHZ_VERSION = 1
MAX_HEALTHZ_BYTES = 512
_LOCK_METADATA_VERSION = 1
_MAX_LOCK_METADATA_BYTES = 4096
_PROCESS_LOCK_PATHS: set[str] = set()
_PROCESS_LOCK_PATHS_GUARD = threading.Lock()


class InstanceLockError(RuntimeError):
    """Base error for the local CoreMind single-instance lock."""


class InstanceAlreadyRunning(InstanceLockError):
    """Raised when another process currently holds the local instance lock."""

    def __init__(self, path: Path, owner: dict[str, Any] | None = None) -> None:
        self.path = path
        self.owner = owner
        detail = f"Alpecca instance lock is already held: {path}"
        if owner and isinstance(owner.get("pid"), int):
            detail += f" (pid {owner['pid']})"
        super().__init__(detail)


class InstanceLockRecoveryError(InstanceLockError):
    """Raised when a lock file's previous owner cannot be proven stale."""


def _try_lock(file: BinaryIO) -> None:
    """Take the first byte lock without waiting, on Windows or POSIX."""
    file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(file: BinaryIO) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def _pid_is_live(pid: int) -> bool | None:
    """Return False only when the OS can prove that ``pid`` no longer exists."""
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_live(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    except OSError as exc:
        return False if exc.errno == errno.ESRCH else None
    return True


def _windows_pid_is_live(pid: int) -> bool | None:
    """Check a Windows process without relying on ``os.kill(pid, 0)``."""
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong)
    open_process.restype = ctypes.c_void_p
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    get_exit_code.restype = ctypes.c_bool
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_bool

    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        return False if error == 87 else None  # ERROR_INVALID_PARAMETER
    try:
        exit_code = ctypes.c_ulong()
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            return None
        return exit_code.value == still_active
    finally:
        close_handle(handle)


class LocalInstanceLock:
    """Atomic, cross-process lock for the one local CoreMind/database writer.

    The held OS lock, rather than the file's contents, is the authority. The
    persistent file is deliberately never unlinked or replaced: doing either
    could let two processes lock different files at the same path. Owner
    metadata is diagnostic and only permits stale recovery after the kernel
    lock is free and the previous PID is proven dead.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path).resolve()
        self._path_key = os.path.normcase(str(self.path))
        self._file: BinaryIO | None = None
        self._owner: dict[str, Any] | None = None
        self._state_lock = threading.Lock()

    @property
    def is_held(self) -> bool:
        return self._file is not None

    @property
    def owner(self) -> dict[str, Any] | None:
        """Return this object's owner metadata while it holds the lock."""
        return None if self._owner is None else dict(self._owner)

    def acquire(self) -> "LocalInstanceLock":
        """Acquire the lock immediately or fail closed without modifying it."""
        with self._state_lock:
            if self._file is not None:
                raise InstanceLockError(f"Alpecca instance lock is already held by this process: {self.path}")

            self._reserve_process_path()
            file: BinaryIO | None = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                file = self.path.open("a+b")
                self._ensure_lock_byte(file)
                try:
                    _try_lock(file)
                except OSError as exc:
                    raise InstanceAlreadyRunning(self.path, self.read_owner()) from exc

                previous_owner = self._read_owner(file)
                self._verify_stale_owner(previous_owner)
                self._owner = self._write_owner(file)
                self._file = file
            except Exception:
                if file is not None and self._file is None:
                    try:
                        _unlock(file)
                    except OSError:
                        pass
                    file.close()
                self._release_process_path()
                raise
        return self

    def release(self) -> None:
        """Release only this object's held OS lock; keep its lock file intact."""
        with self._state_lock:
            file = self._file
            if file is None:
                return
            try:
                self._clear_owner(file)
                _unlock(file)
            finally:
                self._file = None
                self._owner = None
                file.close()
                self._release_process_path()

    def read_owner(self) -> dict[str, Any] | None:
        """Return best-effort diagnostic owner metadata without trusting it."""
        if self._owner is not None:
            return dict(self._owner)
        try:
            with self.path.open("rb") as file:
                return self._read_owner(file)
        except OSError:
            return None

    def __enter__(self) -> "LocalInstanceLock":
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()

    def _reserve_process_path(self) -> None:
        with _PROCESS_LOCK_PATHS_GUARD:
            if self._path_key in _PROCESS_LOCK_PATHS:
                raise InstanceAlreadyRunning(self.path)
            _PROCESS_LOCK_PATHS.add(self._path_key)

    def _release_process_path(self) -> None:
        with _PROCESS_LOCK_PATHS_GUARD:
            _PROCESS_LOCK_PATHS.discard(self._path_key)

    @staticmethod
    def _ensure_lock_byte(file: BinaryIO) -> None:
        file.seek(0, os.SEEK_END)
        if file.tell() == 0:
            file.write(b"\0")
            file.flush()
            os.fsync(file.fileno())

    @staticmethod
    def _read_owner(file: BinaryIO) -> dict[str, Any] | None:
        file.seek(0)
        raw = file.read(_MAX_LOCK_METADATA_BYTES + 1)
        if not raw or len(raw) > _MAX_LOCK_METADATA_BYTES:
            return None
        raw = raw.rstrip(b"\0\r\n \t")
        if not raw:
            return None
        try:
            owner = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if (
            not isinstance(owner, dict)
            or set(owner) != {"version", "pid", "started_at", "hostname"}
            or owner["version"] != _LOCK_METADATA_VERSION
            or type(owner["pid"]) is not int
            or type(owner["started_at"]) not in (int, float)
            or not isinstance(owner["hostname"], str)
        ):
            return None
        return owner

    def _verify_stale_owner(self, owner: dict[str, Any] | None) -> None:
        if owner is None or owner["pid"] == os.getpid():
            return
        live = _pid_is_live(owner["pid"])
        if live is False:
            return
        reason = "is still live" if live else "cannot be verified dead"
        raise InstanceLockRecoveryError(
            f"Refusing to recover Alpecca instance lock at {self.path}: "
            f"previous owner pid {owner['pid']} {reason}"
        )

    @staticmethod
    def _write_owner(file: BinaryIO) -> dict[str, Any]:
        owner = {
            "version": _LOCK_METADATA_VERSION,
            "pid": os.getpid(),
            "started_at": time.time(),
            "hostname": socket.gethostname(),
        }
        encoded = json.dumps(owner, separators=(",", ":"), sort_keys=True).encode("utf-8")
        file.seek(0)
        file.truncate(0)
        file.write(encoded)
        file.flush()
        os.fsync(file.fileno())
        return owner

    @staticmethod
    def _clear_owner(file: BinaryIO) -> None:
        file.seek(0)
        file.truncate(0)
        file.write(b"\0")
        file.flush()
        os.fsync(file.fileno())


def http_status(url: str, timeout: float = 1.0) -> int | None:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "alpecca-instance"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return None


def _is_alpecca_healthz(url: str, timeout: float) -> bool:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "alpecca-instance"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            if int(resp.status) != 200 or resp.geturl() != url:
                return False
            raw = resp.read(MAX_HEALTHZ_BYTES + 1)
    except Exception:
        return False
    if not raw or len(raw) > MAX_HEALTHZ_BYTES:
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and set(payload) == {"service", "version"}
        and payload["service"] == HEALTHZ_SERVICE
        and type(payload["version"]) is int
        and payload["version"] == HEALTHZ_VERSION
    )


def existing_server_url(port: int, host: str = "127.0.0.1",
                        token: str = "", timeout: float = 1.0) -> str | None:
    """Return the local URL if an Alpecca server is already answering.

    ``token`` remains only for caller compatibility. Public identity and other
    credentials must never be placed in a probe URL.
    """
    del token
    base = f"http://{host}:{int(port)}"
    return base if _is_alpecca_healthz(base + HEALTHZ_PATH, timeout) else None
