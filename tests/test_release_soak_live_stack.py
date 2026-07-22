from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import struct

import pytest

from scripts.release_soak import live_stack
from scripts.release_soak import live_stack_cli


NOW = 1_800_000_000.0
LOCAL_HEALTH = "http://127.0.0.1:8765/healthz"
BRAIN_GARDEN = "http://127.0.0.1:8765/brain/graph"
F5_HEALTH = "http://127.0.0.1:8776/health"
DISCOVERY = "https://public.example/mobile/alpecca-endpoint.json"
APK = "https://public.example/mobile/AlpeccaLauncher-v2.1.2.apk"
RELAY = "https://current.loca.lt"


def _iso(timestamp: float = NOW) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _write_capture(path: Path, *, observed_at: float = NOW, coremind: int = 1) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": live_stack.CAPTURE_SCHEMA,
                "observed_at": _iso(observed_at),
                "coremind": {"count": coremind},
                "brain_garden": {
                    "authenticated_http_status": 200,
                    "response_body_observed": False,
                },
                "discord_bridge": {"count": 1, "control_ready": True},
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_vrm(path: Path, *, spec_version: str = "1.0") -> Path:
    document = {
        "asset": {"version": "2.0"},
        "extensions": {"VRMC_vrm": {"specVersion": spec_version}},
    }
    body = json.dumps(document, separators=(",", ":")).encode("utf-8")
    body += b" " * ((4 - len(body) % 4) % 4)
    total = 20 + len(body)
    path.write_bytes(
        struct.pack("<IIIII", 0x46546C67, 2, total, len(body), 0x4E4F534A) + body
    )
    return path


def _discovery() -> dict[str, object]:
    return {
        "service": "alpecca-mobile-discovery",
        "version": 1,
        "updatedAt": int(NOW - 30),
        "endpoints": [
            {
                "url": RELAY,
                "kind": "quick",
                "priority": 10,
                "expiresAt": int(NOW + 3_600),
            }
        ],
    }


class _Response:
    def __init__(
        self,
        body: bytes = b"",
        *,
        status: int = 200,
        final_url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.final_url = final_url
        self.headers = headers or {}
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.final_url

    def read(self, limit: int = -1) -> bytes:
        self.read_calls += 1
        return self.body[:limit]


def _config(tmp_path: Path, capture: Path | None) -> live_stack.LiveStackConfig:
    return live_stack.LiveStackConfig(
        observer_capture_path=capture,
        local_health_url=LOCAL_HEALTH,
        brain_garden_url=BRAIN_GARDEN,
        f5_health_url=F5_HEALTH,
        discovery_url=DISCOVERY,
        apk_url=APK,
        v4_asset_path=_write_vrm(tmp_path / live_stack.REVIEWED_V4_NAME),
        promoted_vrm_path=_write_vrm(tmp_path / "alpecca.vrm"),
        timeout_seconds=0.5,
    )


def _check(receipt: dict[str, object], check_id: str) -> dict[str, object]:
    return next(item for item in receipt["checks"] if item["check"] == check_id)  # type: ignore[index]


def test_fully_observed_snapshot_passes_without_claiming_the_soak_complete(tmp_path: Path) -> None:
    capture = _write_capture(tmp_path / "capture.json")
    responses: list[tuple[object, _Response]] = []

    def open_request(request, _timeout):
        url = request.full_url
        if url == LOCAL_HEALTH or url == RELAY + "/healthz":
            response = _Response(
                b'{"service":"alpecca","version":1}', final_url=url
            )
        elif url == BRAIN_GARDEN:
            response = _Response(
                b"protected payload must not be read", status=401, final_url=url
            )
        elif url == F5_HEALTH:
            response = _Response(
                json.dumps(
                    {
                        "ok": True,
                        "ready": True,
                        "loading_error": "private-path-must-not-enter-receipt",
                    }
                ).encode("utf-8"),
                final_url=url,
            )
        elif url == DISCOVERY:
            response = _Response(
                json.dumps(_discovery()).encode("utf-8"),
                final_url=url,
                headers={"Content-Type": "application/json"},
            )
        elif url == APK:
            response = _Response(
                b"APK body must not be read",
                final_url=url,
                headers={
                    "Content-Type": "application/vnd.android.package-archive",
                    "Content-Length": str(live_stack.REVIEWED_APK_BYTES),
                    "ETag": '"reviewed"',
                },
            )
        else:
            raise AssertionError(f"unexpected test URL: {url}")
        responses.append((request, response))
        return response

    receipt = live_stack.LiveStackCollector(
        clock=lambda: NOW, open_request=open_request
    ).collect(_config(tmp_path, capture))

    assert receipt["assessment"] == {
        "status": "snapshot_observed",
        "counts": {"pass": 8, "fail": 0, "unknown": 0},
        "all_snapshot_checks_passed": True,
        "p14_completion_claim": False,
        "full_soak_complete": False,
    }
    assert receipt["phase"]["snapshot_count"] == 1  # type: ignore[index]
    assert receipt["phase"]["completion_claim"] is False  # type: ignore[index]
    assert "single_snapshot_has_no_soak_duration_or_stability_evidence" in receipt["unknowns"]
    rendered = live_stack.render_receipt(receipt)
    assert "private-path-must-not-enter-receipt" not in rendered
    assert RELAY not in rendered
    assert DISCOVERY not in rendered

    methods = [request.get_method() for request, _response in responses]
    assert methods == ["GET", "GET", "GET", "GET", "GET", "HEAD"]
    for request, _response in responses:
        headers = {key.lower(): value for key, value in request.header_items()}
        assert "authorization" not in headers
        assert "cookie" not in headers
    brain_response = next(response for request, response in responses if request.full_url == BRAIN_GARDEN)
    apk_response = next(response for request, response in responses if request.full_url == APK)
    assert brain_response.read_calls == 0
    assert apk_response.read_calls == 0


def test_missing_capture_keeps_process_brain_and_discord_claims_unknown(tmp_path: Path) -> None:
    def open_request(request, _timeout):
        url = request.full_url
        if url == LOCAL_HEALTH or url == RELAY + "/healthz":
            return _Response(b'{"service":"alpecca","version":1}', final_url=url)
        if url == BRAIN_GARDEN:
            return _Response(status=401, final_url=url)
        if url == F5_HEALTH:
            return _Response(b'{"ok":true,"ready":true}', final_url=url)
        if url == DISCOVERY:
            return _Response(
                json.dumps(_discovery()).encode(),
                final_url=url,
                headers={"Content-Type": "application/json"},
            )
        if url == APK:
            return _Response(
                final_url=url,
                headers={
                    "Content-Type": "application/vnd.android.package-archive",
                    "Content-Length": str(live_stack.REVIEWED_APK_BYTES),
                    "ETag": '"reviewed"',
                },
            )
        raise AssertionError(url)

    receipt = live_stack.LiveStackCollector(
        clock=lambda: NOW, open_request=open_request
    ).collect(_config(tmp_path, None))

    assert _check(receipt, "local_coremind_identity_health")["status"] == "unknown"
    assert _check(receipt, "brain_garden_protected_availability")["status"] == "unknown"
    assert _check(receipt, "discord_bridge_control_readiness")["status"] == "unknown"
    assert _check(receipt, "public_relay_identity_match")["status"] == "pass"
    assert receipt["assessment"]["status"] == "snapshot_incomplete"  # type: ignore[index]


def test_duplicate_coremind_capture_fails_closed(tmp_path: Path) -> None:
    capture = _write_capture(tmp_path / "capture.json", coremind=2)
    config = _config(tmp_path, capture)
    config = live_stack.LiveStackConfig(**{**config.__dict__, "network_enabled": False})

    receipt = live_stack.LiveStackCollector(clock=lambda: NOW).collect(config)

    result = _check(receipt, "local_coremind_identity_health")
    assert result["status"] == "fail"
    assert result["evidence"]["coremind_count"] == 2  # type: ignore[index]


@pytest.mark.parametrize(
    "field,value",
    (
        ("local_health_url", "http://user:" + "password@127.0.0.1:8765/healthz"),
        ("brain_garden_url", "http://127.0.0.1:8765/brain/graph?token=secret"),
        ("f5_health_url", "http://127.0.0.1:8776/warm"),
        (
            "discovery_url",
            "https://user:" + "secret@public.example/mobile/alpecca-endpoint.json",
        ),
        ("apk_url", "https://public.example/mobile/AlpeccaLauncher-v2.1.2.apk?key=secret"),
    ),
)
def test_configuration_rejects_credentials_queries_and_active_routes(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        live_stack.LiveStackConfig(**{field: value})


def test_cli_error_does_not_echo_a_credential_bearing_url(capsys) -> None:
    secret_url = "http://user:" + "do-not-print@127.0.0.1:8765/healthz"

    with pytest.raises(SystemExit) as exc:
        live_stack_cli.main(["--local-health-url", secret_url, "--offline"])

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "do-not-print" not in captured.err
    assert secret_url not in captured.err


def test_reviewed_apk_length_mismatch_fails_and_never_reads_body(tmp_path: Path) -> None:
    response = _Response(
        b"not read",
        final_url=APK,
        headers={
            "Content-Type": "application/vnd.android.package-archive",
            "Content-Length": str(live_stack.REVIEWED_APK_BYTES + 1),
            "ETag": '"different-size"',
        },
    )

    result = live_stack._apk_probe(APK, 0.5, lambda *_args: response)

    assert result["status"] == "fail"
    assert result["content_length"] == live_stack.REVIEWED_APK_BYTES + 1
    assert result["body_read"] is False
    assert response.read_calls == 0


def test_v4_manifest_parser_is_bounded_and_requires_reviewed_version(tmp_path: Path) -> None:
    accepted = _write_vrm(tmp_path / live_stack.REVIEWED_V4_NAME)
    rejected = _write_vrm(tmp_path / "alpecca.vrm", spec_version="0.x")

    accepted_result = live_stack._inspect_vrm(accepted, live_stack.REVIEWED_V4_NAME)
    rejected_result = live_stack._inspect_vrm(rejected, "alpecca.vrm")

    assert accepted_result["status"] == "pass"
    assert accepted_result["vrm_spec_version"] == "1.0"
    assert rejected_result["status"] == "fail"
    assert rejected_result["vrm_spec_version"] == "0.x"


def test_source_contains_no_process_control_command_execution_or_send_methods() -> None:
    root = Path(__file__).resolve().parents[1] / "scripts" / "release_soak"
    source = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in ("live_stack.py", "live_stack_cli.py")
    )

    assert "import subprocess" not in source
    assert "import server" not in source
    assert "from alpecca" not in source
    assert ".kill(" not in source
    assert ".terminate(" not in source
    assert 'method="POST"' not in source
    assert 'method="GET"' in source
    assert 'method="HEAD"' in source
