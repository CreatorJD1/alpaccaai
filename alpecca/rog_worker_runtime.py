"""Primary-host facade for Alpecca's non-speaking ROG compute helper."""

from __future__ import annotations

from collections.abc import Callable

from alpecca.rog_worker_client import (
    HYFUSER_EMOTION_ORDER,
    RogWorkerClient,
    RogWorkerError,
)


STATUS_SCHEMA = "alpecca.rog-worker.primary-status.v1"
RENDER_RECEIPT_SCHEMA = "alpecca.rog-worker.render-receipt.v1"
HYFUSER_STATUS_SCHEMA = "alpecca.rog-worker.hyfuser-status.v1"
HYFUSER_RECEIPT_SCHEMA = "alpecca.rog-worker.hyfuser-receipt.v1"

ClientFactory = Callable[[], RogWorkerClient]


def status_snapshot(
    configured_url: str,
    *,
    client_factory: ClientFactory = RogWorkerClient.from_environment,
) -> dict[str, object]:
    """Return a content-free status without exposing endpoint credentials."""

    if not str(configured_url or "").strip():
        return {
            "schema": STATUS_SCHEMA,
            "configured": False,
            "state": "disabled",
            "emotion_order": list(HYFUSER_EMOTION_ORDER),
            "ready": False,
            "role": "compute-only",
            "speaking": False,
            "discord": False,
            "capabilities": {"reasoning": False, "blender": False},
            "error": "",
        }
    try:
        health = client_factory().health()
    except RogWorkerError as exc:
        return {
            "schema": STATUS_SCHEMA,
            "configured": True,
            "state": "unavailable",
            "emotion_order": list(HYFUSER_EMOTION_ORDER),
            "ready": False,
            "role": "compute-only",
            "speaking": False,
            "discord": False,
            "capabilities": {"reasoning": False, "blender": False},
            "error": type(exc).__name__,
        }
    return {
        "schema": STATUS_SCHEMA,
        "configured": True,
        "state": "ready" if health.ready else "degraded",
        "ready": bool(health.ready),
        "hostname": health.hostname,
        "role": health.role,
        "speaking": bool(health.speaking),
        "discord": bool(health.discord),
        "capabilities": {
            "reasoning": bool(health.reasoning_ready),
            "blender": bool(health.blender_ready),
        },
        "error": "",
    }


def render_blender(
    project: str,
    frame: int = 1,
    *,
    client_factory: ClientFactory = RogWorkerClient.from_environment,
) -> dict[str, object]:
    """Request one fixed Blender frame and return metadata-only evidence."""

    result = client_factory().render_blender(project, frame=frame)
    return {
        "schema": RENDER_RECEIPT_SCHEMA,
        "ok": result.status == "completed",
        "request_id": result.request_id,
        "job_id": result.job_id,
        "status": result.status,
        "frame": result.frame,
        "artifact": {
            "id": result.artifact_id,
            "name": result.artifact_name,
            "sha256": result.artifact_sha256,
            "bytes": result.artifact_bytes,
        },
        "elapsed_ms": result.elapsed_ms,
    }


def hyfuser_status(
    configured_url: str,
    *,
    client_factory: ClientFactory = RogWorkerClient.from_environment,
) -> dict[str, object]:
    """Return content-free readiness for the advisory seven-head service."""

    if not str(configured_url or "").strip():
        return {
            "schema": HYFUSER_STATUS_SCHEMA,
            "configured": False,
            "ready": False,
            "state": "disabled",
            "advisory": True,
            "shadow_only": True,
            "speaking": False,
            "state_mutation": False,
        }
    try:
        health = client_factory().hyfuser_health()
    except RogWorkerError as exc:
        return {
            "schema": HYFUSER_STATUS_SCHEMA,
            "configured": True,
            "ready": False,
            "state": "unavailable",
            "advisory": True,
            "shadow_only": True,
            "speaking": False,
            "state_mutation": False,
            "error": type(exc).__name__,
        }
    return {
        "schema": HYFUSER_STATUS_SCHEMA,
        "configured": True,
        "ready": bool(health.ready),
        "state": health.state,
        "architecture": health.architecture,
        "perspectives": list(health.perspectives),
        "emotion_order": list(health.emotion_order),
        "advisory": True,
        "shadow_only": True,
        "speaking": False,
        "state_mutation": False,
        "error": "",
    }


def score_hyfuser_shadow(
    text_emotion: list[float],
    speech_emotion: list[float],
    *,
    emotion_order: tuple[str, ...] | list[str] = HYFUSER_EMOTION_ORDER,
    client_factory: ClientFactory = RogWorkerClient.from_environment,
) -> dict[str, object]:
    """Return metadata-bound advisory scores without applying them."""

    result = client_factory().score_soul(
        text_emotion,
        speech_emotion,
        emotion_order=emotion_order,
    )
    return {
        "schema": HYFUSER_RECEIPT_SCHEMA,
        "ok": True,
        "request_id": result.request_id,
        "architecture": result.architecture,
        "heads": [
            {
                "name": head.name,
                "score": head.score,
                "confidence": head.confidence,
            }
            for head in result.heads
        ],
        "provenance": {
            "runtime_id": result.runtime_id,
            "weights_sha256": result.weights_sha256,
            "emotion_order": list(HYFUSER_EMOTION_ORDER),
        },
        "elapsed_ms": result.elapsed_ms,
        "advisory": True,
        "shadow_only": True,
        "speaking": False,
        "state_mutation": False,
    }


__all__ = [
    "RENDER_RECEIPT_SCHEMA",
    "HYFUSER_RECEIPT_SCHEMA",
    "HYFUSER_STATUS_SCHEMA",
    "STATUS_SCHEMA",
    "hyfuser_status",
    "render_blender",
    "score_hyfuser_shadow",
    "status_snapshot",
]
