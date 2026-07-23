from __future__ import annotations

from types import SimpleNamespace

from alpecca import rog_worker_runtime
from alpecca.rog_worker_client import RogWorkerTransportError


def test_disabled_status_does_not_construct_a_client():
    def forbidden():
        raise AssertionError("client should not be constructed")

    status = rog_worker_runtime.status_snapshot("", client_factory=forbidden)

    assert status["state"] == "disabled"
    assert status["configured"] is False
    assert status["speaking"] is False
    assert status["discord"] is False


def test_unavailable_status_exposes_only_error_type():
    def unavailable():
        raise RogWorkerTransportError("secret endpoint detail")

    status = rog_worker_runtime.status_snapshot(
        "https://Jason_HOLYROG:8788",
        client_factory=unavailable,
    )

    assert status["state"] == "unavailable"
    assert status["error"] == "RogWorkerTransportError"
    assert "secret" not in str(status)


def test_ready_status_preserves_compute_only_contract():
    health = SimpleNamespace(
        ready=True,
        hostname="Jason_HOLYROG",
        role="compute-only",
        speaking=False,
        discord=False,
        reasoning_ready=True,
        blender_ready=True,
    )
    status = rog_worker_runtime.status_snapshot(
        "https://Jason_HOLYROG:8788",
        client_factory=lambda: SimpleNamespace(health=lambda: health),
    )

    assert status["state"] == "ready"
    assert status["hostname"] == "Jason_HOLYROG"
    assert status["capabilities"] == {"reasoning": True, "blender": True}


def test_render_receipt_contains_evidence_not_a_local_command():
    result = SimpleNamespace(
        request_id="req-1",
        job_id="job-1",
        status="completed",
        frame=12,
        artifact_id="artifact-1",
        artifact_name="frame.png",
        artifact_sha256="a" * 64,
        artifact_bytes=1234,
        elapsed_ms=42,
    )
    seen = {}
    client = SimpleNamespace(
        render_blender=lambda project, frame: (
            seen.update(project=project, frame=frame) or result
        )
    )

    receipt = rog_worker_runtime.render_blender(
        "scenes/alpecca.blend",
        frame=12,
        client_factory=lambda: client,
    )

    assert seen == {"project": "scenes/alpecca.blend", "frame": 12}
    assert receipt["ok"] is True
    assert receipt["artifact"]["sha256"] == "a" * 64
    assert "command" not in receipt
