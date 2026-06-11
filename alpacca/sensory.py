"""The sensory layer: what is the user doing right now?

The spec calls this the "Sensory Modem" -- screen tracking, audio, a temporal
sense of idleness. The most informative and least invasive of these is the
*active window title*, so that's what we build out fully here. It tells us a
surprising amount: which app has focus, often the document or error you're
looking at, and -- via timing -- whether you've stepped away.

Design choices that matter:
  - Windows uses the Win32 API (via pywin32). Everything else gets a best-effort
    fallback so the code still runs and tests pass off-Windows. The companion
    degrades gracefully rather than refusing to start.
  - We convert raw observations into the `fatigue_signals` and `prediction_error`
    that homeostasis.py consumes, so the senses connect directly to the mood.

Privacy: this watches *you*, on *your* machine. Window titles can contain
sensitive text. Keep the data local (it never leaves this process unless you add
that yourself) and be deliberate about retention -- telemetry.jsonl is yours to
prune.
"""
from __future__ import annotations

import platform
import time
from dataclasses import dataclass, field

_IS_WINDOWS = platform.system() == "Windows"

# Words in a window title that suggest the user is wrestling with something.
_ERROR_HINTS = (
    "error", "exception", "traceback", "failed", "failure", "denied",
    "cannot", "fatal", "undefined", "null", "crash", "stack",
)


@dataclass
class Observation:
    """One snapshot of the user's situation, derived from the senses."""

    window_title: str = ""
    app: str = ""
    idle_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)
    # Voice-tone sense (alpacca/voice.py), all zero when the mic sensor is off.
    # Coarse loudness numbers only -- never audio, never words.
    voice_activity: float = 0.0   # how much talking was heard this window
    voice_loudness: float = 0.0   # how loud the talking was, 0..1
    voice_spike: float = 0.0      # 1.0 if something abrupt broke a quiet stretch

    # --- Derived reads the emotional model cares about ---------------------

    def is_error_context(self) -> float:
        title = self.window_title.lower()
        return 1.0 if any(h in title for h in _ERROR_HINTS) else 0.0

    def fatigue_signals(self, session_minutes: float) -> dict:
        """Translate this observation into the fatigue inputs Compassion wants.

        We read the local hour for `late_night`, session length for
        `long_session`, the title for `error_context`, and a recent idle gap as
        `idle_return` (a break tends to refresh, so it lowers perceived fatigue).
        """
        hour = time.localtime(self.timestamp).tm_hour
        late = 1.0 if (hour >= 23 or hour < 5) else 0.0
        # Session fatigue ramps in over ~90 minutes, then saturates.
        long_session = min(1.0, session_minutes / 90.0)
        just_returned = 1.0 if self.idle_seconds > 300 else 0.0
        # Sustained loud talking reads as stress. Brief or quiet speech doesn't
        # register -- we only pass loudness through when there was real talking.
        raised_voice = self.voice_loudness if self.voice_activity > 0.3 else 0.0
        return {
            "late_night": late,
            "long_session": long_session,
            "error_context": self.is_error_context(),
            "idle_return": just_returned,
            "raised_voice": raised_voice,
        }


class WindowSensor:
    """Reads the foreground window title. Real on Windows, simulated elsewhere.

    The sensor also tracks how long the foreground title has been unchanged --
    that's our cheap proxy for user idleness. Keeping the bookkeeping here means
    every caller (the chat path, the background drift loop, the standalone
    telemetry script) gets a real `idle_seconds` instead of always-zero, which
    is what the Compassion model's `idle_return` signal actually needs.
    """

    def __init__(self) -> None:
        self._win32 = None
        self._last_title: str | None = None
        self._last_change = time.time()
        if _IS_WINDOWS:
            try:
                import win32gui  # type: ignore
                self._win32 = win32gui
            except Exception:
                self._win32 = None  # pywin32 missing; fall back to stub

    @property
    def available(self) -> bool:
        return self._win32 is not None

    def _read_windows(self) -> str:
        try:
            hwnd = self._win32.GetForegroundWindow()
            return self._win32.GetWindowText(hwnd) or ""
        except Exception:
            return ""

    def observe(self) -> Observation:
        """Return the current Observation. On non-Windows machines (or without
        pywin32) this yields an empty title so the rest of the pipeline still
        runs -- the loop just sees a quiet, uneventful world."""
        title = self._read_windows() if self._win32 else ""
        now = time.time()
        if title != self._last_title:
            self._last_title = title
            self._last_change = now
        idle = now - self._last_change
        app = title.split(" - ")[-1].strip() if " - " in title else ""
        return Observation(window_title=title, app=app, idle_seconds=idle)


def prediction_error(prev: Observation | None, curr: Observation) -> float:
    """A crude 'how surprising is this moment' signal in [0, 1] -- the input to
    Fear.

    The spec frames Fear around runtime-integrity / unexpected change. We
    approximate that here as: a jump into an error context, or an abrupt switch
    of application after a long stable focus, is mildly surprising. This is a
    placeholder you can make as paranoid as you like (e.g. watch for unknown
    processes touching Alpacca's own files).
    """
    if prev is None:
        return 0.0
    surprise = 0.0
    if curr.is_error_context() and not prev.is_error_context():
        surprise += 0.5
    if curr.app and prev.app and curr.app != prev.app:
        surprise += 0.2
    # A sudden loud sound after quiet (a slam, a shout) is the most literal
    # violated-expectation the senses can deliver.
    surprise += 0.5 * curr.voice_spike
    return min(1.0, surprise)
