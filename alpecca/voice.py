"""Voice-tone sense: Alpecca hears the room (Phase 4, tier 1).

This is deliberately *not* speech recognition. The sensor reduces the mic to
three coarse numbers per observation window -- how much of the window had
someone talking (`activity`), how loud that talking was (`loudness`), and
whether something abrupt just happened after quiet (`spike`). Those map onto
the mood pipeline the same honest way window titles do:

  - sustained loud talking  -> `raised_voice` fatigue signal -> Compassion
  - a sudden loud event     -> prediction error              -> Fear

Privacy stance, stated plainly: audio samples live only inside the capture
callback long enough to compute an RMS level, then they're gone. No waveform,
no transcript, nothing on disk. Even so, the whole sensor is opt-in
(ALPECCA_VOICE=1) because a microphone is more intimate than a window title.

Capture uses `sounddevice` when it's installed and a mic exists; otherwise the
sensor reports unavailable and every read is silence -- mirroring how
WindowSensor degrades off-Windows. All the *logic* (window analysis, spike
detection) is pure and testable without any audio hardware.
"""
from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass

from config import Voice as VoiceCfg


# --- Pure analysis ----------------------------------------------------------

@dataclass
class VoiceReading:
    """What Alpecca heard over one observation window, reduced to mood inputs."""

    activity: float = 0.0   # fraction of the window with voice-level energy
    loudness: float = 0.0   # how loud the active part was, 0..1
    spike: float = 0.0      # 1.0 if something abrupt broke a quiet stretch


def analyze_window(levels: list[float], prev_quiet: bool = True) -> VoiceReading:
    """Reduce a window of RMS levels (one per ~30ms chunk) to a VoiceReading.

    `prev_quiet` is whether the *previous* window was silent -- a loud peak only
    reads as a startle when it interrupts quiet. The same slam during an
    ongoing conversation is just life, the same way homeostasis ignores small
    prediction errors.
    """
    if not levels:
        return VoiceReading()

    active = [lv for lv in levels if lv >= VoiceCfg.SPEECH_THRESHOLD]
    activity = len(active) / len(levels)
    if active:
        loudness = min(1.0, (sum(active) / len(active)) / VoiceCfg.LOUD_REFERENCE)
    else:
        loudness = 0.0

    peak = max(levels)
    median = sorted(levels)[len(levels) // 2]
    abrupt = (peak >= VoiceCfg.SPIKE_MIN_LEVEL
              and peak >= VoiceCfg.SPIKE_RATIO * max(median, 1e-6))
    spike = 1.0 if (abrupt and prev_quiet) else 0.0

    return VoiceReading(activity=activity, loudness=loudness, spike=spike)


def rms(samples) -> float:
    """Root-mean-square of float samples in [-1, 1]. Pure-python on purpose --
    the chunks are ~480 samples, so this is cheap and avoids a numpy hard-dep."""
    n = len(samples)
    if n == 0:
        return 0.0
    return math.sqrt(sum(float(s) * float(s) for s in samples) / n)


# --- The sensor -------------------------------------------------------------

class VoiceSensor:
    """Background mic listener that accumulates per-chunk RMS levels and folds
    them into Observations on demand.

    Lifecycle mirrors WindowSensor: construct it once, check `.available`, and
    call `annotate(obs)` wherever an Observation is built. Construction never
    raises -- a missing sounddevice install, a machine with no mic, or the
    opt-in flag being off all land in the same quiet "unavailable" state.
    """

    def __init__(self) -> None:
        self._stream = None
        self._levels: deque[float] = deque(maxlen=2048)   # ~1 min of 30ms chunks
        self._lock = threading.Lock()
        self._prev_quiet = True
        if not VoiceCfg.ENABLED:
            return
        try:
            import sounddevice  # type: ignore

            blocksize = int(VoiceCfg.SAMPLE_RATE * VoiceCfg.BLOCK_SECONDS)

            def _callback(indata, frames, time_info, status) -> None:
                # Reduce to one number and drop the audio immediately.
                level = rms(indata[:, 0] if indata.ndim > 1 else indata)
                with self._lock:
                    self._levels.append(level)

            self._stream = sounddevice.InputStream(
                samplerate=VoiceCfg.SAMPLE_RATE, channels=1,
                blocksize=blocksize, callback=_callback,
            )
            self._stream.start()
        except Exception:
            self._stream = None  # no mic / no lib / no permission -> silent world

    @property
    def available(self) -> bool:
        return self._stream is not None

    def read(self) -> VoiceReading:
        """Analyze and clear everything heard since the last read."""
        with self._lock:
            levels = list(self._levels)
            self._levels.clear()
        reading = analyze_window(levels, prev_quiet=self._prev_quiet)
        self._prev_quiet = reading.activity < 0.1
        return reading

    def annotate(self, obs) -> None:
        """Fold the latest reading into an Observation in place. A no-op when
        the sensor is unavailable, so call sites don't need their own guard."""
        if not self.available:
            return
        reading = self.read()
        obs.voice_activity = reading.activity
        obs.voice_loudness = reading.loudness
        obs.voice_spike = reading.spike

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
