import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from alpecca import tts


def test_discord_kokoro_override_pins_af_heart_without_pitch_resampling(monkeypatch):
    calls = []
    written = []

    class Pipeline:
        def __call__(self, text, *, voice, speed):
            calls.append({"text": text, "voice": voice, "speed": speed})
            yield text, "", np.array([0.1, -0.1, 0.2, -0.2], dtype=np.float32)

    monkeypatch.setattr(tts, "KOKORO_VOICE", "am_adam")
    monkeypatch.setattr(tts, "_kokoro_pipeline", lambda: Pipeline())
    monkeypatch.setattr(
        tts,
        "_kokoro_dynamics",
        lambda _state: {"pitch": 0.915, "volume": 0.8, "speed": 1.1, "warmth": 0.5, "breath": 0.2},
    )
    monkeypatch.setattr(tts, "_shape_text_for_alpecca_voice", lambda text, _dyn: text)
    monkeypatch.setattr(tts, "_alpecca_voice_segments", lambda text, _dyn: [(text, 1.1, 0)])
    monkeypatch.setattr(tts, "_naturalize_audio", lambda audio, *_args: audio)
    monkeypatch.setattr(tts, "_varispeed", lambda *_args: pytest.fail("Discord must not resample af_heart"))
    monkeypatch.setattr(tts, "_KOKORO_CALL_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(
        tts,
        "voice_state",
        lambda _state: {"voice": "af_heart", "profile": "af_heart_original_modulated"},
    )
    monkeypatch.setitem(
        sys.modules,
        "soundfile",
        SimpleNamespace(write=lambda _buf, audio, rate, format: written.append((audio, rate, format))),
    )

    result = tts.synth("Pinned Discord voice.", backend_override="kokoro")

    assert result == ("audio/wav", b"")
    assert calls == [{"text": "Pinned Discord voice.", "voice": "af_heart", "speed": 1.1}]
    assert written and written[0][1:] == (24000, "WAV")
    assert tts._last_modulation["voice"] == "af_heart"
    assert tts._last_modulation["profile"] == "af_heart_identity_locked"
    assert tts._last_modulation["pitch_resampling"] is False
    assert tts._last_modulation["native_speed"] is True


def test_kokoro_timeout_is_single_flight_and_reported_without_claiming_ready(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(tts, "_kokoro_call", None)
    monkeypatch.setattr(tts, "_KOKORO_CALL_TIMEOUT_SECONDS", 0.01)

    def blocked_call(_text, _state, *, identity_profile):
        assert identity_profile is False
        started.set()
        release.wait(1)
        return "audio/wav", b"late"

    monkeypatch.setattr(tts, "_synth_kokoro_unbounded", blocked_call)
    try:
        began = time.monotonic()
        assert tts._synth_kokoro("cold call") is None
        assert time.monotonic() - began < 0.2
        assert started.wait(0.1)
        assert tts._synth_kokoro("duplicate cold call") is None
        status = tts.kokoro_status()
        assert status["state"] == "warming_or_synthesizing"
        assert status["ready"] is False
        assert status["last_timeout_seconds"] == 0.01
        assert "deadline" in status["last_error"]
    finally:
        release.set()
        with tts._kokoro_call_lock:
            call = tts._kokoro_call
        if call is not None:
            assert call["done"].wait(0.2)
