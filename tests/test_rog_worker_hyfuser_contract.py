from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alpecca import rog_worker_client as client_mod
from alpecca import rog_worker_runtime
from alpecca import rog_worker_server as server_mod
from alpecca.multimodal_affect_fusion import EMOTION_ORDER


SECRET = b"h" * 32
NOW = 1_800_000_000
REQUEST_ID = "request-hyfuser-001"
NONCE = "nonce-hyfuser-00000001"
WEIGHTS = "a" * 64


def test_transport_uses_the_canonical_seven_class_affect_order():
    assert client_mod.HYFUSER_EMOTION_ORDER == EMOTION_ORDER
    assert server_mod.HYFUSER_EMOTION_ORDER == EMOTION_ORDER
    assert client_mod.HYFUSER_VECTOR_DIM == len(EMOTION_ORDER) == 7


def _settings(**overrides):
    values = dict(
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
        hyfuser_timeout_seconds=1.0,
        timestamp_skew_seconds=90,
        idempotency_ttl_seconds=600,
        idempotency_entries=16,
    )
    values.update(overrides)
    return server_mod.WorkerSettings(**values)


def _encoded(value: dict[str, object]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _headers(method: str, path: str, body: bytes, nonce: str = NONCE):
    return {
        server_mod.TIMESTAMP_HEADER: str(NOW),
        server_mod.NONCE_HEADER: nonce,
        server_mod.BODY_SHA256_HEADER: hashlib.sha256(body).hexdigest(),
        server_mod.SIGNATURE_HEADER: server_mod.sign_request(
            SECRET, method, path, NOW, nonce, body
        ),
        server_mod.REQUEST_ID_HEADER: REQUEST_ID,
        "Content-Type": "application/json; charset=utf-8",
    }


def _payload(**overrides):
    value = {
        "schema": server_mod.HYFUSER_REQUEST_SCHEMA,
        "request_id": REQUEST_ID,
        "mode": "shadow",
        "emotion_order": list(server_mod.HYFUSER_EMOTION_ORDER),
        "text_emotion": [1.0] + [0.0] * (server_mod.HYFUSER_VECTOR_DIM - 1),
        "speech_emotion": [0.0, 1.0] + [0.0] * (server_mod.HYFUSER_VECTOR_DIM - 2),
    }
    value.update(overrides)
    return value


class Backend:
    def __init__(self) -> None:
        self.calls = []

    def probe(self):
        return {
            "ready": True,
            "architecture": server_mod.HYFUSER_ARCHITECTURE,
            "runtime_id": "hyfuser-test-runtime",
            "weights_sha256": WEIGHTS,
            "perspectives": list(server_mod.HYFUSER_PERSPECTIVES),
            "emotion_order": list(server_mod.HYFUSER_EMOTION_ORDER),
            "text_emotion_dim": server_mod.HYFUSER_VECTOR_DIM,
            "speech_emotion_dim": server_mod.HYFUSER_VECTOR_DIM,
        }

    def infer(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "scores": [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3],
            "confidences": [0.8] * 7,
            "runtime_id": "hyfuser-test-runtime",
            "weights_sha256": WEIGHTS,
        }


def test_unconfigured_runtime_reports_unavailable_and_refuses_job(monkeypatch):
    monkeypatch.setattr(server_mod.socket, "gethostname", lambda: "Jason_HOLYROG")
    app = server_mod.create_app(
        _settings(), clock=lambda: NOW, hyfuser_backend=None
    )
    client = TestClient(app)
    empty = b""
    health = client.get(
        server_mod.HYFUSER_HEALTH_PATH,
        headers=_headers("GET", server_mod.HYFUSER_HEALTH_PATH, empty),
    )
    assert health.status_code == 200
    assert health.json()["ready"] is False
    assert health.json()["state"] == "unavailable"
    assert health.json()["emotion_order"] == list(server_mod.HYFUSER_EMOTION_ORDER)

    body = _encoded(_payload())
    response = client.post(
        server_mod.HYFUSER_SCORE_PATH,
        content=body,
        headers=_headers(
            "POST", server_mod.HYFUSER_SCORE_PATH, body, "nonce-hyfuser-00000002"
        ),
    )
    assert response.status_code == 503
    assert response.json() == {"ok": False, "error": "hyfuser_unavailable"}


def test_authenticated_shadow_job_returns_seven_ordered_heads_and_replays():
    backend = Backend()
    app = server_mod.create_app(
        _settings(), clock=lambda: NOW, hyfuser_backend=backend
    )
    client = TestClient(app)
    body = _encoded(_payload())
    response = client.post(
        server_mod.HYFUSER_SCORE_PATH,
        content=body,
        headers=_headers("POST", server_mod.HYFUSER_SCORE_PATH, body),
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert [head["name"] for head in result["heads"]] == list(
        server_mod.HYFUSER_PERSPECTIVES
    )
    assert result["advisory"] is True
    assert result["shadow_only"] is True
    assert result["speaking"] is False
    assert result["state_mutation"] is False
    assert result["provenance"]["weights_sha256"] == WEIGHTS
    assert result["provenance"]["emotion_order"] == list(
        server_mod.HYFUSER_EMOTION_ORDER
    )
    assert backend.calls[0]["emotion_order"] == server_mod.HYFUSER_EMOTION_ORDER
    assert backend.calls[0]["timeout_seconds"] == 1.0

    replay = client.post(
        server_mod.HYFUSER_SCORE_PATH,
        content=body,
        headers=_headers(
            "POST", server_mod.HYFUSER_SCORE_PATH, body, "nonce-hyfuser-00000003"
        ),
    )
    assert replay.status_code == 200
    assert replay.headers["X-Alpecca-Idempotent-Replay"] == "1"
    assert len(backend.calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("text_emotion", [0.0] * 6),
        ("speech_emotion", [0.0] * 8),
        ("text_emotion", [0.0] * 6 + [1.01]),
        ("speech_emotion", [0.0] * 6 + [True]),
        ("text_emotion", [0.1] * 7),
    ],
)
def test_server_rejects_wrong_dimensions_and_non_normalized_values(field, value):
    backend = Backend()
    app = server_mod.create_app(
        _settings(), clock=lambda: NOW, hyfuser_backend=backend
    )
    body = _encoded(_payload(**{field: value}))
    response = TestClient(app).post(
        server_mod.HYFUSER_SCORE_PATH,
        content=body,
        headers=_headers("POST", server_mod.HYFUSER_SCORE_PATH, body),
    )
    assert response.status_code == 422
    assert backend.calls == []


def test_server_rejects_reordered_emotion_classes_before_inference():
    backend = Backend()
    app = server_mod.create_app(
        _settings(), clock=lambda: NOW, hyfuser_backend=backend
    )
    body = _encoded(
        _payload(emotion_order=list(reversed(server_mod.HYFUSER_EMOTION_ORDER)))
    )
    response = TestClient(app).post(
        server_mod.HYFUSER_SCORE_PATH,
        content=body,
        headers=_headers("POST", server_mod.HYFUSER_SCORE_PATH, body),
    )
    assert response.status_code == 422
    assert response.json() == {"ok": False, "error": "invalid_emotion_order"}
    assert backend.calls == []


def test_server_readiness_fails_closed_when_backend_probe_reorders_classes():
    class ReorderedBackend(Backend):
        def probe(self):
            value = super().probe()
            value["emotion_order"] = list(
                reversed(server_mod.HYFUSER_EMOTION_ORDER)
            )
            return value

    app = server_mod.create_app(
        _settings(), clock=lambda: NOW, hyfuser_backend=ReorderedBackend()
    )
    response = TestClient(app).get(
        server_mod.HYFUSER_HEALTH_PATH,
        headers=_headers("GET", server_mod.HYFUSER_HEALTH_PATH, b""),
    )
    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert response.json()["state"] == "unavailable"


class Response:
    def __init__(self, payload, url):
        self.body = _encoded(payload)
        self.url = url
        self.status = 200
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(self.body)),
        }

    def geturl(self):
        return self.url

    def read(self, size):
        return self.body[:size]

    def close(self):
        return None


def _client(opener):
    return client_mod.RogWorkerClient(
        "https://Jason_HOLYROG:8788",
        SECRET,
        ca_cert=Path(__file__).resolve(),
        opener=opener,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
        request_id_factory=lambda: REQUEST_ID,
    )


def test_client_emits_exact_contract_and_parses_bounded_result():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response(
            {
                "schema": client_mod.HYFUSER_RESPONSE_SCHEMA,
                "ok": True,
                "request_id": REQUEST_ID,
                "result": {
                    "architecture": server_mod.HYFUSER_ARCHITECTURE,
                    "heads": [
                        {"name": name, "score": 0.25, "confidence": 0.75}
                        for name in client_mod.HYFUSER_PERSPECTIVES
                    ],
                    "provenance": {
                        "runtime_id": "hyfuser-test-runtime",
                        "weights_sha256": WEIGHTS,
                        "input_dimensions": {
                            "text_emotion": 7,
                            "speech_emotion": 7,
                        },
                        "emotion_order": list(client_mod.HYFUSER_EMOTION_ORDER),
                    },
                    "elapsed_ms": 4,
                    "advisory": True,
                    "shadow_only": True,
                    "speaking": False,
                    "state_mutation": False,
                },
            },
            request.full_url,
        )

    result = _client(opener).score_soul(
        [1.0] + [0.0] * 6,
        [0.0, 1.0] + [0.0] * 5,
    )
    assert tuple(head.name for head in result.heads) == client_mod.HYFUSER_PERSPECTIVES
    assert captured["timeout"] == client_mod.DEFAULT_HYFUSER_TIMEOUT_SECONDS
    sent = json.loads(captured["request"].data)
    assert sent["mode"] == "shadow"
    assert sent["emotion_order"] == list(client_mod.HYFUSER_EMOTION_ORDER)
    assert set(sent) == {
        "schema", "request_id", "mode", "emotion_order", "text_emotion",
        "speech_emotion"
    }


def test_client_health_rejects_reordered_emotion_classes():
    def opener(request, timeout):
        return Response(
            {
                "schema": client_mod.HYFUSER_HEALTH_SCHEMA,
                "ok": True,
                "request_id": REQUEST_ID,
                "ready": True,
                "state": "ready",
                "architecture": server_mod.HYFUSER_ARCHITECTURE,
                "perspectives": list(client_mod.HYFUSER_PERSPECTIVES),
                "emotion_order": list(reversed(client_mod.HYFUSER_EMOTION_ORDER)),
                "advisory": True,
                "shadow_only": True,
                "speaking": False,
                "state_mutation": False,
            },
            request.full_url,
        )

    with pytest.raises(client_mod.RogWorkerProtocolError, match="emotion order"):
        _client(opener).hyfuser_health()


def test_client_rejects_reordered_provenance_emotion_classes():
    def opener(request, timeout):
        return Response(
            {
                "schema": client_mod.HYFUSER_RESPONSE_SCHEMA,
                "ok": True,
                "request_id": REQUEST_ID,
                "result": {
                    "architecture": server_mod.HYFUSER_ARCHITECTURE,
                    "heads": [
                        {"name": name, "score": 0.0, "confidence": 0.5}
                        for name in client_mod.HYFUSER_PERSPECTIVES
                    ],
                    "provenance": {
                        "runtime_id": "hyfuser-test-runtime",
                        "weights_sha256": WEIGHTS,
                        "input_dimensions": {
                            "text_emotion": 7,
                            "speech_emotion": 7,
                        },
                        "emotion_order": list(
                            reversed(client_mod.HYFUSER_EMOTION_ORDER)
                        ),
                    },
                    "elapsed_ms": 1,
                    "advisory": True,
                    "shadow_only": True,
                    "speaking": False,
                    "state_mutation": False,
                },
            },
            request.full_url,
        )

    with pytest.raises(client_mod.RogWorkerProtocolError, match="emotion order"):
        _client(opener).score_soul(
            [1.0] + [0.0] * 6,
            [1.0] + [0.0] * 6,
        )


def test_client_rejects_reordered_emotion_classes_without_transport():
    called = False

    def opener(request, timeout):
        nonlocal called
        called = True
        raise AssertionError("transport must not run")

    with pytest.raises(
        client_mod.RogWorkerConfigurationError, match="canonical affect order"
    ):
        _client(opener).score_soul(
            [1.0] + [0.0] * 6,
            [1.0] + [0.0] * 6,
            emotion_order=tuple(reversed(client_mod.HYFUSER_EMOTION_ORDER)),
        )
    assert called is False


def test_primary_runtime_receipt_cannot_claim_speech_or_mutation():
    class Client:
        def score_soul(self, text_emotion, speech_emotion, *, emotion_order):
            assert tuple(emotion_order) == client_mod.HYFUSER_EMOTION_ORDER
            return client_mod.HyfuserScoreResult(
                request_id=REQUEST_ID,
                heads=tuple(
                    client_mod.HyfuserHeadResult(name, 0.0, 0.5)
                    for name in client_mod.HYFUSER_PERSPECTIVES
                ),
                architecture=server_mod.HYFUSER_ARCHITECTURE,
                runtime_id="hyfuser-test-runtime",
                weights_sha256=WEIGHTS,
                elapsed_ms=3,
            )

    receipt = rog_worker_runtime.score_hyfuser_shadow(
        [1.0] + [0.0] * 6,
        [1.0] + [0.0] * 6,
        client_factory=Client,
    )
    assert receipt["advisory"] is True
    assert receipt["shadow_only"] is True
    assert receipt["speaking"] is False
    assert receipt["state_mutation"] is False
    assert receipt["provenance"]["emotion_order"] == list(
        client_mod.HYFUSER_EMOTION_ORDER
    )
