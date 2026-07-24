from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import urllib.error
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy" / "hf-cloud-core" / "cloud_entrypoint.py"
SPEC = importlib.util.spec_from_file_location("alpecca_hf_cloud_voice_entrypoint", PATH)
assert SPEC and SPEC.loader
cloud = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cloud)


class FakeVoiceBackend:
    def __init__(self, secret: str = "voice-secret") -> None:
        self.expected = hashlib.sha256(secret.encode()).digest()
        self.health_calls = 0
        self.synthesis_calls: list[tuple[bytes, str]] = []
        self.result = cloud.VoiceBackendResponse(200, b"RIFF-wave", "audio/wav")

    def authorized(self, supplied: str | None) -> bool:
        candidate = hashlib.sha256((supplied or "").encode()).digest()
        return hmac.compare_digest(candidate, self.expected)

    def health(self):
        self.health_calls += 1
        return {
            "state": "ready",
            "modelLoaded": False,
            "requestText": "must not escape",
            "singletonAuthority": True,
            "coreMind": True,
        }

    def synthesize(self, body: bytes, authorization: str):
        self.synthesis_calls.append((body, authorization))
        return self.result


@pytest.fixture
def voice_server():
    backend = FakeVoiceBackend()
    server = cloud.StandbyServer(0, voice_backend=backend)
    server.start()
    try:
        yield server, backend
    finally:
        server.stop()


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.loads(response.read())


def _post(port: int, body: bytes, *, secret: str | None = None):
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers[cloud.VOICE_AUTHORIZATION_HEADER] = secret
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/voice/tts",
        data=body,
        headers=headers,
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=2)


def test_existing_standby_health_routes_are_unchanged(voice_server) -> None:
    server, backend = voice_server
    expected = {
        "service": "alpecca-continuity-standby",
        "version": 1,
        "state": "waiting-for-singleton-lease",
        "coreMind": False,
    }

    assert _get_json(f"http://127.0.0.1:{server.port}/") == expected
    assert _get_json(f"http://127.0.0.1:{server.port}/healthz") == expected
    assert backend.health_calls == 0
    assert backend.synthesis_calls == []


def test_sparse_configuration_health_does_not_probe_voice() -> None:
    backend = FakeVoiceBackend()
    server = cloud.StandbyServer(
        0,
        voice_backend=backend,
        state="configuration-required",
    )
    server.start()
    try:
        payload = _get_json(f"http://127.0.0.1:{server.port}/healthz")
    finally:
        server.stop()

    assert payload == {
        "service": "alpecca-continuity-standby",
        "version": 1,
        "state": "configuration-required",
        "coreMind": False,
    }
    assert backend.health_calls == 0


def test_voice_health_is_public_content_free_and_denies_authority(voice_server) -> None:
    server, backend = voice_server
    payload = _get_json(f"http://127.0.0.1:{server.port}/voice/health")

    assert payload == {
        "service": "alpecca-cloud-kokoro-voice",
        "version": 1,
        "state": "ready",
        "engine": "kokoro",
        "voice": "af_heart",
        "device": "cpu",
        "sampleRateHz": 24000,
        "modelLoaded": False,
        "persistence": False,
        "coreMind": False,
        "singletonAuthority": False,
        "maxBodyBytes": cloud.MAX_VOICE_BODY_BYTES,
    }
    assert "requestText" not in payload
    assert backend.health_calls == 1


def test_voice_tts_authenticates_before_forwarding(voice_server) -> None:
    server, backend = voice_server
    body = json.dumps({"text": "hello"}).encode()

    for secret in (None, "wrong"):
        with pytest.raises(urllib.error.HTTPError) as rejected:
            _post(server.port, body, secret=secret)
        assert rejected.value.code == 401
    assert backend.synthesis_calls == []

    with _post(server.port, body, secret="voice-secret") as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "audio/wav"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.read() == b"RIFF-wave"
    assert backend.synthesis_calls == [(body, "voice-secret")]


def test_voice_tts_applies_body_limit_before_backend(voice_server) -> None:
    server, backend = voice_server
    body = b"x" * (cloud.MAX_VOICE_BODY_BYTES + 1)

    try:
        _post(server.port, body, secret="voice-secret")
    except urllib.error.HTTPError as rejected:
        assert rejected.code == 413
    except ConnectionAbortedError as rejected:
        assert getattr(rejected, "winerror", None) == 10053
    else:
        raise AssertionError("oversized voice request was accepted")
    assert backend.synthesis_calls == []


def test_voice_tts_never_forwards_backend_error_content(voice_server) -> None:
    server, backend = voice_server
    backend.result = cloud.VoiceBackendResponse(
        503,
        b'{"detail":"secret internal model failure"}',
        "application/json",
    )

    with pytest.raises(urllib.error.HTTPError) as rejected:
        _post(server.port, b'{"text":"hello"}', secret="voice-secret")
    body = rejected.value.read()

    assert rejected.value.code == 503
    assert json.loads(body) == {"error": "voice_request_rejected"}
    assert b"secret internal model failure" not in body


def test_loopback_backend_uses_fixed_digest_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compared = []
    real_compare = hmac.compare_digest

    def track(left, right):
        compared.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(cloud.hmac, "compare_digest", track)
    backend = cloud.LoopbackVoiceBackend(
        secret="voice-secret", opener=lambda *_args, **_kwargs: None
    )

    assert not backend.authorized(None)
    assert not backend.authorized("wrong")
    assert backend.authorized("Bearer voice-secret")
    assert len(compared) == 3
    assert all(len(left) == len(right) == 32 for left, right in compared)


def test_loopback_backend_forwards_only_to_standalone_voice_route() -> None:
    captured = {}

    class Response:
        status = 200
        headers = {"Content-Type": "audio/wav"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, limit):
            captured["read_limit"] = limit
            return b"RIFF-loopback"

    def opener(request, *, timeout):
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["headers"] = {
            key.lower(): value for key, value in request.header_items()
        }
        captured["timeout"] = timeout
        return Response()

    backend = cloud.LoopbackVoiceBackend(
        secret="voice-secret", port=9123, opener=opener
    )
    result = backend.synthesize(b'{"text":"hello"}', "voice-secret")

    assert result == cloud.VoiceBackendResponse(200, b"RIFF-loopback", "audio/wav")
    assert captured["url"] == "http://127.0.0.1:9123/v1/voice/synthesize"
    assert captured["data"] == b'{"text":"hello"}'
    assert captured["headers"]["x-alpecca-authorization"] == "voice-secret"
    assert captured["read_limit"] == cloud.MAX_VOICE_AUDIO_BYTES + 1


def test_promoted_core_uses_local_kokoro_without_self_recursion() -> None:
    environment = {
        "ALPECCA_CLOUD_TTS_ENDPOINT": "https://self.example/voice/tts",
        "ALPECCA_CLOUD_TTS_AUTHORIZATION": "must-be-removed",
        "ALPECCA_TTS_BACKEND": "cloud",
    }

    cloud.configure_environment(environment)

    assert environment["ALPECCA_TTS_BACKEND"] == "kokoro"
    assert environment["ALPECCA_CLOUD_TTS_ENDPOINT"] == ""
    assert environment["ALPECCA_CLOUD_TTS_AUTHORIZATION"] == ""


def test_lifecycle_has_one_public_port_and_both_public_tts_owners() -> None:
    docker = (ROOT / "deploy" / "hf-cloud-core" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    start = (ROOT / "deploy" / "hf-cloud-core" / "start.sh").read_text(encoding="utf-8")
    readme = (ROOT / "deploy" / "hf-cloud-core" / "README.md").read_text(
        encoding="utf-8"
    )
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    supervisor = (ROOT / "deploy" / "hf-cloud-core" / "app.py").read_text(
        encoding="utf-8"
    )

    assert "app_port: 7860" in readme
    assert "EXPOSE 7860\n" in docker
    assert "EXPOSE 7860 7861" not in docker
    assert (
        'ENTRYPOINT ["/usr/bin/tini", "-g", "--", '
        '"/opt/hf-cloud-core/start.sh"]'
    ) in docker
    assert "cloud_process_supervisor.py" in start
    assert "cloud_healthcheck.py" in docker
    assert 'app.post("/voice/tts")' in server
    public_paths = server[
        server.index("_PUBLIC_AUTH_PATHS = frozenset"):
        server.index("_SAFE_HTTP_METHODS", server.index("_PUBLIC_AUTH_PATHS"))
    ]
    assert '"/voice/tts"' not in public_paths
    assert '"server:app"' in supervisor
