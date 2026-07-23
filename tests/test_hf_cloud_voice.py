from __future__ import annotations

import builtins
import hmac
import importlib.util
import asyncio
import json
from pathlib import Path
import struct
import sys
import threading
import time
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy" / "hf-cloud-core" / "cloud_voice.py"
HEALTHCHECK_MODULE_PATH = ROOT / "deploy" / "hf-cloud-core" / "cloud_healthcheck.py"


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


def _load_healthcheck_module():
    spec = importlib.util.spec_from_file_location(
        "hf_cloud_healthcheck_voice_test", HEALTHCHECK_MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pcm_wav(*, frames: bytes | None = None) -> bytes:
    if frames is None:
        # 120 ms of an alternating, clearly non-silent PCM signal.
        frames = struct.pack("<hhhh", 0, 1_200, 0, -1_200) * 720
    channels = 1
    sample_rate = 24_000
    bits = 16
    block_align = channels * bits // 8
    byte_rate = sample_rate * block_align
    fmt = struct.pack(
        "<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits
    )
    data_padding = b"\x00" if len(frames) & 1 else b""
    chunks = (
        b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(frames)) + frames + data_padding
    )
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


class FakeSynthesizer:
    def __init__(self, *, result: bytes | None = None) -> None:
        self.loaded = False
        self.result = _pcm_wav() if result is None else result
        self.calls: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.loaded = True
        self.calls.append(text)
        return self.result


def test_standalone_voice_listener_is_loopback_only() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert 'host="127.0.0.1"' in source
    assert 'host="0.0.0.0"' not in source


def test_health_waits_for_bounded_synthesis_self_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    class BlockingSynthesizer(FakeSynthesizer):
        def synthesize(self, text: str) -> bytes:
            started.set()
            release.wait(timeout=1.0)
            return super().synthesize(text)

    synth = BlockingSynthesizer()
    client = FakeClient(module.create_app(secret="voice-secret", synthesizer=synth))

    response = client.get("/healthz")

    assert started.wait(timeout=1.0)
    assert response.status_code == 200
    assert response.json() == {
        "service": "alpecca-cloud-kokoro-voice",
        "version": 1,
        "state": "starting",
        "engine": "kokoro",
        "voice": "af_heart",
        "device": "cpu",
        "sampleRateHz": 24000,
        "modelLoaded": False,
        "selfCheckPassed": False,
        "selfCheckState": "running",
        "synthesisReady": False,
        "persistence": False,
        "coreMind": False,
        "singletonAuthority": False,
        "maxTextChars": module.MAX_TEXT_CHARS,
        "maxBodyBytes": module.MAX_BODY_BYTES,
    }
    assert "voice-secret" not in response.text

    release.set()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        response = client.get("/healthz")
        if response.json()["synthesisReady"]:
            break
        time.sleep(0.01)

    assert response.json()["state"] == "ready"
    assert response.json()["modelLoaded"] is True
    assert response.json()["selfCheckPassed"] is True
    assert response.json()["selfCheckState"] == "passed"
    assert response.json()["synthesisReady"] is True
    assert synth.calls == [module.SELF_CHECK_TEXT]
    assert len(synth.calls[0]) <= module.MAX_TEXT_CHARS


def test_health_rejects_invalid_or_timed_out_self_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    invalid = FakeSynthesizer(result=b"RIFF\x04\x00\x00\x00WAVE")
    invalid_client = FakeClient(
        module.create_app(secret="voice-secret", synthesizer=invalid)
    )

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        invalid_response = invalid_client.get("/healthz")
        if invalid_response.json()["selfCheckState"] == "failed":
            break
        time.sleep(0.01)

    assert invalid_response.json()["state"] == "unavailable"
    assert invalid_response.json()["modelLoaded"] is True
    assert invalid_response.json()["selfCheckPassed"] is False
    assert invalid_response.json()["synthesisReady"] is False

    release = threading.Event()

    class TimedOutSynthesizer(FakeSynthesizer):
        def synthesize(self, text: str) -> bytes:
            release.wait(timeout=1.0)
            return super().synthesize(text)

    timed_out = TimedOutSynthesizer()
    timeout_client = FakeClient(
        module.create_app(
            secret="voice-secret",
            synthesizer=timed_out,
            self_check_timeout_seconds=0.01,
        )
    )
    timeout_client.get("/healthz")
    time.sleep(0.03)
    timeout_response = timeout_client.get("/healthz")
    release.set()

    assert timeout_response.json()["state"] == "unavailable"
    assert timeout_response.json()["selfCheckState"] == "failed"
    assert timeout_response.json()["selfCheckPassed"] is False
    assert timeout_response.json()["synthesisReady"] is False


def test_wav_readiness_rejects_header_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)

    assert not module._valid_wav(b"RIFF\x04\x00\x00\x00WAVE")


def test_wav_readiness_rejects_silent_or_minuscule_pcm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    silent_frames = b"\x00\x00" * (module.SAMPLE_RATE_HZ // 5)

    assert not module._valid_wav(_pcm_wav(frames=silent_frames))
    assert not module._valid_wav(_pcm_wav(frames=struct.pack("<h", 1_200)))


def test_wav_readiness_accepts_meaningful_non_silent_pcm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)

    assert module._valid_wav(_pcm_wav())


def test_container_healthcheck_requires_complete_voice_readiness() -> None:
    healthcheck = _load_healthcheck_module()

    assert healthcheck.voice_synthesis_ready(
        {
            "state": "ready",
            "modelLoaded": True,
            "selfCheckPassed": True,
            "selfCheckState": "passed",
            "synthesisReady": True,
        }
    )
    assert not healthcheck.voice_synthesis_ready({"state": "ready"})
    assert not healthcheck.voice_synthesis_ready(
        {
            "state": "ready",
            "modelLoaded": False,
            "selfCheckPassed": True,
            "selfCheckState": "passed",
            "synthesisReady": True,
        }
    )
    assert not healthcheck.voice_synthesis_ready(
        {
            "state": "ready",
            "modelLoaded": True,
            "selfCheckPassed": False,
            "selfCheckState": "failed",
            "synthesisReady": False,
        }
    )


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
    assert accepted.content == _pcm_wav()
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


@pytest.mark.parametrize(
    "audio",
    [
        b"not-a-wave",
        _pcm_wav(frames=b"\x00\x00" * 4_800),
        _pcm_wav(frames=struct.pack("<h", 1_200)),
    ],
    ids=["malformed", "silent", "minuscule"],
)
def test_live_synthesis_rejects_unplayable_wav(
    monkeypatch: pytest.MonkeyPatch,
    audio: bytes,
) -> None:
    module = _load_module(monkeypatch)
    client = FakeClient(
        module.create_app(secret="secret", synthesizer=FakeSynthesizer(result=audio))
    )

    response = client.post(
        "/v1/voice/synthesize",
        json={"text": "live response"},
        headers={module.AUTHORIZATION_HEADER: "secret"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "invalid_synthesis_result"}


def test_live_synthesis_accepts_meaningful_non_silent_pcm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module(monkeypatch)
    audio = _pcm_wav()
    client = FakeClient(
        module.create_app(secret="secret", synthesizer=FakeSynthesizer(result=audio))
    )

    response = client.post(
        "/v1/voice/synthesize",
        json={"text": "live response"},
        headers={module.AUTHORIZATION_HEADER: "secret"},
    )

    assert response.status_code == 200
    assert response.content == audio
    assert response.headers["content-type"] == "audio/wav"


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
