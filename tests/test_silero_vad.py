from __future__ import annotations

import numpy as np

from alpecca import discord_voice, silero_vad


def _packet(seconds: float = 0.02, *, amplitude: int = 0) -> bytes:
    frames = int(discord_voice.PCM_SAMPLE_RATE * seconds)
    samples = np.full((frames, 2), amplitude, dtype="<i2")
    return samples.tobytes()


class _FakeVad:
    def __init__(self, probabilities: list[float], *, fail: bool = False) -> None:
        self.probabilities = list(probabilities)
        self.fail = fail
        self.resets = 0

    def accept_pcm(self, _pcm: bytes) -> tuple[float, ...]:
        if self.fail:
            raise RuntimeError("test detector failed")
        if not self.probabilities:
            return ()
        return (self.probabilities.pop(0),)

    def reset(self) -> None:
        self.resets += 1


def test_vad_waits_for_two_positive_frames_and_preserves_pre_roll(monkeypatch):
    monkeypatch.setattr(discord_voice, "VAD_START_FRAMES", 2)
    starts: list[str] = []
    utterances: list[discord_voice.VoiceUtterance] = []
    detector = _FakeVad([0.9] * 20)
    collector = discord_voice.CreatorPcmCollector(
        42,
        utterances.append,
        on_speech_start=lambda: starts.append("start"),
        vad=detector,
    )

    assert collector.push(42, _packet()) == "vad-waiting"
    assert collector.push(42, _packet()) == "buffered"
    for _ in range(18):
        assert collector.push(42, _packet()) == "buffered"
    assert collector.finish(42) is True

    assert starts == ["start"]
    assert len(utterances) == 1
    # Both confirmation packets are retained, including the first one.
    assert 0.39 <= utterances[0].duration_seconds <= 0.41
    assert detector.resets == 1


def test_vad_noise_never_starts_or_emits(monkeypatch):
    monkeypatch.setattr(discord_voice, "VAD_START_FRAMES", 2)
    starts: list[str] = []
    utterances: list[discord_voice.VoiceUtterance] = []
    collector = discord_voice.CreatorPcmCollector(
        42,
        utterances.append,
        on_speech_start=lambda: starts.append("start"),
        vad=_FakeVad([0.01] * 30),
    )

    for _ in range(25):
        assert collector.push(42, _packet()) == "vad-waiting"
    assert collector.finish(42) is False
    assert starts == []
    assert utterances == []


def test_vad_silence_endpoint_emits_without_discord_stop(monkeypatch):
    monkeypatch.setattr(discord_voice, "VAD_START_FRAMES", 2)
    monkeypatch.setattr(discord_voice, "VAD_END_FRAMES", 5)
    utterances: list[discord_voice.VoiceUtterance] = []
    detector = _FakeVad([0.9] * 20 + [0.01] * 5)
    collector = discord_voice.CreatorPcmCollector(42, utterances.append, vad=detector)

    disposition = ""
    for _ in range(25):
        disposition = collector.push(42, _packet())

    assert disposition == "emitted-vad"
    assert len(utterances) == 1
    assert utterances[0].duration_seconds >= discord_voice.MIN_UTTERANCE_SECONDS


def test_vad_runtime_failure_restores_packet_fallback():
    starts: list[str] = []
    utterances: list[discord_voice.VoiceUtterance] = []
    collector = discord_voice.CreatorPcmCollector(
        42,
        utterances.append,
        on_speech_start=lambda: starts.append("start"),
        vad=_FakeVad([], fail=True),
    )

    for _ in range(20):
        assert collector.push(42, _packet()) == "buffered"
    assert collector.finish(42) is True
    assert starts == ["start"]
    assert len(utterances) == 1


class _Session:
    def __init__(self) -> None:
        self.inputs: list[dict[str, np.ndarray]] = []

    def run(self, _outputs, inputs):
        self.inputs.append(inputs)
        state = np.ones((2, 1, 128), dtype=np.float32)
        return np.asarray([[0.75]], dtype=np.float32), state


def test_onnx_adapter_downsamples_stereo_48k_and_carries_state():
    session = _Session()
    detector = silero_vad.SileroOnnxDetector(session=session)

    probabilities = detector.accept_pcm(_packet(0.032, amplitude=8192))

    assert probabilities == (0.75,)
    assert len(session.inputs) == 1
    inputs = session.inputs[0]
    assert inputs["input"].shape == (
        1,
        silero_vad.CONTEXT_SAMPLES + silero_vad.FRAME_SAMPLES,
    )
    assert inputs["input"].dtype == np.float32
    assert np.allclose(inputs["input"][:, :silero_vad.CONTEXT_SAMPLES], 0.0)
    assert np.allclose(inputs["input"][:, silero_vad.CONTEXT_SAMPLES:], 0.25)
    assert inputs["state"].shape == (2, 1, 128)
    assert int(inputs["sr"]) == 16_000


def test_readiness_is_content_free():
    posture = silero_vad.readiness()

    assert posture["engine"] in {"silero-onnx-cpu", "packet-fallback"}
    assert posture["sample_rate"] == 16_000
    assert "model" not in posture or isinstance(posture.get("model"), bool)
