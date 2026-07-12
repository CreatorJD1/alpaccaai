"""Fail-closed checks for inference that is classified as local-only."""
from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit


_CLOUD_MODEL_SUFFIXES = (":cloud", "-cloud", ".cloud", "@cloud")


def ollama_host_is_loopback(value: str) -> bool:
    """Accept literal loopback endpoints without DNS or network probing."""
    raw = str(value or "").strip()
    if not raw:
        return False
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def model_name_is_local(
    model: str, *, known_cloud_models: Iterable[str] = ()
) -> bool:
    """Reject explicit cloud tags and configured hosted model identifiers."""
    normalized = str(model or "").strip().lower()
    if not normalized:
        return False
    configured_cloud = {
        str(value or "").strip().lower()
        for value in known_cloud_models
        if str(value or "").strip()
    }
    return (
        normalized not in configured_cloud
        and not normalized.endswith(_CLOUD_MODEL_SUFFIXES)
    )


def verified_local_ollama_target(
    host: str,
    model: str,
    *,
    known_cloud_models: Iterable[str] = (),
) -> bool:
    """True only for a loopback Ollama endpoint and a non-cloud model name."""
    return ollama_host_is_loopback(host) and model_name_is_local(
        model, known_cloud_models=known_cloud_models
    )


__all__ = [
    "model_name_is_local",
    "ollama_host_is_loopback",
    "verified_local_ollama_target",
]
