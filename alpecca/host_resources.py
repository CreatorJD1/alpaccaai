"""Read-only Windows-capable host-resource telemetry.

This module only observes host state.  It does not read or change pagefile
settings, use the registry, request elevation, or apply its advisory policy.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import csv
import ctypes
from ctypes import wintypes
import math
from numbers import Real
import os
import shutil
import subprocess
import threading
import time
from typing import Any

from . import resource_policy, resource_signals


CACHE_SECONDS = 3.0
GPU_TIMEOUT_SECONDS = 1.5
MAX_GPU_ROWS = 16
MEBIBYTE = 1024 * 1024

_MISSING = object()
_RAW_FIELDS = (
    "cpu_percent",
    "ram_used_bytes",
    "ram_total_bytes",
    "commit_used_bytes",
    "commit_limit_bytes",
    "vram_used_bytes",
    "vram_total_bytes",
    "disk_free_bytes",
    "disk_total_bytes",
    "battery_percent",
    "battery_charging",
    "thermal_celsius",
)


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def _lookup(value: object, *names: str) -> object:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return _MISSING
    if value is None:
        return _MISSING
    for name in names:
        try:
            return getattr(value, name)
        except AttributeError:
            continue
    return _MISSING


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        return None
    return int(number)


def _percentage(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        return None
    return round(number, 2)


def _temperature(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        return None
    return round(number, 2)


def _nvidia_number(value: object) -> float | None:
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0.0 else None


def _boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _bytes(
    value: object,
    *byte_names: str,
    mib_names: tuple[str, ...] = (),
) -> int | None:
    raw = _lookup(value, *byte_names)
    if raw is not _MISSING:
        return _nonnegative_int(raw)
    raw_mib = _lookup(value, *mib_names)
    if raw_mib is _MISSING:
        return None
    mib = _nonnegative_int(raw_mib)
    return None if mib is None else mib * MEBIBYTE


def _remaining(used: object, total: object) -> tuple[int | None, float | None]:
    used_bytes = _nonnegative_int(used)
    total_bytes = _nonnegative_int(total)
    if used_bytes is None or total_bytes is None or used_bytes > total_bytes:
        return None, None
    headroom = total_bytes - used_bytes
    return headroom, round(headroom / total_bytes, 4) if total_bytes else None


def _free_space(free: object, total: object) -> tuple[int | None, float | None]:
    free_bytes = _nonnegative_int(free)
    total_bytes = _nonnegative_int(total)
    if free_bytes is None or total_bytes is None or free_bytes > total_bytes:
        return None, None
    return free_bytes, round(free_bytes / total_bytes, 4) if total_bytes else None


def _filetime_value(value: _FILETIME) -> int:
    return int(value.dwLowDateTime) | (int(value.dwHighDateTime) << 32)


class HostResourceSampler:
    """Read-only sampler with private, overridable probes for deterministic tests."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        cache_ttl_seconds: float = CACHE_SECONDS,
        _clock: Callable[[], float] | None = None,
        _monotonic: Callable[[], float] | None = None,
        _cpu_probe: Callable[[], object] | None = None,
        _performance_probe: Callable[[], object] | None = None,
        _battery_probe: Callable[[], object] | None = None,
        _disk_probe: Callable[[], object] | None = None,
        _gpu_probe: Callable[[], object] | None = None,
        _disk_path: str | None = None,
        _is_windows: bool | None = None,
    ) -> None:
        supplied_clock = clock or _clock
        self._clock = supplied_clock or time.time
        self._monotonic = _monotonic or supplied_clock or time.monotonic
        self._cache_ttl_seconds = self._cache_ttl(cache_ttl_seconds)
        self._is_windows = os.name == "nt" if _is_windows is None else bool(_is_windows)
        system_drive = os.environ.get("SystemDrive", "") if self._is_windows else ""
        self._disk_path = _disk_path or (system_drive + os.sep if system_drive else os.path.abspath(os.sep))

        self._cpu_times_reader = _cpu_probe or self._read_cpu_times
        self._performance_reader = _performance_probe or self._read_performance_info
        self._battery_reader = _battery_probe or self._read_battery_status
        self._disk_reader = _disk_probe or self._read_disk_usage
        self._gpu_reader = _gpu_probe or self._read_gpu_status

        self._lock = threading.RLock()
        self._cpu_previous: tuple[int, int, int] | None = None
        self._cpu_started = False
        self._performance_for_collection: object = _MISSING
        self._gpu_for_collection: object = None
        self._cached_snapshot: dict[str, object] | None = None
        self._cached_at: float | None = None

    @staticmethod
    def _cache_ttl(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            return CACHE_SECONDS
        ttl = float(value)
        return ttl if math.isfinite(ttl) and ttl > 0.0 else CACHE_SECONDS

    def snapshot(self, force: bool = False) -> dict[str, object]:
        """Return one observed snapshot, using the in-memory TTL cache by default."""
        with self._lock:
            now = self._monotonic_now()
            if (
                not force
                and self._cached_snapshot is not None
                and self._cached_at is not None
            ):
                elapsed = now - self._cached_at
                if 0.0 <= elapsed < self._cache_ttl_seconds:
                    return self._cached_copy(elapsed)

            snapshot = self._collect()
            snapshot["timestamp"] = self._wall_now()
            snapshot["age"] = 0.0
            snapshot["age_seconds"] = 0.0
            self._cached_snapshot = deepcopy(snapshot)
            self._cached_at = self._monotonic_now()
            return snapshot

    def sample(self, force: bool = False) -> dict[str, object]:
        """Alias for consumers that use a generic resource sampler interface."""
        return self.snapshot(force=force)

    def _cached_copy(self, age: float) -> dict[str, object]:
        assert self._cached_snapshot is not None
        snapshot = deepcopy(self._cached_snapshot)
        rounded_age = round(max(0.0, age), 3)
        snapshot["age"] = rounded_age
        snapshot["age_seconds"] = rounded_age
        return snapshot

    def _wall_now(self) -> float:
        try:
            value = float(self._clock())
        except Exception:
            return time.time()
        return value if math.isfinite(value) else time.time()

    def _monotonic_now(self) -> float:
        try:
            value = float(self._monotonic())
        except Exception:
            return time.monotonic()
        return value if math.isfinite(value) else time.monotonic()

    def _safe_probe(
        self,
        name: str,
        probe: Callable[[], object],
        errors: dict[str, str],
    ) -> object:
        try:
            return probe()
        except Exception as exc:
            errors[name] = type(exc).__name__
            return None

    # The following private hooks are intentionally small and overridable.
    # Defaults are observational Windows APIs or read-only stdlib calls.
    def _probe_cpu_percent(self) -> float | None:
        sample = self._cpu_times_reader()
        direct = _percentage(_lookup(sample, "cpu_percent", "percent"))
        if direct is not None:
            return direct
        current = self._cpu_times(sample)
        if current is None:
            return None
        previous = self._cpu_previous
        self._cpu_previous = current
        if previous is None:
            return None
        idle_delta = current[0] - previous[0]
        kernel_delta = current[1] - previous[1]
        user_delta = current[2] - previous[2]
        total_delta = kernel_delta + user_delta
        if idle_delta < 0 or kernel_delta < 0 or user_delta < 0 or total_delta <= 0:
            return None
        if idle_delta > total_delta:
            return None
        return round(100.0 * (total_delta - idle_delta) / total_delta, 2)

    def _probe_ram(self) -> dict[str, int] | None:
        value = self._performance_sample()
        total = _bytes(value, "ram_total_bytes", "physical_total_bytes", "total_bytes")
        available = _bytes(value, "ram_available_bytes", "physical_available_bytes", "available_bytes")
        if total is None and available is None:
            return None
        return {"total_bytes": total, "available_bytes": available}

    def _probe_commit(self) -> dict[str, int] | None:
        value = self._performance_sample()
        used = _bytes(value, "commit_used_bytes", "commit_total_bytes", "used_bytes")
        limit = _bytes(value, "commit_limit_bytes", "limit_bytes")
        if used is None and limit is None:
            return None
        return {"used_bytes": used, "limit_bytes": limit}

    def _probe_battery(self) -> object:
        return self._battery_reader()

    def _probe_disk(self) -> object:
        return self._disk_reader()

    def _probe_gpu(self) -> object:
        return self._gpu_reader()

    def _probe_thermal_celsius(self) -> float | None:
        return self._gpu_temperature(self._gpu_for_collection)

    def _performance_sample(self) -> object:
        if self._performance_for_collection is _MISSING:
            self._performance_for_collection = self._performance_reader()
        return self._performance_for_collection

    @staticmethod
    def _cpu_times(value: object) -> tuple[int, int, int] | None:
        if isinstance(value, Mapping):
            fields = (
                _lookup(value, "idle", "idle_time", "idle_100ns"),
                _lookup(value, "kernel", "kernel_time", "kernel_100ns"),
                _lookup(value, "user", "user_time", "user_100ns"),
            )
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            fields = tuple(value[:3]) if len(value) >= 3 else ()
        else:
            return None
        if len(fields) != 3 or any(field is _MISSING for field in fields):
            return None
        parsed = tuple(_nonnegative_int(field) for field in fields)
        if any(item is None for item in parsed):
            return None
        idle, kernel, user = parsed
        if idle is None or kernel is None or user is None or idle > kernel:
            return None
        return idle, kernel, user

    def _collect_cpu(self, errors: dict[str, str]) -> dict[str, object]:
        value = self._safe_probe("cpu", self._probe_cpu_percent, errors)
        if not self._cpu_started:
            self._cpu_started = True
            return {"state": "warming", "percent": None}
        percent = _percentage(value)
        return {
            "state": "known" if percent is not None else "unknown",
            "percent": percent,
        }

    @staticmethod
    def _ram_reading(value: object) -> dict[str, object]:
        total = _bytes(value, "ram_total_bytes", "physical_total_bytes", "total_bytes")
        available = _bytes(value, "ram_available_bytes", "physical_available_bytes", "available_bytes")
        used = _bytes(value, "ram_used_bytes", "physical_used_bytes", "used_bytes")
        if used is None and total is not None and available is not None and available <= total:
            used = total - available
        headroom, fraction = _remaining(used, total)
        if available is None:
            available = headroom
        return {
            "state": "known" if used is not None and total is not None else "unknown",
            "used_bytes": used,
            "total_bytes": total,
            "available_bytes": available,
            "headroom_bytes": headroom,
            "headroom_fraction": fraction,
        }

    @staticmethod
    def _commit_reading(value: object) -> dict[str, object]:
        used = _bytes(value, "commit_used_bytes", "commit_total_bytes", "used_bytes")
        limit = _bytes(value, "commit_limit_bytes", "limit_bytes", "total_bytes")
        headroom, fraction = _remaining(used, limit)
        return {
            "state": "known" if used is not None and limit is not None else "unknown",
            "used_bytes": used,
            "limit_bytes": limit,
            "headroom_bytes": headroom,
            "headroom_fraction": fraction,
        }

    @staticmethod
    def _battery_reading(value: object) -> dict[str, object]:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, Mapping)):
            value = {
                "percent": value[0] if value else None,
                "charging": value[1] if len(value) > 1 else None,
            }
        percent = _percentage(_lookup(value, "battery_percent", "percent"))
        charging = _boolean(_lookup(value, "battery_charging", "charging"))
        return {
            "state": "known" if percent is not None or charging is not None else "unknown",
            "percent": percent,
            "charging": charging,
        }

    @staticmethod
    def _disk_reading(value: object) -> dict[str, object]:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, Mapping)):
            value = {
                "total_bytes": value[0] if value else None,
                "free_bytes": value[2] if len(value) > 2 else None,
            }
        free = _bytes(value, "disk_free_bytes", "free_bytes", "free")
        total = _bytes(value, "disk_total_bytes", "total_bytes", "total")
        headroom, fraction = _free_space(free, total)
        return {
            "state": "known" if free is not None and total is not None else "unknown",
            "free_bytes": free,
            "total_bytes": total,
            "headroom_bytes": headroom,
            "headroom_fraction": fraction,
        }

    @staticmethod
    def _gpu_devices(value: object) -> list[object]:
        if isinstance(value, Mapping):
            devices = _lookup(value, "devices", "gpus")
            if devices is _MISSING:
                return [value]
            if isinstance(devices, Sequence) and not isinstance(devices, (str, bytes, bytearray)):
                return list(devices[:MAX_GPU_ROWS])
            return []
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return list(value[:MAX_GPU_ROWS])
        return []

    @classmethod
    def _gpu_reading(cls, value: object) -> dict[str, object]:
        devices: list[dict[str, object]] = []
        for item in cls._gpu_devices(value):
            total = _bytes(
                item,
                "vram_total_bytes",
                "memory_total_bytes",
                "total_bytes",
                mib_names=("vram_total_mb", "memory_total_mb", "memory_total"),
            )
            used = _bytes(
                item,
                "vram_used_bytes",
                "memory_used_bytes",
                "used_bytes",
                mib_names=("vram_used_mb", "memory_used_mb", "memory_used"),
            )
            temperature = _temperature(_lookup(item, "temperature_celsius", "temperature_c", "temperature"))
            name = _lookup(item, "name", "gpu_name")
            devices.append({
                "name": str(name)[:160] if name is not _MISSING and name is not None else None,
                "total_bytes": total,
                "used_bytes": used,
                "temperature_celsius": temperature,
            })

        complete = [
            item for item in devices
            if isinstance(item["total_bytes"], int)
            and isinstance(item["used_bytes"], int)
            and item["used_bytes"] <= item["total_bytes"]
        ]
        total = sum(int(item["total_bytes"]) for item in complete) if complete else None
        used = sum(int(item["used_bytes"]) for item in complete) if complete else None
        headroom, fraction = _remaining(used, total)
        temperatures = [
            float(item["temperature_celsius"])
            for item in devices
            if isinstance(item["temperature_celsius"], (int, float))
        ]
        return {
            "state": "known" if total is not None and used is not None else "unknown",
            "source": "nvidia-smi",
            "devices": devices,
            "used_bytes": used,
            "total_bytes": total,
            "headroom_bytes": headroom,
            "headroom_fraction": fraction,
            "temperature_celsius": max(temperatures) if temperatures else None,
            "vram_used_bytes": used,
            "vram_total_bytes": total,
        }

    @classmethod
    def _gpu_temperature(cls, value: object) -> float | None:
        direct = _temperature(_lookup(value, "temperature_celsius", "temperature_c", "temperature"))
        if direct is not None:
            return direct
        temperatures: list[float] = []
        for item in cls._gpu_devices(value):
            temperature = _temperature(_lookup(item, "temperature_celsius", "temperature_c", "temperature"))
            if temperature is not None:
                temperatures.append(temperature)
        return max(temperatures) if temperatures else None

    @staticmethod
    def _thermal_reading(value: object, fallback: object) -> dict[str, object]:
        celsius = _temperature(value)
        if celsius is None:
            celsius = _temperature(fallback)
        return {
            "state": "known" if celsius is not None else "unknown",
            "celsius": celsius,
        }

    def _collect(self) -> dict[str, object]:
        errors: dict[str, str] = {}
        self._performance_for_collection = _MISSING
        self._gpu_for_collection = None
        try:
            cpu = self._collect_cpu(errors)
            ram = self._ram_reading(self._safe_probe("ram", self._probe_ram, errors))
            commit = self._commit_reading(self._safe_probe("commit", self._probe_commit, errors))
            battery = self._battery_reading(self._safe_probe("battery", self._probe_battery, errors))
            disk = self._disk_reading(self._safe_probe("disk", self._probe_disk, errors))
            gpu_source = self._safe_probe("gpu", self._probe_gpu, errors)
            self._gpu_for_collection = gpu_source
            gpu = self._gpu_reading(gpu_source)
            thermal = self._thermal_reading(
                self._safe_probe("thermal", self._probe_thermal_celsius, errors),
                gpu["temperature_celsius"],
            )
        finally:
            self._performance_for_collection = _MISSING
            self._gpu_for_collection = None

        raw: dict[str, object] = {
            "cpu_percent": cpu["percent"],
            "ram_used_bytes": ram["used_bytes"],
            "ram_total_bytes": ram["total_bytes"],
            "commit_used_bytes": commit["used_bytes"],
            "commit_limit_bytes": commit["limit_bytes"],
            "vram_used_bytes": gpu["used_bytes"],
            "vram_total_bytes": gpu["total_bytes"],
            "disk_free_bytes": disk["free_bytes"],
            "disk_total_bytes": disk["total_bytes"],
            "battery_percent": battery["percent"],
            "battery_charging": battery["charging"],
            "thermal_celsius": thermal["celsius"],
        }
        assessment = resource_signals.assess_resources(**raw)
        policy = resource_policy.decide(
            resource_assessment=assessment,
            memory_pressure=None,
        )

        headroom = {
            "ram_bytes": ram["headroom_bytes"],
            "ram_fraction": ram["headroom_fraction"],
            "commit_bytes": commit["headroom_bytes"],
            "commit_fraction": commit["headroom_fraction"],
            "vram_bytes": gpu["headroom_bytes"],
            "vram_fraction": gpu["headroom_fraction"],
            "disk_bytes": disk["headroom_bytes"],
            "disk_fraction": disk["headroom_fraction"],
            "ram": {"bytes": ram["headroom_bytes"], "fraction": ram["headroom_fraction"]},
            "commit": {"bytes": commit["headroom_bytes"], "fraction": commit["headroom_fraction"]},
            "vram": {"bytes": gpu["headroom_bytes"], "fraction": gpu["headroom_fraction"]},
            "disk": {"bytes": disk["headroom_bytes"], "fraction": disk["headroom_fraction"]},
        }
        ram_total = _nonnegative_int(ram["total_bytes"])
        commit_limit = _nonnegative_int(commit["limit_bytes"])
        estimated_capacity = (
            commit_limit - ram_total
            if ram_total is not None and commit_limit is not None and commit_limit >= ram_total
            else None
        )
        pagefile = {
            "state": "estimated" if estimated_capacity is not None else "unknown",
            "source": "GetPerformanceInfo",
            "estimated_capacity_bytes": estimated_capacity,
            "commit_limit_bytes": commit_limit,
            "physical_ram_bytes": ram_total,
            "commit_headroom_bytes": commit["headroom_bytes"],
            "commit_headroom_fraction": commit["headroom_fraction"],
            "configuration_read": False,
        }

        source_states = {
            "cpu": cpu["state"],
            "ram": ram["state"],
            "commit": commit["state"],
            "battery": battery["state"],
            "disk": disk["state"],
            "vram": gpu["state"],
            "thermal": thermal["state"],
            "gpu": gpu["state"],
        }
        sources = {
            "cpu": "GetSystemTimes",
            "ram": "GetPerformanceInfo",
            "commit": "GetPerformanceInfo",
            "battery": "GetSystemPowerStatus",
            "disk": "shutil.disk_usage",
            "vram": "nvidia-smi",
            "thermal": "nvidia-smi",
        }
        unknown = [field for field in _RAW_FIELDS if raw[field] is None]
        if cpu["state"] == "warming":
            state = "warming"
        elif not assessment.get("known_resources"):
            state = "unknown"
        elif unknown or assessment.get("invalid_resources"):
            state = "partial"
        else:
            state = "ready"

        unknown_reasons: dict[str, str] = {}
        field_probe = {
            "cpu_percent": "cpu",
            "ram_used_bytes": "ram",
            "ram_total_bytes": "ram",
            "commit_used_bytes": "commit",
            "commit_limit_bytes": "commit",
            "vram_used_bytes": "gpu",
            "vram_total_bytes": "gpu",
            "disk_free_bytes": "disk",
            "disk_total_bytes": "disk",
            "battery_percent": "battery",
            "battery_charging": "battery",
            "thermal_celsius": "thermal",
        }
        for field in unknown:
            source = field_probe[field]
            if field == "cpu_percent" and cpu["state"] == "warming":
                unknown_reasons[field] = "warming"
            elif source in errors:
                unknown_reasons[field] = "probe_unavailable"
            else:
                unknown_reasons[field] = "not_available"

        return {
            "state": state,
            "sources": sources,
            "source_states": source_states,
            "cpu": cpu,
            "ram": ram,
            "commit": commit,
            "battery": battery,
            "disk": disk,
            "gpu": gpu,
            "thermal": thermal,
            "raw": raw,
            "headroom": headroom,
            "pagefile": pagefile,
            "assessment": assessment,
            "resource_signals": assessment,
            "advisory": policy,
            "policy": policy,
            "unknown": unknown,
            "unknown_fields": list(unknown),
            "unknowns": list(unknown),
            "unknown_resources": list(assessment.get("unknown_resources", ())),
            "unknown_reasons": unknown_reasons,
        }

    def _read_cpu_times(self) -> dict[str, int] | None:
        if not self._is_windows:
            return None
        idle = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        try:
            function = ctypes.windll.kernel32.GetSystemTimes
            function.argtypes = (
                ctypes.POINTER(_FILETIME),
                ctypes.POINTER(_FILETIME),
                ctypes.POINTER(_FILETIME),
            )
            function.restype = wintypes.BOOL
            success = function(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        except Exception:
            return None
        if not success:
            return None
        return {
            "idle": _filetime_value(idle),
            "kernel": _filetime_value(kernel),
            "user": _filetime_value(user),
        }

    def _read_performance_info(self) -> dict[str, int] | None:
        if not self._is_windows:
            return None
        info = _PERFORMANCE_INFORMATION()
        info.cb = ctypes.sizeof(info)
        try:
            function = ctypes.windll.psapi.GetPerformanceInfo
            function.argtypes = (ctypes.POINTER(_PERFORMANCE_INFORMATION), wintypes.DWORD)
            function.restype = wintypes.BOOL
            success = function(ctypes.byref(info), info.cb)
        except Exception:
            return None
        page_size = int(info.PageSize)
        if not success or page_size <= 0:
            return None
        return {
            "ram_total_bytes": int(info.PhysicalTotal) * page_size,
            "ram_available_bytes": int(info.PhysicalAvailable) * page_size,
            "commit_used_bytes": int(info.CommitTotal) * page_size,
            "commit_limit_bytes": int(info.CommitLimit) * page_size,
        }

    def _read_battery_status(self) -> dict[str, object] | None:
        if not self._is_windows:
            return None
        status = _SYSTEM_POWER_STATUS()
        try:
            function = ctypes.windll.kernel32.GetSystemPowerStatus
            function.argtypes = (ctypes.POINTER(_SYSTEM_POWER_STATUS),)
            function.restype = wintypes.BOOL
            success = function(ctypes.byref(status))
        except Exception:
            return None
        if not success:
            return None

        line_status = int(status.ACLineStatus)
        battery_flag = int(status.BatteryFlag)
        life_percent = int(status.BatteryLifePercent)
        if line_status == 1 or (battery_flag != 255 and battery_flag & 0x08):
            charging: bool | None = True
        elif line_status == 0:
            charging = False
        else:
            charging = None
        return {
            "percent": None if life_percent == 255 else life_percent,
            "charging": charging,
        }

    def _read_disk_usage(self) -> dict[str, int] | None:
        try:
            usage = shutil.disk_usage(self._disk_path)
        except Exception:
            return None
        return {"free_bytes": int(usage.free), "total_bytes": int(usage.total)}

    def _read_gpu_status(self) -> dict[str, object] | None:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return None
        kwargs: dict[str, Any] = {}
        if self._is_windows:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                [
                    executable,
                    "--query-gpu=name,memory.total,memory.used,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=GPU_TIMEOUT_SECONDS,
                check=False,
                shell=False,
                **kwargs,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None

        devices: list[dict[str, object]] = []
        for row in csv.reader((completed.stdout or "").splitlines()[:MAX_GPU_ROWS]):
            if len(row) != 4:
                continue
            name, total_mib, used_mib, temperature_c = (part.strip() for part in row)
            total = _nvidia_number(total_mib)
            used = _nvidia_number(used_mib)
            temperature = _nvidia_number(temperature_c)
            devices.append({
                "name": name,
                "vram_total_mb": _nonnegative_int(total),
                "vram_used_mb": _nonnegative_int(used),
                "temperature_celsius": _temperature(temperature),
            })
        return {"devices": devices} if devices else None


__all__ = ["CACHE_SECONDS", "GPU_TIMEOUT_SECONDS", "HostResourceSampler"]
