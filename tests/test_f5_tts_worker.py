from __future__ import annotations

import sys
from types import ModuleType

from scripts import f5_tts_worker


def test_worker_suppresses_third_party_text_output(monkeypatch, capsys):
    secret = "private Discord sentence must not enter worker logs"
    f5_package = ModuleType("f5_tts")
    f5_package.__path__ = []
    infer_package = ModuleType("f5_tts.infer")
    infer_package.__path__ = []
    utils = ModuleType("f5_tts.infer.utils_infer")
    soundfile = ModuleType("soundfile")

    def preprocess(ref_audio, ref_text, *, show_info):
        del show_info
        print(f"ref_audio={ref_audio} ref_text={ref_text} {secret}")
        return ref_audio, ref_text

    def infer(*_args, **_kwargs):
        print(f"gen_text={secret}", file=sys.stderr)
        return object(), 24_000, None

    def write(buffer, _wave, _sample_rate, *, format):
        assert format == "WAV"
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
    )

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert audio == b"w" * 2048
    assert metadata["bytes"] == 2048
