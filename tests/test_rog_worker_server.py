from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from alpecca import rog_worker_server as worker_mod


SECRET = b"r" * 32
NOW = 1_800_000_000


def make_settings(**overrides) -> worker_mod.WorkerSettings:
    settings = worker_mod.WorkerSettings(
        secret=SECRET,
        model_allowlist=frozenset({"qwen3.5:9b"}),
        max_body_bytes=4096,
        max_prompt_chars=512,
        max_system_chars=128,
        max_history_messages=4,
        max_history_chars=96,
        max_result_chars=256,
        max_ollama_response_bytes=4096,
        max_render_bytes=4096,
        max_tokens=256,
        ollama_num_ctx=8192,
        reason_timeout_seconds=5.0,
        render_timeout_seconds=5.0,
        timestamp_skew_seconds=90,
        idempotency_ttl_seconds=600,
        idempotency_entries=16,
    )
    return replace(settings, **overrides)


def encoded(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def request_id_from_body(body: bytes) -> str:
    if not body:
        return "request-health-001"
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return "request-body-001"
    return str(value.get("request_id", "request-body-001"))


def signed_headers(
    method: str,
    path: str,
    body: bytes = b"",
    *,
    nonce: str = "nonce-0000000000000001",
    timestamp: int = NOW,
    secret: bytes = SECRET,
    request_id: str | None = None,
) -> dict[str, str]:
    return {
        worker_mod.TIMESTAMP_HEADER: str(timestamp),
        worker_mod.NONCE_HEADER: nonce,
        worker_mod.BODY_SHA256_HEADER: hashlib.sha256(body).hexdigest(),
        worker_mod.SIGNATURE_HEADER: worker_mod.sign_request(
            secret, method, path, timestamp, nonce, body
        ),
        worker_mod.REQUEST_ID_HEADER: request_id or request_id_from_body(body),
        "Content-Type": "application/json; charset=utf-8",
    }


def reason_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": worker_mod.REASON_REQUEST_SCHEMA,
        "request_id": "request-reason-001",
        "system_prompt": "Be grounded.",
        "user_prompt": "Compare the options.",
        "history": [
            {"role": "user", "content": "Earlier question."},
            {"role": "assistant", "content": "Earlier answer."},
        ],
        "model": "qwen3.5:9b",
        "max_tokens": 90,
    }
    payload.update(overrides)
    return payload


def blender_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": worker_mod.BLENDER_REQUEST_SCHEMA,
        "request_id": "request-render-001",
        "project": "scene.blend",
        "frame": 12,
    }
    payload.update(overrides)
    return payload


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class FakeConnection:
    def __init__(self, response: FakeResponse, calls: list[dict[str, object]]) -> None:
        self.response = response
        self.calls = calls
        self.closed = False

    def request(self, method, path, body=None, headers=None) -> None:
        self.calls.append(
            {"method": method, "path": path, "body": body, "headers": headers}
        )

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class ConnectionFactory:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.response_body = json.dumps(payload).encode("utf-8")
        self.status = status
        self.connections: list[FakeConnection] = []
        self.calls: list[dict[str, object]] = []
        self.arguments: list[tuple[str, int, float]] = []

    def __call__(self, host: str, port: int, *, timeout: float) -> FakeConnection:
        self.arguments.append((host, port, timeout))
        connection = FakeConnection(
            FakeResponse(self.response_body, self.status), self.calls
        )
        self.connections.append(connection)
        return connection


def reasoning_factory(
    text: str = "bounded answer",
    *,
    thinking: str = "private chain of thought",
    prompt_tokens: int = 18,
    completion_tokens: int = 4,
) -> ConnectionFactory:
    return ConnectionFactory(
        {
            "message": {"content": text, "thinking": thinking},
            "prompt_eval_count": prompt_tokens,
            "eval_count": completion_tokens,
        }
    )


def tags_factory(*models: str) -> ConnectionFactory:
    return ConnectionFactory(
        {"models": [{"name": model, "size": 1} for model in models]}
    )


@pytest.fixture
def external_tls_paths():
    with tempfile.TemporaryDirectory(prefix="alpecca-rog-tls-") as folder:
        root = Path(folder)
        cert_path = root / "jason-holyrog.crt"
        key_path = root / "jason-holyrog.key"
        cert_path.write_text("public-test-certificate", encoding="ascii")
        key_path.write_text("private-test-key", encoding="ascii")
        yield cert_path, key_path, root / "worker-ops.sqlite3"


def post_reason(
    client: TestClient,
    payload: dict[str, object],
    *,
    nonce: str = "nonce-0000000000000001",
):
    body = encoded(payload)
    return client.post(
        "/v1/reason",
        content=body,
        headers=signed_headers("POST", "/v1/reason", body, nonce=nonce),
    )


def post_render(
    client: TestClient,
    payload: dict[str, object],
    *,
    nonce: str = "nonce-0000000000000001",
):
    body = encoded(payload)
    return client.post(
        "/v1/render/blender",
        content=body,
        headers=signed_headers(
            "POST", "/v1/render/blender", body, nonce=nonce
        ),
    )


def test_module_has_no_alpecca_runtime_or_memory_imports() -> None:
    tree = ast.parse(Path(worker_mod.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {"server", "alpecca.mind", "alpecca.memory", "alpecca.discord_bridge"}
    assert imported.isdisjoint(forbidden)


def test_signature_headers_and_five_line_canonicalization_match_client_lane() -> None:
    body = encoded(reason_payload())
    digest = hashlib.sha256(body).hexdigest()
    canonical = worker_mod.canonical_request(
        "POST", "/v1/reason", NOW, "nonce-0000000000000001", digest
    )
    assert canonical == (
        f"POST\n/v1/reason\n{NOW}\nnonce-0000000000000001\n{digest}"
    ).encode("ascii")
    assert worker_mod.sign_request(
        SECRET, "POST", "/v1/reason", NOW, "nonce-0000000000000001", body
    ) == hmac.new(SECRET, canonical, hashlib.sha256).hexdigest()
    assert worker_mod.TIMESTAMP_HEADER == "X-Alpecca-Worker-Timestamp"
    assert worker_mod.NONCE_HEADER == "X-Alpecca-Worker-Nonce"
    assert worker_mod.BODY_SHA256_HEADER == "X-Alpecca-Worker-Body-SHA256"
    assert worker_mod.SIGNATURE_HEADER == "X-Alpecca-Worker-Signature"
    assert worker_mod.REQUEST_ID_HEADER == "X-Alpecca-Request-Id"


def test_authenticated_health_is_content_free_and_typed(monkeypatch) -> None:
    monkeypatch.setattr(worker_mod.socket, "gethostname", lambda: "Jason_HOLYROG")
    connection_factory = tags_factory("qwen3.5:9b", "not-allowed:latest")
    app = worker_mod.create_app(
        make_settings(),
        clock=lambda: NOW,
        connection_factory=connection_factory,
    )
    client = TestClient(app)
    assert client.get("/v1/health").status_code == 401
    response = client.get(
        "/v1/health", headers=signed_headers("GET", "/v1/health")
    )
    assert response.status_code == 200
    assert response.json() == {
        "schema": worker_mod.HEALTH_SCHEMA,
        "ok": True,
        "request_id": "request-health-001",
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
    assert SECRET.decode("ascii") not in response.text
    assert "qwen3.5:9b" not in response.text
    assert connection_factory.calls == [
        {
            "method": "GET",
            "path": "/api/tags",
            "body": None,
            "headers": {"Accept": "application/json"},
        }
    ]
    assert client.get("/healthz").status_code == 404


def test_health_reports_reasoning_unready_when_ollama_or_model_is_missing() -> None:
    for factory in (tags_factory("different:9b"), ConnectionFactory({}, status=503)):
        app = worker_mod.create_app(
            make_settings(),
            clock=lambda: NOW,
            connection_factory=factory,
        )
        response = TestClient(app).get(
            "/v1/health",
            headers=signed_headers("GET", "/v1/health"),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ready"] is False
        assert payload["capabilities"]["reasoning"] == {"ready": False}
        assert "different:9b" not in response.text


def test_health_fails_closed_without_secret() -> None:
    app = worker_mod.create_app(make_settings(secret=None), clock=lambda: NOW)
    response = TestClient(app).get(
        "/v1/health", headers=signed_headers("GET", "/v1/health")
    )
    assert response.status_code == 503
    assert response.json()["error"] == "authentication_not_configured"


def test_secret_uses_shared_default_or_configured_credential_target() -> None:
    class FakeCredentialStore:
        CRED_TYPE_GENERIC = 1

        def __init__(self) -> None:
            self.calls = []

        def CredRead(self, target, credential_type, flags):
            self.calls.append((target, credential_type, flags))
            return {"CredentialBlob": ("w" * 32).encode("utf-16-le")}

    store = FakeCredentialStore()
    assert worker_mod.load_worker_secret({}, win32cred_module=store) == b"w" * 32
    assert store.calls == [("Alpecca/Jason_HOLYROG/ComputeWorker", 1, 0)]
    store.calls.clear()
    override = "Alpecca/Jason_HOLYROG/ComputeWorker-Test"
    worker_mod.load_worker_secret(
        {worker_mod.CREDENTIAL_TARGET_ENV: override}, win32cred_module=store
    )
    assert store.calls == [(override, 1, 0)]


def test_secret_prefers_environment_and_repr_redacts_it() -> None:
    value = "z" * 32
    loaded = worker_mod.load_worker_secret({"ALPECCA_ROG_WORKER_SECRET": value})
    assert loaded == value.encode("utf-8")
    assert value not in repr(make_settings(secret=loaded))


@pytest.mark.parametrize(
    ("change", "status", "error"),
    [
        ({worker_mod.SIGNATURE_HEADER: "0" * 64}, 401, "invalid_authentication"),
        ({worker_mod.TIMESTAMP_HEADER: str(NOW - 1000)}, 401, "stale_request"),
        ({worker_mod.NONCE_HEADER: "bad nonce"}, 401, "invalid_authentication"),
        ({worker_mod.BODY_SHA256_HEADER: "0" * 64}, 401, "body_hash_mismatch"),
        ({worker_mod.REQUEST_ID_HEADER: "different-request"}, 409, "request_id_mismatch"),
    ],
)
def test_authentication_rejects_tampering(change, status, error) -> None:
    body = encoded(reason_payload())
    headers = signed_headers("POST", "/v1/reason", body)
    headers.update(change)
    response = TestClient(
        worker_mod.create_app(make_settings(), clock=lambda: NOW)
    ).post("/v1/reason", content=body, headers=headers)
    assert response.status_code == status
    assert response.json()["error"] == error


def test_reasoning_uses_typed_history_thinking_and_bounded_8k_context() -> None:
    factory = reasoning_factory("Visible conclusion.")
    app = worker_mod.create_app(
        make_settings(), clock=lambda: NOW, connection_factory=factory
    )
    response = post_reason(TestClient(app), reason_payload())
    assert response.status_code == 200
    assert response.json() == {
        "schema": worker_mod.REASON_RESPONSE_SCHEMA,
        "ok": True,
        "request_id": "request-reason-001",
        "result": {
            "model": "qwen3.5:9b",
            "text": "Visible conclusion.",
            "elapsed_ms": 0,
            "prompt_tokens": 18,
            "completion_tokens": 4,
        },
    }
    assert factory.arguments == [("127.0.0.1", 11434, 5.0)]
    upstream = json.loads(factory.calls[0]["body"])
    assert upstream == {
        "model": "qwen3.5:9b",
        "messages": [
            {"role": "system", "content": "Be grounded."},
            {"role": "user", "content": "Earlier question."},
            {"role": "assistant", "content": "Earlier answer."},
            {"role": "user", "content": "Compare the options."},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 90, "num_ctx": 8192},
    }
    serialized = response.text
    assert "private chain of thought" not in serialized
    assert "thinking" not in serialized
    assert factory.connections[0].closed is True


def test_worker_nonce_capacity_tolerates_authenticated_health_polling() -> None:
    app = worker_mod.create_app(make_settings(idempotency_entries=16))

    assert app.state.worker._nonces._max_entries == 4_096


def test_reasoning_fails_cleanly_when_only_thinking_is_returned() -> None:
    observations = []
    factory = reasoning_factory("   ", thinking="sensitive private reasoning")
    app = worker_mod.create_app(
        make_settings(),
        clock=lambda: NOW,
        connection_factory=factory,
        audit_sink=observations.append,
    )
    response = post_reason(TestClient(app), reason_payload())
    assert response.status_code == 502
    assert response.json() == {"ok": False, "error": "reasoning_no_visible_content"}
    assert "sensitive private reasoning" not in json.dumps(observations)


def test_reasoning_fails_instead_of_returning_truncated_visible_content() -> None:
    factory = reasoning_factory("abcdefgh")
    app = worker_mod.create_app(
        make_settings(max_result_chars=5),
        clock=lambda: NOW,
        connection_factory=factory,
    )
    response = post_reason(TestClient(app), reason_payload())
    assert response.status_code == 502
    assert response.json()["error"] == "reasoning_result_too_large"
    assert "abcde" not in response.text


@pytest.mark.parametrize(
    ("overrides", "status", "error"),
    [
        ({"extra": True}, 422, "invalid_contract_fields"),
        ({"schema": "wrong"}, 422, "invalid_schema"),
        ({"model": "other:9b"}, 403, "model_not_allowed"),
        ({"max_tokens": 9999}, 422, "invalid_max_tokens"),
        ({"history": [{"role": "system", "content": "no"}]}, 422, "invalid_history"),
        ({"history": "not-a-list"}, 422, "invalid_history"),
    ],
)
def test_reasoning_contract_is_strict(overrides, status, error) -> None:
    response = post_reason(
        TestClient(worker_mod.create_app(make_settings(), clock=lambda: NOW)),
        reason_payload(**overrides),
    )
    assert response.status_code == status
    assert response.json()["error"] == error


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/v1/reason",
            {
                "request_id": "request-legacy-reason",
                "model": "qwen3.5:9b",
                "prompt": "Legacy flat prompt.",
                "system": "Legacy flat system.",
                "max_tokens": 32,
            },
        ),
        (
            "/v1/render/blender",
            {
                "request_id": "request-legacy-render",
                "blend_file": "scene.blend",
                "frame": 1,
            },
        ),
    ],
)
def test_legacy_flat_contracts_are_intentionally_rejected(path, payload) -> None:
    body = encoded(payload)
    response = TestClient(
        worker_mod.create_app(make_settings(), clock=lambda: NOW)
    ).post(path, content=body, headers=signed_headers("POST", path, body))

    assert response.status_code == 422
    assert response.json() == {"ok": False, "error": "invalid_contract_fields"}


def test_reasoning_history_count_and_each_message_are_bounded() -> None:
    client = TestClient(worker_mod.create_app(make_settings(), clock=lambda: NOW))
    too_many = [{"role": "user", "content": "x"}] * 5
    response = post_reason(client, reason_payload(history=too_many))
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_history"
    response = post_reason(
        client,
        reason_payload(
            request_id="request-history-002",
            history=[{"role": "user", "content": "x" * 97}],
        ),
        nonce="nonce-0000000000000002",
    )
    assert response.status_code == 413
    assert response.json()["error"] == "history_too_large"


def test_duplicate_json_keys_and_oversized_body_are_rejected() -> None:
    app = worker_mod.create_app(make_settings(max_body_bytes=1024), clock=lambda: NOW)
    client = TestClient(app)
    duplicate = (
        b'{"schema":"alpecca.rog-worker.reason.request.v1",'
        b'"request_id":"request-dupe-001","system_prompt":"",'
        b'"user_prompt":"one","user_prompt":"two","history":[],'
        b'"model":"qwen3.5:9b","max_tokens":32}'
    )
    response = client.post(
        "/v1/reason",
        content=duplicate,
        headers=signed_headers("POST", "/v1/reason", duplicate),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "duplicate_json_key"
    too_large = b"{" + (b" " * 1100) + b"}"
    response = client.post(
        "/v1/reason",
        content=too_large,
        headers=signed_headers(
            "POST", "/v1/reason", too_large, nonce="nonce-0000000000000002"
        ),
    )
    assert response.status_code == 413


def test_nonce_replay_and_idempotent_request_replay_are_distinct() -> None:
    factory = reasoning_factory("once")
    client = TestClient(
        worker_mod.create_app(
            make_settings(), clock=lambda: NOW, connection_factory=factory
        )
    )
    payload = reason_payload()
    body = encoded(payload)
    headers = signed_headers("POST", "/v1/reason", body)
    first = client.post("/v1/reason", content=body, headers=headers)
    nonce_replay = client.post("/v1/reason", content=body, headers=headers)
    idempotent = post_reason(client, payload, nonce="nonce-0000000000000002")
    assert first.status_code == 200
    assert nonce_replay.status_code == 409
    assert nonce_replay.json()["error"] == "nonce_replay"
    assert idempotent.status_code == 200
    assert idempotent.headers["X-Alpecca-Idempotent-Replay"] == "1"
    assert idempotent.json() == first.json()
    assert len(factory.calls) == 1


def test_nonce_replay_survives_worker_restart_and_db_contains_no_content(
    tmp_path: Path,
) -> None:
    database = tmp_path / "worker-ops.sqlite3"
    settings = make_settings(replay_db_path=database)
    body = encoded(reason_payload(user_prompt="PRIVATE PROMPT MUST NOT BE STORED"))
    headers = signed_headers("POST", "/v1/reason", body)
    first = TestClient(
        worker_mod.create_app(
            settings,
            clock=lambda: NOW,
            connection_factory=reasoning_factory("PRIVATE RESULT"),
        )
    ).post("/v1/reason", content=body, headers=headers)
    second = TestClient(
        worker_mod.create_app(
            settings,
            clock=lambda: NOW,
            connection_factory=reasoning_factory("must not run"),
        )
    ).post("/v1/reason", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"ok": False, "error": "nonce_replay"}
    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(replay_nonces)")
        }
        assert columns == {"nonce", "seen_at", "expires_at"}
    raw_database = database.read_bytes()
    assert b"PRIVATE PROMPT" not in raw_database
    assert b"PRIVATE RESULT" not in raw_database


def test_nonce_store_never_evicts_a_live_nonce_to_admit_another(
    tmp_path: Path,
) -> None:
    current = [float(NOW)]
    store = worker_mod._NonceStore(
        180,
        2,
        lambda: current[0],
        tmp_path / "bounded-replay.sqlite3",
    )
    assert store.accept("nonce-0000000000000001") == "accepted"
    assert store.accept("nonce-0000000000000002") == "accepted"
    assert store.accept("nonce-0000000000000003") == "full"
    assert store.accept("nonce-0000000000000001") == "replay"
    current[0] += 181
    assert store.accept("nonce-0000000000000003") == "accepted"


def test_request_id_conflict_and_busy_worker_fail_without_queueing() -> None:
    factory = reasoning_factory("once")
    app = worker_mod.create_app(
        make_settings(), clock=lambda: NOW, connection_factory=factory
    )
    client = TestClient(app)
    first = reason_payload()
    assert post_reason(client, first).status_code == 200
    changed = reason_payload(user_prompt="different")
    response = post_reason(client, changed, nonce="nonce-0000000000000002")
    assert response.status_code == 409
    assert response.json()["error"] == "request_id_conflict"

    busy_app = worker_mod.create_app(make_settings(), clock=lambda: NOW)
    assert busy_app.state.worker._slots.acquire(blocking=False)
    try:
        response = post_reason(
            TestClient(busy_app), reason_payload(request_id="request-busy-001")
        )
    finally:
        busy_app.state.worker._slots.release()
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"


def configured_render_app(
    tmp_path: Path,
    process_runner,
    *,
    audit_sink=None,
    **overrides,
):
    blend_root = tmp_path / "approved-blends"
    output_root = tmp_path / "approved-output"
    blend_root.mkdir()
    output_root.mkdir()
    (blend_root / "scene.blend").write_bytes(b"BLENDER")
    executable = tmp_path / "blender.exe"
    executable.write_bytes(b"EXE")
    settings = make_settings(
        blender_executable=str(executable),
        blend_root=blend_root,
        output_root=output_root,
        **overrides,
    )
    app = worker_mod.create_app(
        settings,
        clock=lambda: NOW,
        process_runner=process_runner,
        audit_sink=audit_sink,
    )
    return app, blend_root, output_root, executable


def render_output_from_command(command: tuple[str, ...]) -> Path:
    template = Path(command[command.index("--render-output") + 1])
    frame = int(command[command.index("--render-frame") + 1])
    return Path(str(template).replace("######", f"{frame:06d}") + ".png")


def test_blender_command_is_fixed_autoexec_disabled_and_env_sanitized(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []
    secret_text = SECRET.decode("ascii")
    monkeypatch.setenv("ALPECCA_ROG_WORKER_SECRET", secret_text)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord-private")
    monkeypatch.setenv("ALPECCA_CONTINUITY_LEASE_ID", "lease-private")
    monkeypatch.setenv("HF_TOKEN", "hf-private")
    monkeypatch.setenv("UNRELATED_SECRET_TOKEN", "other-private")
    monkeypatch.setenv("TEMP", f"C:\\Temp\\{secret_text}")

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        render_output_from_command(command).write_bytes(b"PNG-DATA")
        return SimpleNamespace(returncode=0)

    app, blend_root, output_root, executable = configured_render_app(tmp_path, runner)
    response = post_render(TestClient(app), blender_payload())
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == worker_mod.BLENDER_RESPONSE_SCHEMA
    assert payload["request_id"] == "request-render-001"
    result = payload["result"]
    assert result["status"] == "completed"
    assert result["frame"] == 12
    assert result["artifact"]["name"].endswith("-000012.png")
    assert result["artifact"]["sha256"] == hashlib.sha256(b"PNG-DATA").hexdigest()

    command, kwargs = calls[0]
    assert command[:4] == (
        str(executable.resolve()),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
    )
    assert "--python" not in command
    assert "--python-expr" not in command
    assert command[command.index("--background") + 3] == str(
        (blend_root / "scene.blend").resolve()
    )
    assert kwargs["cwd"] == str(blend_root.resolve())
    assert kwargs["shell"] is False
    assert kwargs["stdout"] is subprocess.DEVNULL
    child_env = kwargs["env"]
    serialized_env = json.dumps(child_env)
    assert child_env["PYTHONNOUSERSITE"] == "1"
    assert not any(key.upper().startswith("ALPECCA_") for key in child_env)
    assert "DISCORD_BOT_TOKEN" not in child_env
    assert "HF_TOKEN" not in child_env
    assert secret_text not in serialized_env
    assert "discord-private" not in serialized_env
    assert "lease-private" not in serialized_env
    assert "other-private" not in serialized_env
    assert str(output_root.resolve()) not in serialized_env


@pytest.mark.parametrize(
    "project",
    ["../scene.blend", "folder/scene.blend", "folder\\scene.blend", "C:scene.blend"],
)
def test_blender_rejects_arbitrary_paths(tmp_path: Path, project: str) -> None:
    def forbidden_runner(*_args, **_kwargs):
        raise AssertionError("Blender must not run")

    app, *_ = configured_render_app(tmp_path, forbidden_runner)
    response = post_render(TestClient(app), blender_payload(project=project))
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_project"


def test_blender_timeout_is_bounded_and_idempotent(tmp_path: Path) -> None:
    calls = []

    def timeout_runner(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    app, *_ = configured_render_app(tmp_path, timeout_runner)
    client = TestClient(app)
    payload = blender_payload(request_id="request-timeout-001")
    first = post_render(client, payload)
    replay = post_render(client, payload, nonce="nonce-0000000000000002")
    assert first.status_code == 504
    assert first.json()["error"] == "blender_timeout"
    assert replay.status_code == 504
    assert replay.headers["X-Alpecca-Idempotent-Replay"] == "1"
    assert len(calls) == 1


def test_audit_is_metadata_only_for_reason_and_render(tmp_path: Path) -> None:
    observations = []
    factory = reasoning_factory("VISIBLE PRIVATE RESULT", thinking="PRIVATE THINKING")
    app = worker_mod.create_app(
        make_settings(),
        clock=lambda: NOW,
        connection_factory=factory,
        audit_sink=observations.append,
    )
    assert post_reason(
        TestClient(app),
        reason_payload(user_prompt="PRIVATE USER PROMPT"),
    ).status_code == 200

    def runner(command, **_kwargs):
        render_output_from_command(command).write_bytes(b"PRIVATE IMAGE")
        return SimpleNamespace(returncode=0)

    render_app, *_ = configured_render_app(
        tmp_path, runner, audit_sink=observations.append
    )
    assert post_render(TestClient(render_app), blender_payload()).status_code == 200
    serialized = json.dumps(observations)
    for forbidden in (
        "PRIVATE USER PROMPT",
        "VISIBLE PRIVATE RESULT",
        "PRIVATE THINKING",
        "scene.blend",
        SECRET.decode("ascii"),
        "request-reason-001",
    ):
        assert forbidden not in serialized


def test_unexpected_runner_failure_returns_content_free_internal_error() -> None:
    class BrokenFactory:
        def __call__(self, *_args, **_kwargs):
            raise RuntimeError("secret internal detail")

    observations = []
    app = worker_mod.create_app(
        make_settings(),
        clock=lambda: NOW,
        connection_factory=BrokenFactory(),
        audit_sink=observations.append,
    )
    response = post_reason(TestClient(app), reason_payload())
    assert response.status_code == 500
    assert response.json() == {"ok": False, "error": "internal_error"}
    assert "secret internal detail" not in response.text
    assert "secret internal detail" not in json.dumps(observations)


def test_lan_mode_refuses_plain_http_even_when_runner_is_bypassed(
    external_tls_paths,
) -> None:
    cert_path, key_path, replay_db_path = external_tls_paths
    settings = make_settings(
        bind_host="0.0.0.0",
        allow_lan=True,
        tls_cert_path=cert_path,
        tls_key_path=key_path,
        replay_db_path=replay_db_path,
    )
    app = worker_mod.create_app(
        settings,
        clock=lambda: NOW,
        connection_factory=tags_factory("qwen3.5:9b"),
    )
    insecure = TestClient(app, base_url="http://Jason_HOLYROG:8788").get(
        "/v1/health",
        headers=signed_headers("GET", "/v1/health"),
    )
    secure = TestClient(app, base_url="https://Jason_HOLYROG:8788").get(
        "/v1/health",
        headers=signed_headers("GET", "/v1/health"),
    )
    assert insecure.status_code == 426
    assert insecure.json() == {"ok": False, "error": "tls_required"}
    assert secure.status_code == 200


def test_remote_ollama_unapproved_lan_bind_and_num_ctx_over_cap_are_rejected(
    external_tls_paths,
) -> None:
    with pytest.raises(worker_mod.WorkerConfigurationError, match="loopback"):
        make_settings(ollama_url="http://192.168.12.1:11434")
    with pytest.raises(worker_mod.WorkerConfigurationError, match="ALLOW_LAN"):
        make_settings(bind_host="0.0.0.0")
    cert_path, key_path, replay_db_path = external_tls_paths
    assert make_settings(
        bind_host="0.0.0.0",
        allow_lan=True,
        tls_cert_path=cert_path,
        tls_key_path=key_path,
        replay_db_path=replay_db_path,
    ).bind_host == "0.0.0.0"
    with pytest.raises(worker_mod.WorkerConfigurationError, match="ollama_num_ctx"):
        make_settings(ollama_num_ctx=8193)


def test_environment_defaults_to_qwen35_and_8k_context() -> None:
    settings = worker_mod.WorkerSettings.from_env(
        {"ALPECCA_ROG_WORKER_SECRET": "s" * 32}
    )
    assert settings.model_allowlist == frozenset({"qwen3.5:9b"})
    assert "qwen3:8b" not in settings.model_allowlist
    assert settings.ollama_num_ctx == 8192
