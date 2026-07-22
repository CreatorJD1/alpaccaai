from __future__ import annotations

import builtins
import hmac
import importlib.util
import asyncio
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy" / "hf-cloud-core" / "cloud_voice.py"


class FakeHTTPException(Exception):
    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FakeResponse:
    def __init__(self, content=b"", media_type=None, headers=None, *, status_code=200):
        self.content = content
        self.status_code = status_code
        self.headers = {key.lower(): value for key, value in (headers or {}).items()}
        if media_type is not None:
            self.headers["content-type"] = media_type

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self):
        return json.loads(self.content.decode("utf-8"))


class FakeRequest:
    def __init__(self, content: bytes, headers: dict[str, str]) -> None:
        self._content = content
        self.headers = {}
        for key, value in headers.items():
            self.headers[key] = value
            self.headers[key.lower()] = value

    async def stream(self):
        yield self._content


class FakeFastAPI:
    def __init__(self, **_kwargs) -> None:
        self.routes = {}

    def get(self, path, **_kwargs):
        return self._register("GET", path)

    def post(self, path, **_kwargs):
        return self._register("POST", path)

    def _register(self, method, path):
        def decorator(function):
            self.routes[(method, path)] = function
            return function

        return decorator


class FakeClient:
    def __init__(self, app) -> None:
        self.app = app

    def get(self, path: str) -> FakeResponse:
        result = asyncio.run(self.app.routes[("GET", path)]())
        return self._response(result)

    def post(self, path: str, *, json=None, content=None, headers=None) -> FakeResponse:
        body = (
            globals()["json"].dumps(json).encode("utf-8")
            if json is not None
            else bytes(content or b"")
        )
        request_headers = dict(headers or {})
        request_headers.setdefault("content-length", str(len(body)))
        request = FakeRequest(body, request_headers)
        try:
            result = asyncio.run(self.app.routes[("POST", path)](request))
        except FakeHTTPException as exc:
            return FakeResponse(
                globals()["json"].dumps({"detail": exc.detail}).encode("utf-8"),
                media_type="application/json",
                status_code=exc.status_code,
            )
        return self._response(result)

    @staticmethod
    def _response(result) -> FakeResponse:
        if isinstance(result, FakeResponse):
            return result
        return FakeResponse(
            json.dumps(result).encode("utf-8"), media_type="application/json"
        )


def _load_module(monkeypatch: pytest.MonkeyPatch):
    fastapi = ModuleType("fastapi")
    fastapi.FastAPI = FakeFastAPI
    fastapi.HTTPException = FakeHTTPException
    fastapi.Request = FakeRequest
    fastapi.Response = FakeResponse
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "alpecca" or name.startswith("alpecca."):
            raise AssertionError("standalone voice service imported Alpecca runtime")
        if name == "kokoro" or name == "soundfile":
            raise AssertionError("Kokoro loaded before authenticated synthesis")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    spec = importlib.util.spec_from_file_location("hf_cloud_voice_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeSynthesizer:
    def __init__(self, *, result: bytes = b"RIFF-fake-wave") -> None:
        self.loaded = False
        self.result = result
        self.calls: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.loaded = True
        self.calls.append(text)
        return self.result


def test_standalone_voice_listener_is_loopback_only() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert 'host="127.0.0.1"' in source
    assert 'host="0.0.0.0"' not in source


def test_health_is_content_free_and_does_not_load_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    synth = FakeSynthesizer()
    client = FakeClient(module.create_app(secret="voice-secret", synthesizer=synth))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
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
        "maxTextChars": module.MAX_TEXT_CHARS,
        "maxBodyBytes": module.MAX_BODY_BYTES,
    }
    assert synth.calls == []
    assert "voice-secret" not in response.text


def test_synthesis_requires_constant_time_custom_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    synth = FakeSynthesizer()
    compared: list[tuple[bytes, bytes]] = []
    real_compare = hmac.compare_digest

    def track_compare(left, right):
        compared.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(module.hmac, "compare_digest", track_compare)
    client = FakeClient(module.create_app(secret="voice-secret", synthesizer=synth))

    missing = client.post("/v1/voice/synthesize", json={"text": "hello"})
    wrong = client.post(
        "/v1/voice/synthesize",
        json={"text": "hello"},
        headers={module.AUTHORIZATION_HEADER: "wrong"},
    )
    accepted = client.post(
        "/v1/voice/synthesize",
        json={"text": "  hello   Alpecca  "},
        headers={module.AUTHORIZATION_HEADER: "Bearer voice-secret"},
    )

    assert missing.status_code == wrong.status_code == 401
    assert accepted.status_code == 200
    assert accepted.content == b"RIFF-fake-wave"
    assert accepted.headers["content-type"] == "audio/wav"
    assert accepted.headers["cache-control"] == "no-store"
    assert synth.calls == ["hello Alpecca"]
    assert len(compared) == 3
    assert all(len(left) == len(right) == 32 for left, right in compared)


def test_body_and_text_limits_are_enforced_before_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    synth = FakeSynthesizer()
    client = FakeClient(module.create_app(secret="secret", synthesizer=synth))
    headers = {module.AUTHORIZATION_HEADER: "secret"}

    too_much_text = client.post(
        "/v1/voice/synthesize",
        json={"text": "x" * (module.MAX_TEXT_CHARS + 1)},
        headers=headers,
    )
    oversized_body = client.post(
        "/v1/voice/synthesize",
        content=b"{" + b" " * module.MAX_BODY_BYTES + b"}",
        headers={**headers, "Content-Type": "application/json"},
    )
    invalid = client.post(
        "/v1/voice/synthesize",
        content=b"not-json",
        headers={**headers, "Content-Type": "application/json"},
    )

    assert too_much_text.status_code == 413
    assert oversized_body.status_code == 413
    assert invalid.status_code == 400
    assert synth.calls == []


def test_audio_result_is_bounded_and_errors_disclose_no_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    synth = FakeSynthesizer(result=b"x" * (module.MAX_AUDIO_BYTES + 1))
    client = FakeClient(module.create_app(secret="secret", synthesizer=synth))
    response = client.post(
        "/v1/synthesize",
        json={"text": "bounded request"},
        headers={module.AUTHORIZATION_HEADER: "secret"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "invalid_synthesis_result"}
    assert "bounded request" not in response.text


def test_lazy_kokoro_uses_cpu_voice_and_in_memory_wav(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    calls: dict[str, object] = {}

    class FakePipeline:
        def __init__(self, *, lang_code: str) -> None:
            calls["lang_code"] = lang_code

        def __call__(self, text, **kwargs):
            calls["text"] = text
            calls.update(kwargs)
            return iter([("graphemes", "phonemes", [0.0, 0.25, -0.25])])

    class FakeSoundFile:
        def __init__(self, output, **kwargs) -> None:
            calls["soundfile"] = kwargs
            self.output = output

        def __enter__(self):
            self.output.write(b"RIFF")
            return self

        def write(self, audio) -> None:
            calls["audio"] = audio
            self.output.write(b"audio")

        def __exit__(self, *_args) -> None:
            return None

    class KokoroModule:
        KPipeline = FakePipeline

    class SoundFileModule:
        SoundFile = FakeSoundFile

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "kokoro":
            return KokoroModule()
        if name == "soundfile":
            return SoundFileModule()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    synth = module.LazyKokoroSynthesizer()
    assert not synth.loaded

    result = synth.synthesize("hello")

    assert result == b"RIFFaudio"
    assert synth.loaded
    assert module.os.environ["CUDA_VISIBLE_DEVICES"] == ""
    assert calls["lang_code"] == "a"
    assert calls["voice"] == "af_heart"
    assert calls["speed"] == 1.0
    assert calls["soundfile"] == {
        "mode": "w",
        "samplerate": 24000,
        "channels": 1,
        "format": "WAV",
        "subtype": "PCM_16",
    }
