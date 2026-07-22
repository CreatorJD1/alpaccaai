from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest

from scripts.release_soak import (
    DEFAULT_MOBILE_APK_URL,
    DEFAULT_MOBILE_DISCOVERY_URL,
    LOCALTUNNEL_BYPASS_HEADER,
    LOCALTUNNEL_BYPASS_VALUE,
    PROCESS_STATUS_SCHEMA,
    RESULT_SCHEMA,
    STATUS_CAPTURE_SCHEMA,
    CheckResult,
    ReleaseSoakHarness,
    SoakConfig,
    probe_healthz,
    probe_mobile_apk_metadata,
    probe_mobile_discovery,
    render_report,
)
from scripts.release_soak import cli as soak_cli


NOW = 1_800_000_000.0
DISCOVERY_URL = "https://public.example/mobile/alpecca-endpoint.json"
APK_URL = "https://public.example/mobile/AlpeccaLauncher-v2.1.0.apk"
CURRENT_MOBILE_ENDPOINT = "https://current.loca.lt"


def _iso(timestamp: float = NOW) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _capture(kind: str, payload: dict, *, observed_at: float = NOW) -> dict:
    return {
        "schema": STATUS_CAPTURE_SCHEMA,
        "kind": kind,
        "observed_at": _iso(observed_at),
        "payload": payload,
    }


def _process_status(*, coremind: list[int], discord: list[int], observed_at: float = NOW) -> dict:
    return {
        "schema": PROCESS_STATUS_SCHEMA,
        "observed_at": _iso(observed_at),
        "coremind": {"count": len(coremind), "pids": coremind},
        "discord_bridge": {"count": len(discord), "pids": discord},
    }


def _result(
    kind: str,
    name: str,
    *,
    exit_code: int = 0,
    finished_at: float = NOW - 10,
    counts: dict[str, int] | None = None,
) -> dict:
    return {
        "schema": RESULT_SCHEMA,
        "kind": kind,
        "name": name,
        "started_at": _iso(finished_at - 5),
        "finished_at": _iso(finished_at),
        "exit_code": exit_code,
        "counts": counts if counts is not None else ({"passed": 3} if kind == "test" else {}),
    }


def _discovery_document(
    endpoint: str = CURRENT_MOBILE_ENDPOINT,
    *,
    kind: str = "quick",
    updated_at: int = int(NOW - 30),
    expires_at: int = int(NOW + 3_600),
) -> dict:
    return {
        "service": "alpecca-mobile-discovery",
        "version": 1,
        "updatedAt": updated_at,
        "endpoints": [
            {
                "url": endpoint,
                "kind": kind,
                "priority": 10,
                "expiresAt": 0 if kind == "named" else expires_at,
            }
        ],
    }


def _healthy_endpoint(_url: str | None, _timeout: float) -> CheckResult:
    return CheckResult(
        "endpoint_health",
        "pass",
        "synthetic exact health evidence",
        {"service": "alpecca", "version": 1},
    )


def _check(report: dict, check_id: str, observation: int = 0) -> dict:
    checks = report["observations"][observation]["checks"]
    return next(item for item in checks if item["check"] == check_id)


def test_happy_path_tracks_bounded_observations_without_claiming_p14_completion(tmp_path: Path) -> None:
    pid = os.getpid()
    process = _write_json(tmp_path / "process.json", _process_status(coremind=[pid], discord=[44]))
    runtime = _write_json(
        tmp_path / "runtime.json",
        _capture("runtime", {"models": {"chat_ready": True, "reason": "qwen3.5:9b"}}),
    )
    graph = _write_json(
        tmp_path / "graph.json",
        _capture(
            "brain_graph",
            {
                "nodes": [
                    {"probe": "model", "state": "healthy"},
                    {"probe": "discord", "state": "healthy"},
                ]
            },
        ),
    )
    vault = _write_json(
        tmp_path / "vault.json",
        _capture(
            "vault",
            {
                "configured": True,
                "ready_for_auto_sync": True,
                "local_status": {
                    "last_success_ts": NOW - 60,
                    "last_archive_ts": NOW - 300,
                    "pending_snapshots": 0,
                    "pending_archives": 0,
                },
            },
        ),
    )
    lock = tmp_path / "alpecca.instance"
    _write_json(
        lock,
        {"version": 1, "pid": pid, "started_at": NOW - 500, "hostname": "not-reported"},
    )
    test_result = _write_json(
        tmp_path / "tests.json", _result("test", "core suite", counts={"passed": 359, "skipped": 2})
    )
    build_result = _write_json(tmp_path / "build.json", _result("build", "House HQ build"))

    def public_open(request, _timeout):
        if request.full_url == DISCOVERY_URL:
            return _HealthResponse(
                json.dumps(_discovery_document()).encode("utf-8"),
                final_url=DISCOVERY_URL,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        if request.full_url == CURRENT_MOBILE_ENDPOINT + "/healthz":
            return _HealthResponse(
                b'{"service":"alpecca","version":1}',
                final_url=CURRENT_MOBILE_ENDPOINT + "/healthz",
            )
        if request.full_url == APK_URL:
            return _HealthResponse(
                b"",
                final_url=APK_URL,
                headers={
                    "Content-Type": "application/vnd.android.package-archive",
                    "Content-Length": "1048576",
                    "ETag": '"reviewed-apk"',
                },
            )
        raise AssertionError(f"unexpected public request: {request.full_url}")

    report = ReleaseSoakHarness(
        clock=lambda: NOW,
        sleeper=lambda _seconds: pytest.fail("zero interval must not sleep"),
        health_probe=_healthy_endpoint,
        public_open=public_open,
    ).run(
        SoakConfig(
            health_url="http://127.0.0.1:8765/healthz",
            mobile_discovery_url=DISCOVERY_URL,
            mobile_apk_url=APK_URL,
            process_status_path=process,
            runtime_status_path=runtime,
            brain_graph_path=graph,
            vault_status_path=vault,
            instance_lock_path=lock,
            test_result_paths=(test_result,),
            build_result_paths=(build_result,),
            observations=2,
            interval_seconds=0,
        )
    )

    assert report["assessment"]["status"] == "observed_checks_passed"
    assert report["assessment"]["all_observed_checks_passed"] is True
    assert report["assessment"]["p14_completion_claim"] is False
    assert report["phase"]["completion_claim"] is False
    assert report["phase"]["status"] == "observation_only"
    assert len(report["observations"]) == 2
    assert all(item["stable_pass"] for item in report["check_summary"])
    assert _check(report, "one_instance_evidence")["evidence"]["active_coremind_count"] == 1
    assert _check(report, "model_availability")["evidence"]["reason_model"] == "qwen3.5:9b"
    assert _check(report, "mobile_discovery_continuity")["status"] == "pass"
    assert _check(report, "mobile_apk_metadata")["status"] == "pass"
    rendered = render_report(report)
    assert "not-reported" not in rendered
    assert "P14 completion" in rendered


def test_missing_evidence_stays_unknown_and_never_becomes_a_pass() -> None:
    report = ReleaseSoakHarness(clock=lambda: NOW).run(
        SoakConfig(health_url=None, instance_lock_path=None)
    )

    assert report["assessment"]["status"] == "insufficient_evidence"
    assert report["assessment"]["counts"] == {"fail": 0, "pass": 0, "unknown": 9}
    assert report["phase"]["completion_claim"] is False
    assert all(check["status"] == "unknown" for check in report["observations"][0]["checks"])


def test_duplicate_processes_and_conflicting_graph_evidence_fail_closed(tmp_path: Path) -> None:
    process = _write_json(
        tmp_path / "process.json", _process_status(coremind=[101, 102], discord=[201, 202])
    )
    runtime = _write_json(
        tmp_path / "runtime.json",
        _capture("runtime", {"models": {"chat_ready": True, "reason": "qwen3.5:9b"}}),
    )
    graph = _write_json(
        tmp_path / "graph.json",
        _capture(
            "brain_graph",
            {
                "nodes": [
                    {"probe": "model", "state": "degraded"},
                    {"probe": "discord", "state": "healthy"},
                ]
            },
        ),
    )
    report = ReleaseSoakHarness(clock=lambda: NOW, health_probe=_healthy_endpoint).run(
        SoakConfig(process_status_path=process, runtime_status_path=runtime, brain_graph_path=graph)
    )

    assert _check(report, "one_instance_evidence")["status"] == "fail"
    assert _check(report, "discord_process_presence")["status"] == "fail"
    assert _check(report, "model_availability")["status"] == "fail"
    assert report["assessment"]["status"] == "checks_failed"


def test_ready_runtime_with_unapproved_reason_model_fails(tmp_path: Path) -> None:
    runtime = _write_json(
        tmp_path / "runtime.json",
        _capture("runtime", {"models": {"chat_ready": True, "reason": "unexpected:latest"}}),
    )
    report = ReleaseSoakHarness(clock=lambda: NOW, health_probe=_healthy_endpoint).run(
        SoakConfig(runtime_status_path=runtime)
    )
    result = _check(report, "model_availability")

    assert result["status"] == "fail"
    assert result["evidence"]["approved_reason_model"] == "qwen3.5:9b"
    assert result["evidence"]["reason_model"] == "unexpected:latest"


class _HealthResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        final_url: str = "http://127.0.0.1:8765/healthz",
        headers: dict[str, str] | None = None,
    ):
        self.status = status
        self._body = body
        self._final_url = final_url
        self.headers = headers or {}
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._final_url

    def read(self, limit: int = -1) -> bytes:
        self.read_calls += 1
        return self._body[:limit]


def test_health_probe_is_exact_bounded_get_without_credentials() -> None:
    captured: dict[str, object] = {}

    def open_request(request, timeout):
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _HealthResponse(b'{"service":"alpecca","version":1}')

    result = probe_healthz(
        "http://127.0.0.1:8765/healthz", 0.5, open_request=open_request
    )

    assert result.status == "pass"
    assert captured["method"] == "GET"
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert captured["timeout"] == 0.5

    oversized = probe_healthz(
        "http://127.0.0.1:8765/healthz",
        0.5,
        open_request=lambda *_args: _HealthResponse(b"x" * 600),
    )
    redirected = probe_healthz(
        "http://127.0.0.1:8765/healthz",
        0.5,
        open_request=lambda *_args: _HealthResponse(
            b'{"service":"alpecca","version":1}', final_url="http://example.test/healthz"
        ),
    )
    assert oversized.status == "fail"
    assert redirected.status == "fail"


def test_mobile_discovery_checks_schema_expiry_and_localtunnel_health_without_credentials() -> None:
    requests: list[object] = []

    def open_request(request, _timeout):
        requests.append(request)
        if request.full_url == DISCOVERY_URL:
            return _HealthResponse(
                json.dumps(_discovery_document()).encode("utf-8"),
                final_url=DISCOVERY_URL,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        assert request.full_url == CURRENT_MOBILE_ENDPOINT + "/healthz"
        return _HealthResponse(
            b'{"service":"alpecca","version":1}',
            final_url=CURRENT_MOBILE_ENDPOINT + "/healthz",
        )

    result = probe_mobile_discovery(
        DISCOVERY_URL,
        0.5,
        NOW,
        open_request=open_request,
    )

    assert result.status == "pass"
    assert len(requests) == 2
    discovery_headers = {key.lower(): value for key, value in requests[0].header_items()}
    health_headers = {key.lower(): value for key, value in requests[1].header_items()}
    assert requests[0].get_method() == "GET"
    assert requests[1].get_method() == "GET"
    assert LOCALTUNNEL_BYPASS_HEADER not in discovery_headers
    assert health_headers[LOCALTUNNEL_BYPASS_HEADER] == LOCALTUNNEL_BYPASS_VALUE
    for headers in (discovery_headers, health_headers):
        assert "authorization" not in headers
        assert "cookie" not in headers
    assert result.evidence["current_endpoint"] == CURRENT_MOBILE_ENDPOINT
    assert result.evidence["current_endpoint_expires_in_seconds"] == 3_600
    assert result.evidence["localtunnel_bypass_header_used"] is True


@pytest.mark.parametrize(
    "document",
    (
        _discovery_document(endpoint="http://insecure.example"),
        _discovery_document(updated_at=int(NOW - 3_600), expires_at=int(NOW - 1)),
    ),
)
def test_mobile_discovery_rejects_insecure_or_expired_rows_before_endpoint_probe(
    document: dict,
) -> None:
    request_count = 0

    def open_request(request, _timeout):
        nonlocal request_count
        request_count += 1
        assert request.full_url == DISCOVERY_URL
        return _HealthResponse(
            json.dumps(document).encode("utf-8"),
            final_url=DISCOVERY_URL,
            headers={"Content-Type": "application/json"},
        )

    result = probe_mobile_discovery(DISCOVERY_URL, 0.5, NOW, open_request=open_request)

    assert result.status == "fail"
    assert request_count == 1
    assert result.evidence["schema_error"] in {"invalid_endpoint_value", "expired_endpoint"}


def test_mobile_discovery_rejects_redirected_public_object_without_following_endpoint() -> None:
    requests = 0

    def open_request(_request, _timeout):
        nonlocal requests
        requests += 1
        return _HealthResponse(
            json.dumps(_discovery_document()).encode("utf-8"),
            final_url="https://redirected.example/mobile/alpecca-endpoint.json",
            headers={"Content-Type": "application/json"},
        )

    result = probe_mobile_discovery(DISCOVERY_URL, 0.5, NOW, open_request=open_request)

    assert result.status == "fail"
    assert result.evidence["discovery_redirected"] is True
    assert requests == 1


def test_mobile_discovery_body_and_apk_size_metadata_are_bounded() -> None:
    discovery = probe_mobile_discovery(
        DISCOVERY_URL,
        0.5,
        NOW,
        open_request=lambda *_args: _HealthResponse(
            b"x" * (16 * 1024 + 1),
            final_url=DISCOVERY_URL,
            headers={"Content-Type": "application/json"},
        ),
    )
    apk = probe_mobile_apk_metadata(
        APK_URL,
        0.5,
        open_request=lambda *_args: _HealthResponse(
            b"",
            final_url=APK_URL,
            headers={
                "Content-Type": "application/vnd.android.package-archive",
                "Content-Length": str(128 * 1024 * 1024 + 1),
                "ETag": '"apk-etag"',
            },
        ),
    )

    assert discovery.status == "fail"
    assert discovery.evidence["discovery_response_bytes"] == 16 * 1024 + 1
    assert apk.status == "fail"
    assert apk.evidence["content_length"] == 128 * 1024 * 1024 + 1


def test_mobile_apk_uses_head_and_validates_bounded_public_metadata_without_body_read() -> None:
    captured: dict[str, object] = {}
    response = _HealthResponse(
        b"APK body must not be read",
        final_url=APK_URL,
        headers={
            "Content-Type": "application/vnd.android.package-archive",
            "Content-Length": "2097152",
            "ETag": '"apk-etag"',
            "Last-Modified": "Wed, 15 Jul 2026 20:00:00 GMT",
        },
    )

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return response

    result = probe_mobile_apk_metadata(APK_URL, 0.75, open_request=open_request)

    request = captured["request"]
    headers = {key.lower(): value for key, value in request.header_items()}
    assert result.status == "pass"
    assert request.get_method() == "HEAD"
    assert captured["timeout"] == 0.75
    assert response.read_calls == 0
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert result.evidence["content_length"] == 2_097_152
    assert result.evidence["etag"] == '"apk-etag"'


@pytest.mark.parametrize(
    "headers,final_url",
    (
        (
            {
                "Content-Type": "application/vnd.android.package-archive",
                "Content-Length": "1024",
            },
            APK_URL,
        ),
        (
            {
                "Content-Type": "application/octet-stream",
                "Content-Length": "1024",
                "ETag": '"apk-etag"',
            },
            APK_URL,
        ),
        (
            {
                "Content-Type": "application/vnd.android.package-archive",
                "Content-Length": "1024",
                "ETag": '"apk-etag"',
            },
            "https://redirected.example/mobile/AlpeccaLauncher-v2.1.0.apk",
        ),
    ),
)
def test_mobile_apk_metadata_fails_missing_or_wrong_metadata_and_redirects(
    headers: dict[str, str], final_url: str
) -> None:
    result = probe_mobile_apk_metadata(
        APK_URL,
        0.5,
        open_request=lambda *_args: _HealthResponse(
            b"",
            final_url=final_url,
            headers=headers,
        ),
    )

    assert result.status == "fail"


@pytest.mark.parametrize(
    "url",
    (
        "http://user:" + "password@127.0.0.1:8765/healthz",
        "http://127.0.0.1:8765/healthz?token=nope",
        "http://example.com/healthz",
        "http://127.0.0.1:8765/system/status",
        "file:///tmp/healthz",
    ),
)
def test_health_configuration_rejects_credentials_and_non_health_routes(url: str) -> None:
    with pytest.raises(ValueError):
        SoakConfig(health_url=url)


@pytest.mark.parametrize(
    "field,url",
    (
        ("mobile_discovery_url", "http://public.example/mobile/alpecca-endpoint.json"),
        (
            "mobile_discovery_url",
            "https://user:secret@public.example/mobile/alpecca-endpoint.json",
        ),
        (
            "mobile_discovery_url",
            "https://public.example/mobile/alpecca-endpoint.json?cache=no",
        ),
        ("mobile_apk_url", "http://public.example/mobile/AlpeccaLauncher.apk"),
        ("mobile_apk_url", "https://public.example/mobile/not-an-apk.json"),
    ),
)
def test_public_mobile_configuration_is_https_only_and_credential_free(
    field: str, url: str
) -> None:
    with pytest.raises(ValueError):
        SoakConfig(health_url=None, **{field: url})


def test_invalid_public_mobile_urls_never_reach_transport() -> None:
    def forbidden_transport(*_args):
        pytest.fail("policy-rejected public URLs must not reach the transport")

    discovery = probe_mobile_discovery(
        "http://public.example/mobile/alpecca-endpoint.json",
        0.5,
        NOW,
        open_request=forbidden_transport,
    )
    apk = probe_mobile_apk_metadata(
        "http://public.example/mobile/AlpeccaLauncher.apk",
        0.5,
        open_request=forbidden_transport,
    )

    assert discovery.status == "unknown"
    assert apk.status == "unknown"


def test_stale_vault_and_pending_outbox_are_reported_as_failures(tmp_path: Path) -> None:
    stale = _write_json(
        tmp_path / "stale-vault.json",
        _capture(
            "vault",
            {
                "configured": True,
                "ready_for_auto_sync": True,
                "local_status": {
                    "last_success_ts": NOW - 901,
                    "last_archive_ts": NOW - 100,
                    "pending_snapshots": 1,
                    "pending_archives": 0,
                },
            },
        ),
    )
    report = ReleaseSoakHarness(clock=lambda: NOW, health_probe=_healthy_endpoint).run(
        SoakConfig(vault_status_path=stale)
    )
    result = _check(report, "vault_freshness")

    assert result["status"] == "fail"
    assert result["evidence"]["snapshot_freshness"] == "stale"
    assert result["evidence"]["pending_snapshots"] == 1


def test_vault_missing_auto_sync_readiness_remains_unknown(tmp_path: Path) -> None:
    vault = _write_json(
        tmp_path / "vault.json",
        _capture(
            "vault",
            {
                "configured": True,
                "local_status": {
                    "last_success_ts": NOW - 60,
                    "last_archive_ts": NOW - 100,
                    "pending_snapshots": 0,
                    "pending_archives": 0,
                },
            },
        ),
    )
    report = ReleaseSoakHarness(clock=lambda: NOW, health_probe=_healthy_endpoint).run(
        SoakConfig(vault_status_path=vault)
    )

    assert _check(report, "vault_freshness")["status"] == "unknown"


def test_sensitive_status_fields_are_rejected_and_never_echoed(tmp_path: Path) -> None:
    runtime = _write_json(
        tmp_path / "runtime.json",
        {
            "models": {"chat_ready": True, "reason": "qwen3.5:9b"},
            "token": "must-never-appear-in-report",
        },
    )
    report = ReleaseSoakHarness(clock=lambda: NOW, health_probe=_healthy_endpoint).run(
        SoakConfig(runtime_status_path=runtime)
    )
    result = _check(report, "model_availability")
    rendered = render_report(report)

    assert result["status"] == "unknown"
    assert result["evidence"]["runtime_error"] == "sensitive_field_rejected"
    assert "must-never-appear-in-report" not in rendered


def test_result_receipts_ingest_success_failure_and_staleness_without_running_commands(
    tmp_path: Path,
) -> None:
    passing = _write_json(
        tmp_path / "passing.json", _result("test", "focused tests", counts={"passed": 12})
    )
    failing = _write_json(
        tmp_path / "failing.json",
        _result("test", "core tests", exit_code=1, counts={"passed": 10, "failed": 1}),
    )
    stale_build = _write_json(
        tmp_path / "stale-build.json",
        _result("build", "House HQ build", finished_at=NOW - 86_401),
    )
    report = ReleaseSoakHarness(clock=lambda: NOW, health_probe=_healthy_endpoint).run(
        SoakConfig(
            test_result_paths=(passing, failing),
            build_result_paths=(stale_build,),
        )
    )

    tests = _check(report, "test_result_ingestion")
    build = _check(report, "build_result_ingestion")
    assert tests["status"] == "fail"
    assert tests["evidence"]["failed_names"] == ["core tests"]
    assert tests["evidence"]["reported_passed_tests"] == 22
    assert build["status"] == "unknown"
    assert build["evidence"]["stale_names"] == ["House HQ build"]


def test_duplicate_result_names_do_not_inflate_evidence(tmp_path: Path) -> None:
    first = _write_json(tmp_path / "first.json", _result("build", "House HQ build"))
    second = _write_json(tmp_path / "second.json", _result("build", "House HQ build"))
    report = ReleaseSoakHarness(clock=lambda: NOW, health_probe=_healthy_endpoint).run(
        SoakConfig(build_result_paths=(first, second))
    )
    result = _check(report, "build_result_ingestion")

    assert result["status"] == "unknown"
    assert result["evidence"]["duplicate_names"] == ["House HQ build"]


def test_observation_and_duration_bounds_are_enforced() -> None:
    with pytest.raises(ValueError, match="observations"):
        SoakConfig(observations=1_441)
    with pytest.raises(ValueError, match="window"):
        SoakConfig(observations=200, interval_seconds=3_600)
    with pytest.raises(ValueError, match="test result"):
        SoakConfig(test_result_paths=tuple(Path(str(index)) for index in range(17)))


def test_cli_writes_an_honest_report_without_requiring_live_evidence(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    exit_code = soak_cli.main(
        [
            "--offline-evidence-only",
            "--ignore-instance-lock",
            "--output",
            str(output),
            "--compact",
        ]
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["assessment"]["status"] == "insufficient_evidence"
    assert report["phase"]["completion_claim"] is False


def test_cli_defaults_to_reviewed_public_mobile_objects() -> None:
    args = soak_cli.build_parser().parse_args([])

    assert args.mobile_discovery_url == DEFAULT_MOBILE_DISCOVERY_URL
    assert args.mobile_apk_url == DEFAULT_MOBILE_APK_URL


def test_harness_source_has_no_runtime_control_or_command_execution() -> None:
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(
        (root / "scripts" / "release_soak" / name).read_text(encoding="utf-8")
        for name in ("core.py", "cli.py")
    )

    assert "import subprocess" not in source
    assert "Popen(" not in source
    assert ".terminate(" not in source
    assert ".kill(" not in source
    assert "import server" not in source
    assert "from alpecca" not in source
    assert 'method="POST"' not in source
    assert 'method="GET"' in source
    assert 'method="HEAD"' in source
