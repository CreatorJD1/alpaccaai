"""Primary-host facade for Alpecca's non-speaking ROG compute helper."""

from __future__ import annotations

from collections.abc import Callable

from alpecca.rog_worker_client import RogWorkerClient, RogWorkerError


STATUS_SCHEMA = "alpecca.rog-worker.primary-status.v1"
RENDER_RECEIPT_SCHEMA = "alpecca.rog-worker.render-receipt.v1"

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


__all__ = [
    "RENDER_RECEIPT_SCHEMA",
    "STATUS_SCHEMA",
    "render_blender",
    "status_snapshot",
]
