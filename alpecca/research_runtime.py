"""Bounded evidence for optional research runtimes shown in Brain Garden.

The main server does not instantiate these experimental workers by default. A
missing instance is therefore explicit unavailable evidence, not an unknown or
healthy claim. When a bounded runtime is later attached, its status provider
can replace that default without exposing media, transcripts, or identifiers.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import RLock


ResearchStatusProvider = Callable[[], Mapping[str, object]]

_LOCK = RLock()
_PROVIDERS: dict[str, ResearchStatusProvider] = {}

_DEFAULTS: dict[str, dict[str, object]] = {
    "video_companion": {"available": False},
    "asr_dispatch": {
        "schema": "alpecca.asr-dispatch-status.v1",
        "selection": {
            "schema": "alpecca.asr-selection.v1",
            "selected_backend": "faster-whisper",
        },
        "capabilities": {
            "faster-whisper": {"configured": False, "ready": False}
        },
    },
    "speaker_worker": {
        "status": "unavailable",
        "purpose": "familiarity-only",
        "device": "cpu",
        "may_authenticate": False,
        "may_grant_authority": False,
        "backend": "not-configured",
        "enrolled_profiles": 0,
        "max_audio_seconds": 12.0,
    },
    "face_worker": {
        "status": "unavailable",
        "purpose": "familiarity-only",
        "device": "cpu",
        "may_authenticate": False,
        "may_authorize_creator": False,
        "may_grant_authority": False,
        "image_retained": False,
        "max_image_bytes": 8 * 1024 * 1024,
        "max_image_pixels": 12_000_000,
    },
    "vision_dispatch": {"available": False},
}


def register_status_provider(name: str, provider: ResearchStatusProvider) -> None:
    """Register a read-only, bounded provider for one attached runtime."""
    if name not in _DEFAULTS:
        raise ValueError(f"unsupported research runtime: {name}")
    if not callable(provider):
        raise TypeError("provider must be callable")
    with _LOCK:
        _PROVIDERS[name] = provider


def clear_status_provider(name: str) -> None:
    """Detach a runtime provider, restoring explicit unavailable evidence."""
    with _LOCK:
        _PROVIDERS.pop(name, None)


def brain_graph_facts() -> dict[str, dict[str, object]]:
    """Return one bounded status mapping per research runtime without raising."""
    with _LOCK:
        providers = dict(_PROVIDERS)
    facts: dict[str, dict[str, object]] = {}
    for name, default in _DEFAULTS.items():
        provider = providers.get(name)
        try:
            value = provider() if provider is not None else default
        except Exception:
            value = default
        facts[name] = dict(value) if isinstance(value, Mapping) else dict(default)
    return facts
