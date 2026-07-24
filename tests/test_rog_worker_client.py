from __future__ import annotations

from io import BytesIO
import hashlib
import hmac
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest

from alpecca import rog_worker_client as rog


SECRET = "worker-secret-0123456789-abcdefghijklmnopqrstuvwxyz"
SECRET_BYTES = SECRET.encode("utf-8")
BASE_URL = "https://Jason_HOLYROG:8788"
MAGICDNS_BASE_URL = "https://jason-holyrog.tailda0108.ts.net:8788"
TEST_CA = Path(__file__).resolve()
REQUEST_ID = "request-00000001"
NONCE = "nonce-0000000000000001"
NOW = 1_721_600_000


class Response:
    def __init__(
        self,
        payload: object | bytes,
        *,
        url: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
        include_content_length: bool = True,
    ) -> None:
        self.body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        self.status = status
        self.url = url
        self.headers = {"Content-Type": "application/json; charset=utf-8"}
        if include_content_length:
            self.headers["Content-Length"] = str(len(self.body))
        self.headers.update(headers or {})
        self.closed = False
        self.read_sizes: list[int] = []

    def geturl(self) -> str:
        return self.url

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self.body[:size]

    def close(self) -> None:
        self.closed = True


def make_client(opener, **kwargs) -> rog.RogWorkerClient:
    return rog.RogWorkerClient(
        BASE_URL,
        SECRET,
        ca_cert=TEST_CA,
        opener=opener,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
        request_id_factory=lambda: REQUEST_ID,
        **kwargs,
    )


def health_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": rog.HEALTH_SCHEMA,
        "ok": True,
        "request_id": REQUEST_ID,
        "hostname": "Jason_HOLYROG",
        "role": "compute-only",
        "ready": True,
        "speaking": False,
        "discord": False,
        "capabilities": {
            "reasoning": {"ready": True},
            "blender": {"ready": False},
        },
    }
    payload.update(overrides)
    return payload


def reasoning_response(
    text: str = "done",
    **result_overrides: object,
) -> dict[str, object]:
    result: dict[str, object] = {
        "model": "qwen3.5:9b",
        "text": text,
        "elapsed_ms": 12,
    }
    result.update(result_overrides)
    return {
        "schema": rog.REASON_RESPONSE_SCHEMA,
        "ok": True,
        "request_id": REQUEST_ID,
        "result": result,
    }


def blender_response(
    *,
    frame: int = 1,
    artifact_name: str | None = None,
) -> dict[str, object]:
    name = artifact_name or f"render-{REQUEST_ID}-{frame:06d}.png"
    return {
        "schema": rog.BLENDER_RESPONSE_SCHEMA,
        "ok": True,
        "request_id": REQUEST_ID,
        "result": {
            "job_id": "render-0123456789abcdef",
            "frame": frame,
            "status": "completed",
            "artifact": {
                "id": "artifact-0123456789abcdef",
                "name": name,
                "sha256": "a" * 64,
                "bytes": 4096,
            },
            "elapsed_ms": 34,
        },
    }


def header_map(request) -> dict[str, str]:
    return {name.lower(): value for name, value in request.header_items()}


def test_canonical_request_and_signature_match_worker_five_line_contract() -> None:
    body = b'{"model":"qwen3.5:9b"}'
    digest = hashlib.sha256(body).hexdigest()
    canonical = rog.canonical_request(
        "POST",
        rog.REASON_PATH,
        NOW,
        NONCE,
        body,
    )

    assert canonical == (
        "POST\n"
        "/v1/reason\n"
        "1721600000\n"
        "nonce-0000000000000001\n"
        f"{digest}"
    ).encode("utf-8")
    assert rog.sign_request(
        SECRET,
        "POST",
        rog.REASON_PATH,
        NOW,
        NONCE,
        body,
    ) == hmac.new(SECRET_BYTES, canonical, hashlib.sha256).hexdigest()


def test_health_uses_exact_server_headers_endpoint_and_compute_only_shape() -> None:
    captured: dict[str, object] = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response(health_payload(), url=request.full_url)

    result = make_client(opener).health()

    assert result.request_id == REQUEST_ID
    assert result.hostname == "Jason_HOLYROG"
    assert result.ready is True
    assert result.reasoning_ready is True
    assert result.blender_ready is False
    request = captured["request"]
    assert request.full_url == BASE_URL + rog.HEALTH_PATH
    assert request.get_method() == "GET"
    assert request.data is None
    headers = header_map(request)
    assert headers[rog.TIMESTAMP_HEADER.lower()] == str(NOW)
    assert headers[rog.NONCE_HEADER.lower()] == NONCE
    assert headers[rog.BODY_SHA256_HEADER.lower()] == hashlib.sha256(b"").hexdigest()
    assert headers[rog.REQUEST_ID_HEADER.lower()] == REQUEST_ID
    assert headers[rog.SIGNATURE_HEADER.lower()] == rog.sign_request(
        SECRET,
        "GET",
        rog.HEALTH_PATH,
        NOW,
        NONCE,
        b"",
    )
    assert captured["timeout"] == 2.0


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"hostname": "other-host"}, "hostname"),
        ({"role": "primary"}, "compute-only"),
        ({"speaking": True}, "compute-only"),
        ({"discord": True}, "compute-only"),
        ({"ready": False}, "readiness"),
        (
            {"capabilities": {"reasoning": True, "blender": {"ready": False}}},
            "reasoning",
        ),
    ],
)
def test_health_rejects_identity_role_and_nested_contract_mismatches(
    overrides,
    match,
) -> None:
    worker = make_client(
        lambda request, timeout: Response(
            health_payload(**overrides),
            url=request.full_url,
        )
    )
    with pytest.raises(rog.RogWorkerProtocolError, match=match):
        worker.health()


def test_health_rejects_unknown_response_fields() -> None:
    worker = make_client(
        lambda request, timeout: Response(
            {**health_payload(), "unexpected": "not accepted"},
            url=request.full_url,
        )
    )
    with pytest.raises(rog.RogWorkerProtocolError, match="fields"):
        worker.health()


def test_reason_sends_structured_server_contract_and_parses_nested_result() -> None:
    captured: dict[str, object] = {}

    def opener(request, timeout):
        captured["request"] = request
        return Response(
            reasoning_response(
                "A bounded answer.",
                prompt_tokens=27,
                completion_tokens=8,
                elapsed_ms=41,
            ),
            url=request.full_url,
        )

    result = make_client(opener).reason(
        "Be concise.",
        "Compare the two render passes.",
        history=[
            {"role": "user", "content": "First pass?"},
            {"role": "assistant", "content": "It had artifacts."},
        ],
        max_tokens=256,
    )

    assert result.text == "A bounded answer."
    assert result.model == "qwen3.5:9b"
    assert result.prompt_tokens == 27
    assert result.completion_tokens == 8
    assert result.elapsed_ms == 41
    request = captured["request"]
    assert request.full_url == BASE_URL + rog.REASON_PATH
    assert request.get_method() == "POST"
    payload = json.loads(request.data)
    assert set(payload) == {
        "schema",
        "request_id",
        "model",
        "system_prompt",
        "user_prompt",
        "history",
        "max_tokens",
    }
    assert payload["schema"] == rog.REASON_REQUEST_SCHEMA
    assert payload["request_id"] == REQUEST_ID
    assert payload["model"] == "qwen3.5:9b"
    assert payload["system_prompt"] == "Be concise."
    assert payload["user_prompt"] == "Compare the two render passes."
    assert payload["max_tokens"] == 256
    assert payload["history"] == [
        {"role": "user", "content": "First pass?"},
        {"role": "assistant", "content": "It had artifacts."},
    ]
    headers = header_map(request)
    assert headers[rog.BODY_SHA256_HEADER.lower()] == hashlib.sha256(
        request.data
    ).hexdigest()
    assert headers[rog.REQUEST_ID_HEADER.lower()] == REQUEST_ID
    assert headers[rog.SIGNATURE_HEADER.lower()] == rog.sign_request(
        SECRET,
        "POST",
        rog.REASON_PATH,
        NOW,
        NONCE,
        request.data,
    )


def test_reason_without_history_sends_required_empty_fields() -> None:
    captured = {}

    def opener(request, timeout):
        captured["payload"] = json.loads(request.data)
        return Response(
            reasoning_response(),
            url=request.full_url,
        )

    make_client(opener).reason("", "Direct prompt")
    assert captured["payload"]["user_prompt"] == "Direct prompt"
    assert captured["payload"]["system_prompt"] == ""
    assert captured["payload"]["history"] == []


def test_reason_enforces_server_model_prompt_history_and_token_bounds() -> None:
    worker = make_client(
        lambda *args, **kwargs: pytest.fail("network must not run")
    )
    invalid_calls = (
        lambda: worker.reason("system", ""),
        lambda: worker.reason("system", "prompt", model="other:9b"),
        lambda: worker.reason("system", "prompt", max_tokens=0),
        lambda: worker.reason("system", "prompt", max_tokens=2049),
        lambda: worker.reason(
            "system",
            "prompt",
            history=[{"role": "system", "content": "not allowed"}],
        ),
        lambda: worker.reason(
            "system",
            "prompt",
            history=[{"role": "user", "content": "ok", "extra": "no"}],
        ),
    )
    for call in invalid_calls:
        with pytest.raises(rog.RogWorkerConfigurationError):
            call()


def test_reason_result_repr_does_not_expose_generated_text() -> None:
    private_result = "credential-like-output-must-not-appear"
    worker = make_client(
        lambda request, timeout: Response(
            reasoning_response(private_result),
            url=request.full_url,
        )
    )
    result = worker.reason("system", "question")
    assert private_result not in repr(result)


def test_render_blender_matches_basename_only_server_contract_and_artifact() -> None:
    captured: dict[str, object] = {}

    def opener(request, timeout):
        captured["request"] = request
        return Response(
            blender_response(frame=12),
            url=request.full_url,
        )

    result = make_client(opener).render_blender("Alpecca Scene.blend", frame=12)

    assert result.frame == 12
    assert result.job_id == "render-0123456789abcdef"
    assert result.status == "completed"
    assert result.artifact_id == "artifact-0123456789abcdef"
    assert result.artifact_name == f"render-{REQUEST_ID}-000012.png"
    assert result.artifact_sha256 == "a" * 64
    assert result.artifact_bytes == 4096
    assert result.elapsed_ms == 34
    request = captured["request"]
    assert request.full_url == BASE_URL + rog.BLENDER_PATH
    assert json.loads(request.data) == {
        "schema": rog.BLENDER_REQUEST_SCHEMA,
        "request_id": REQUEST_ID,
        "project": "Alpecca Scene.blend",
        "frame": 12,
    }
    headers = header_map(request)
    assert headers[rog.BODY_SHA256_HEADER.lower()] == hashlib.sha256(
        request.data
    ).hexdigest()
    assert headers[rog.REQUEST_ID_HEADER.lower()] == REQUEST_ID


@pytest.mark.parametrize(
    "project",
    [
        "../secret.blend",
        "folder/scene.blend",
        r"folder\scene.blend",
        "C:scene.blend",
        "/absolute.blend",
        "scene.py",
        "",
    ],
)
def test_render_blender_rejects_paths_outside_worker_approved_root(project) -> None:
    worker = make_client(
        lambda *args, **kwargs: pytest.fail("network must not run")
    )
    with pytest.raises(rog.RogWorkerConfigurationError):
        worker.render_blender(project)


def test_render_blender_rejects_frame_zero_before_network() -> None:
    worker = make_client(
        lambda *args, **kwargs: pytest.fail("network must not run")
    )
    with pytest.raises(rog.RogWorkerConfigurationError, match="frame"):
        worker.render_blender("scene.blend", frame=0)


def test_render_blender_rejects_artifact_traversal() -> None:
    worker = make_client(
        lambda request, timeout: Response(
            blender_response(frame=1, artifact_name="../escaped.png"),
            url=request.full_url,
        )
    )
    with pytest.raises(rog.RogWorkerProtocolError, match="artifact name"):
        worker.render_blender("scene.blend", frame=1)


def test_environment_uses_tls_holyrog_default_and_primary_ca_file(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(health_payload(), url=request.full_url)

    worker = rog.RogWorkerClient.from_environment(
        {
            rog.SECRET_ENV: SECRET,
            rog.CA_CERT_ENV: str(TEST_CA),
        },
        opener=opener,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
        request_id_factory=lambda: REQUEST_ID,
    )
    assert worker.health().ready is True
    assert calls == [MAGICDNS_BASE_URL + rog.HEALTH_PATH]
    with pytest.raises(rog.RogWorkerConfigurationError, match="certificate"):
        rog.RogWorkerClient.from_environment(
            {
                rog.SECRET_ENV: SECRET,
                "LOCALAPPDATA": str(tmp_path / "missing-local-app-data"),
            }
        )


def test_environment_timeout_canonical_precedes_compatibility_and_caps_at_180() -> None:
    captured: list[float] = []

    def opener(request, timeout):
        captured.append(timeout)
        return Response(
            reasoning_response(),
            url=request.full_url,
        )

    common = {
        rog.SECRET_ENV: SECRET,
        rog.URL_ENV: BASE_URL,
        rog.CA_CERT_ENV: str(TEST_CA),
    }
    canonical = rog.RogWorkerClient.from_environment(
        {
            **common,
            rog.TIMEOUT_ENV: "170",
            rog.TIMEOUT_COMPAT_ENV: "not-used",
        },
        opener=opener,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
        request_id_factory=lambda: REQUEST_ID,
    )
    compatibility = rog.RogWorkerClient.from_environment(
        {**common, rog.TIMEOUT_COMPAT_ENV: "160"},
        opener=opener,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
        request_id_factory=lambda: REQUEST_ID,
    )
    canonical.reason("", "canonical")
    compatibility.reason("", "compatibility")
    assert captured == [170.0, 160.0]
    assert rog.RogWorkerClient(
        BASE_URL,
        SECRET,
        timeout_seconds=180,
        ca_cert=TEST_CA,
        opener=lambda *args, **kwargs: None,
    )
    with pytest.raises(rog.RogWorkerConfigurationError):
        rog.RogWorkerClient(
            BASE_URL, SECRET, timeout_seconds=180.01, ca_cert=TEST_CA
        )


def test_operation_timeouts_are_independent_and_bounded() -> None:
    captured: list[tuple[str, float]] = []

    def opener(request, timeout):
        path = urlsplit(request.full_url).path
        captured.append((path, timeout))
        if path == rog.HEALTH_PATH:
            payload = health_payload()
        elif path == rog.REASON_PATH:
            payload = reasoning_response()
        else:
            payload = blender_response()
        return Response(payload, url=request.full_url)

    worker = rog.RogWorkerClient.from_environment(
        {
            rog.SECRET_ENV: SECRET,
            rog.URL_ENV: BASE_URL,
            rog.CA_CERT_ENV: str(TEST_CA),
            rog.HEALTH_TIMEOUT_ENV: "4",
            rog.REASON_TIMEOUT_ENV: "175",
            rog.RENDER_TIMEOUT_ENV: "800",
        },
        opener=opener,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
        request_id_factory=lambda: REQUEST_ID,
    )
    worker.health()
    worker.reason("", "reason")
    worker.render_blender("scene.blend")
    assert captured == [
        (rog.HEALTH_PATH, 4.0),
        (rog.REASON_PATH, 175.0),
        (rog.BLENDER_PATH, 800.0),
    ]
    assert rog.RogWorkerClient(
        BASE_URL,
        SECRET,
        ca_cert=TEST_CA,
        health_timeout_seconds=5,
        reason_timeout_seconds=180,
        render_timeout_seconds=900,
        opener=lambda *args, **kwargs: None,
    )
    for kwargs in (
        {"health_timeout_seconds": 5.01},
        {"reason_timeout_seconds": 180.01},
        {"render_timeout_seconds": 900.01},
    ):
        with pytest.raises(rog.RogWorkerConfigurationError):
            rog.RogWorkerClient(BASE_URL, SECRET, ca_cert=TEST_CA, **kwargs)


def test_environment_reads_exact_windows_credential_without_creating_it() -> None:
    class FakeCredentialManager:
        CRED_TYPE_GENERIC = 1

        def __init__(self) -> None:
            self.reads: list[tuple[str, int, int]] = []
            self.writes = 0

        def CredRead(self, target, credential_type, flags):
            self.reads.append((target, credential_type, flags))
            return {"CredentialBlob": SECRET.encode("utf-16-le")}

        def CredWrite(self, *_args, **_kwargs):
            self.writes += 1
            raise AssertionError("client must never create a credential")

    credential = FakeCredentialManager()
    target = "Alpecca/Test/ExactROGTarget"
    worker = rog.RogWorkerClient.from_environment(
        {
            rog.URL_ENV: BASE_URL,
            rog.CREDENTIAL_TARGET_ENV: target,
            rog.CA_CERT_ENV: str(TEST_CA),
        },
        opener=lambda request, timeout: Response(
            health_payload(),
            url=request.full_url,
        ),
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
        request_id_factory=lambda: REQUEST_ID,
        win32cred_module=credential,
    )
    assert worker.health().ready is True
    assert credential.reads == [(target, 1, 0)]
    assert credential.writes == 0
    assert SECRET not in repr(worker)


def test_missing_windows_credential_is_not_created() -> None:
    class MissingCredentialError(Exception):
        winerror = 1168

    class MissingCredentialManager:
        CRED_TYPE_GENERIC = 1

        def __init__(self) -> None:
            self.reads = 0
            self.writes = 0

        def CredRead(self, *_args):
            self.reads += 1
            raise MissingCredentialError()

        def CredWrite(self, *_args, **_kwargs):
            self.writes += 1

    credential = MissingCredentialManager()
    with pytest.raises(rog.RogWorkerConfigurationError, match="unavailable"):
        rog.RogWorkerClient.from_environment(
            {
                rog.URL_ENV: BASE_URL,
                rog.CREDENTIAL_TARGET_ENV: "Alpecca/Missing/ROG",
                rog.CA_CERT_ENV: str(TEST_CA),
            },
            win32cred_module=credential,
        )
    assert credential.reads == 1
    assert credential.writes == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:8788",
        "http://public.example.test:8788",
        "http://8.8.8.8:8788",
    ],
)
def test_non_loopback_http_is_refused_even_with_legacy_opt_in(url: str) -> None:
    with pytest.raises(rog.RogWorkerConfigurationError, match="authenticated TLS"):
        rog.RogWorkerClient(
            url,
            SECRET,
            allow_private_lan_http=True,
            opener=lambda *args, **kwargs: None,
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://Jason_HOLYROG:8788",
        "http://192.168.12.165:8788",
        "http://rog-worker.local:8788",
    ],
)
def test_legacy_lan_flag_cannot_enable_private_lan_http(url: str) -> None:
    with pytest.raises(rog.RogWorkerConfigurationError, match="authenticated TLS"):
        rog.RogWorkerClient(
            url,
            SECRET,
            allow_private_lan_http=True,
            opener=lambda *args, **kwargs: None,
        )


def test_loopback_http_remains_available_for_local_smoke() -> None:
    worker = rog.RogWorkerClient(
        "http://127.0.0.1:8788",
        SECRET,
        opener=lambda *args, **kwargs: None,
    )
    assert "http://127.0.0.1:8788" in repr(worker)


def test_remote_https_requires_exact_worker_dns_and_ca_file() -> None:
    with pytest.raises(rog.RogWorkerConfigurationError, match="certificate"):
        rog.RogWorkerClient(BASE_URL, SECRET, opener=lambda *args, **kwargs: None)
    with pytest.raises(rog.RogWorkerConfigurationError, match="MagicDNS or legacy"):
        rog.RogWorkerClient(
            "https://192.168.12.165:8788",
            SECRET,
            ca_cert=TEST_CA,
            opener=lambda *args, **kwargs: None,
        )


def test_magicdns_is_the_preferred_default_and_legacy_dns_remains_accepted() -> None:
    assert rog.DEFAULT_BASE_URL == MAGICDNS_BASE_URL
    assert rog.MAGICDNS_HOSTNAME == "jason-holyrog.tailda0108.ts.net"

    magicdns = rog.RogWorkerClient(
        MAGICDNS_BASE_URL,
        SECRET,
        ca_cert=TEST_CA,
        opener=lambda *args, **kwargs: None,
    )
    legacy = rog.RogWorkerClient(
        BASE_URL,
        SECRET,
        ca_cert=TEST_CA,
        opener=lambda *args, **kwargs: None,
    )

    assert MAGICDNS_BASE_URL in repr(magicdns)
    assert BASE_URL in repr(legacy)


def test_environment_without_url_routes_requests_to_magicdns() -> None:
    calls: list[str] = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(health_payload(), url=request.full_url)

    worker = rog.RogWorkerClient.from_environment(
        {
            rog.SECRET_ENV: SECRET,
            rog.CA_CERT_ENV: str(TEST_CA),
        },
        opener=opener,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
        request_id_factory=lambda: REQUEST_ID,
    )
    assert worker.health().ready is True
    assert calls == [MAGICDNS_BASE_URL + rog.HEALTH_PATH]


def test_default_https_opener_enforces_ca_hostname_and_tls12(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class Context:
        check_hostname = False
        verify_mode = None
        minimum_version = None

    context = Context()

    def create_default_context(*, purpose, cafile):
        observed["purpose"] = purpose
        observed["cafile"] = cafile
        return context

    class BuiltOpener:
        def open(self, request, timeout):
            raise AssertionError("network was not expected")

    def build_opener(*handlers):
        observed["handlers"] = handlers
        return BuiltOpener()

    monkeypatch.setattr(rog.ssl, "create_default_context", create_default_context)
    monkeypatch.setattr(rog, "build_opener", build_opener)
    rog.RogWorkerClient(BASE_URL, SECRET, ca_cert=TEST_CA)

    assert observed["purpose"] is rog.ssl.Purpose.SERVER_AUTH
    assert observed["cafile"] == str(TEST_CA)
    assert context.check_hostname is True
    assert context.verify_mode == rog.ssl.CERT_REQUIRED
    assert context.minimum_version == rog.ssl.TLSVersion.TLSv1_2


@pytest.mark.parametrize(
    "url",
    [
        "https://" + "user:" + "password@" + "Jason_HOLYROG:8788",
        "https://Jason_HOLYROG:8788/api",
        "https://Jason_HOLYROG:8788?target=other",
        "https://Jason_HOLYROG:8788#fragment",
    ],
)
def test_worker_origin_rejects_credentials_paths_queries_and_fragments(url) -> None:
    with pytest.raises(rog.RogWorkerConfigurationError, match="exact origin"):
        rog.RogWorkerClient(
            url,
            SECRET,
            ca_cert=TEST_CA,
            opener=lambda *args, **kwargs: None,
        )


def test_redirected_or_changed_response_target_is_rejected() -> None:
    worker = make_client(
        lambda request, timeout: Response(
            health_payload(),
            url="https://other.example.test/v1/health",
        )
    )
    with pytest.raises(rog.RogWorkerProtocolError, match="target changed"):
        worker.health()
    assert rog._NoRedirect().redirect_request(None, None, 302, "", {}, "x") is None


def test_declared_and_streamed_response_limits_are_enforced() -> None:
    declared = make_client(
        lambda request, timeout: Response(
            b"{}",
            url=request.full_url,
            headers={"Content-Length": "1025"},
        ),
        max_response_bytes=1024,
    )
    with pytest.raises(rog.RogWorkerResponseTooLargeError):
        declared.health()

    streamed = make_client(
        lambda request, timeout: Response(
            b"x" * 1025,
            url=request.full_url,
            include_content_length=False,
        ),
        max_response_bytes=1024,
    )
    with pytest.raises(rog.RogWorkerResponseTooLargeError):
        streamed.health()


def test_http_and_transport_errors_are_typed_and_redacted() -> None:
    leaked = "secret-response-detail"

    def auth_failure(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            leaked,
            {},
            BytesIO((SECRET + leaked).encode("utf-8")),
        )

    def transport_failure(request, timeout):
        raise URLError(SECRET + leaked)

    with pytest.raises(rog.RogWorkerAuthenticationError) as auth_error:
        make_client(auth_failure).health()
    with pytest.raises(rog.RogWorkerTransportError) as transport_error:
        make_client(transport_failure).health()
    combined = repr(auth_error.value) + repr(transport_error.value)
    assert SECRET not in combined
    assert leaked not in combined


def test_client_repr_and_configuration_errors_never_expose_secret() -> None:
    worker = make_client(lambda *args, **kwargs: None)
    assert SECRET not in repr(worker)
    assert "<redacted>" in repr(worker)
    with pytest.raises(rog.RogWorkerConfigurationError) as captured:
        rog.RogWorkerClient(
            BASE_URL,
            SECRET + ("x" * 600),
            ca_cert=TEST_CA,
        )
    assert SECRET not in repr(captured.value)


def test_response_content_type_encoding_length_and_exact_fields_are_strict() -> None:
    cases = (
        Response(
            health_payload(),
            url=BASE_URL + rog.HEALTH_PATH,
            headers={"Content-Type": "text/html"},
        ),
        Response(
            health_payload(),
            url=BASE_URL + rog.HEALTH_PATH,
            headers={"Content-Encoding": "gzip"},
        ),
        Response(
            health_payload(),
            url=BASE_URL + rog.HEALTH_PATH,
            headers={"Content-Length": "1"},
        ),
    )
    for response in cases:
        worker = make_client(lambda request, timeout, response=response: response)
        with pytest.raises(rog.RogWorkerProtocolError):
            worker.health()
        assert response.closed


def test_client_reason_round_trip_matches_actual_worker_server_contract() -> None:
    from fastapi.testclient import TestClient

    from alpecca import rog_worker_server as server

    class UpstreamResponse:
        status = 200

        def read(self, limit):
            return json.dumps(
                {"message": {"content": "server-aligned answer"}}
            ).encode("utf-8")[:limit]

    class UpstreamConnection:
        def request(self, method, path, body=None, headers=None):
            self.request_record = (method, path, body, headers)

        def getresponse(self):
            return UpstreamResponse()

        def close(self):
            pass

    def connection_factory(host, port, *, timeout):
        assert (host, port) == ("127.0.0.1", 11434)
        return UpstreamConnection()

    settings = server.WorkerSettings(
        secret=SECRET_BYTES,
        model_allowlist=frozenset({"qwen3.5:9b"}),
    )
    app_client = TestClient(
        server.create_app(
            settings,
            clock=lambda: NOW,
            connection_factory=connection_factory,
        ),
        base_url=BASE_URL,
    )

    def opener(request, timeout):
        parsed = urlsplit(request.full_url)
        transported_headers = dict(request.header_items())
        lowered = {key.lower(): value for key, value in transported_headers.items()}
        assert lowered[rog.NONCE_HEADER.lower()] == NONCE
        assert lowered[rog.TIMESTAMP_HEADER.lower()] == str(NOW)
        assert lowered[rog.SIGNATURE_HEADER.lower()] == server.sign_request(
            SECRET_BYTES,
            request.get_method(),
            parsed.path,
            str(NOW),
            NONCE,
            request.data,
        )
        response = app_client.request(
            request.get_method(),
            parsed.path,
            content=request.data,
            headers=transported_headers,
        )
        if response.status_code >= 400:
            raise HTTPError(
                request.full_url,
                response.status_code,
                response.text,
                response.headers,
                BytesIO(response.content),
            )
        return Response(
            response.content,
            url=request.full_url,
            status=response.status_code,
            headers=dict(response.headers),
        )

    worker = make_client(opener)
    result = worker.reason("Stay grounded.", "What is the bounded result?")
    assert result.text == "server-aligned answer"
    assert result.model == "qwen3.5:9b"
    assert result.elapsed_ms >= 0
