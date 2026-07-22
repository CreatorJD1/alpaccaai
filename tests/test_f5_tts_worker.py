from __future__ import annotations

import json
import sys
from types import ModuleType

import numpy as np
import pytest

from alpecca import open_tts
from alpecca.state import EmotionalState
from scripts import f5_tts_worker


def test_open_tts_maps_affect_to_bounded_f5_controls() -> None:
    sleepy = open_tts._voice_controls(EmotionalState(energy=0.05, love=0.4))
    lively = open_tts._voice_controls(
        EmotionalState(energy=0.95, curiosity=0.8, love=0.8)
    )

    assert sleepy["speed"] == 0.8
    assert lively["speed"] == 1.2
    assert sleepy["style"] != lively["style"]
    assert 0.55 <= sleepy["gain"] <= 1.2
    assert 0.55 <= lively["gain"] <= 1.2


def test_open_tts_sends_modulation_and_reports_worker_values(monkeypatch) -> None:
    sent = {}
    applied = {
        "speed": 1.2,
        "gain": 1.1,
        "requested_gain": 1.2,
        "style": "bright",
        "cfg_strength": 2.1,
        "sway_sampling_coef": -0.8,
    }

    class Response:
        status = 200
        headers = {"X-Alpecca-F5-Worker": json.dumps({"applied": applied})}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b"w" * 2048

    def urlopen(request, timeout):
        sent.update(json.loads(request.data.decode("utf-8")))
        assert timeout >= 3.0
        return Response()

    monkeypatch.setattr(open_tts, "F5_WORKER_ENABLED", True)
    monkeypatch.setattr(open_tts.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(open_tts, "_wav_quality_issue", lambda _data: "")
    controls = {
        "speed": 1.2,
        "gain": 1.2,
        "style": "bright",
        "primary": "joyful",
        "rate_pct": 120,
        "volume": 1.0,
    }

    result = open_tts._worker_synth(
        "A lively line.",
        {"audio": "reference.wav", "text": "reference", "id": "bright"},
        controls,
    )

    assert sent["speed"] == 1.2
    assert sent["gain"] == 1.2
    assert sent["style"] == "bright"
    assert sent["primary"] == "joyful"
    assert result is not None
    assert result[2]["requested_modulation"] == controls
    assert result[2]["applied_modulation"] == applied
    assert open_tts.status()["last_worker"]["applied"] == applied


def test_worker_applies_f5_style_speed_and_gain_without_logging_text(
    monkeypatch, capsys
) -> None:
    secret = "private Discord sentence must not enter worker logs"
    f5_package = ModuleType("f5_tts")
    f5_package.__path__ = []
    infer_package = ModuleType("f5_tts.infer")
    infer_package.__path__ = []
    utils = ModuleType("f5_tts.infer.utils_infer")
    soundfile = ModuleType("soundfile")
    inference = {}
    written = {}

    def preprocess(ref_audio, ref_text, *, show_info):
        del show_info
        print(f"ref_audio={ref_audio} ref_text={ref_text} {secret}")
        return ref_audio, ref_text

    def infer(*_args, **kwargs):
        inference.update(kwargs)
        print(f"gen_text={secret}", file=sys.stderr)
        return np.asarray([-0.4, 0.4], dtype=np.float32), 24_000, None

    def write(buffer, wave, sample_rate, *, format):
        assert format == "WAV"
        written["wave"] = np.asarray(wave)
        written["sample_rate"] = sample_rate
        buffer.write(b"w" * 2048)

    utils.preprocess_ref_audio_text = preprocess
    utils.infer_process = infer
    soundfile.write = write
    monkeypatch.setitem(sys.modules, "f5_tts", f5_package)
    monkeypatch.setitem(sys.modules, "f5_tts.infer", infer_package)
    monkeypatch.setitem(sys.modules, "f5_tts.infer.utils_infer", utils)
    monkeypatch.setitem(sys.modules, "soundfile", soundfile)
    monkeypatch.setattr(f5_tts_worker, "_ready", True)
    monkeypatch.setattr(f5_tts_worker, "_model", object())
    monkeypatch.setattr(f5_tts_worker, "_vocoder", object())

    audio, metadata = f5_tts_worker.synth(
        secret,
        "reference.wav",
        "private reference transcript",
        4,
        speed=1.2,
        gain=0.75,
        style="bright",
    )

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert audio == b"w" * 2048
    assert inference["speed"] == 1.2
    assert inference["cfg_strength"] == 2.1
    assert inference["sway_sampling_coef"] == -0.8
    assert written["sample_rate"] == 24_000
    assert float(np.max(np.abs(written["wave"]))) == pytest.approx(0.3)
    assert metadata["applied"]["style"] == "bright"
    assert metadata["applied"]["requested_gain"] == 0.75
    assert metadata["applied"]["gain"] == pytest.approx(0.75)


def test_f5_waveform_applies_gain_then_peak_limits() -> None:
    samples, input_peak, applied_gain, limiter_gain, output_peak = (
        f5_tts_worker._normalize_waveform(
            np.asarray([-1.6, -0.25, 0.4, 1.2], dtype=np.float32),
            requested_gain=1.1,
        )
    )

    assert input_peak == pytest.approx(1.6)
    assert limiter_gain < 1.0
    assert applied_gain == pytest.approx(0.575)
    assert output_peak == pytest.approx(0.92)
    assert float(np.max(np.abs(samples))) == pytest.approx(0.92)


def test_f5_worker_clamps_untrusted_controls() -> None:
    assert f5_tts_worker._controls(9.0, -2.0, "unknown") == {
        "speed": 1.2,
        "gain": 0.55,
        "style": "present",
        "cfg_strength": 2.0,
        "sway_sampling_coef": -1.0,
    }


@pytest.mark.parametrize("samples", [[], [float("nan")], [float("inf")]])
def test_f5_waveform_rejects_empty_or_nonfinite_audio(samples: list[float]) -> None:
    with pytest.raises(RuntimeError, match="invalid waveform"):
        f5_tts_worker._normalize_waveform(samples)
