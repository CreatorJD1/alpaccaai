"""The computer use tool implementation for alpaccaai.

This module turns Claude's abstract computer-use actions ("take a screenshot",
"click at (x, y)", "type this text") into real input on the local machine.

The Claude API constrains screenshots to a maximum long edge and total pixel
count and returns coordinates *in the scaled image space*. We therefore:

  1. Capture the screen at native resolution.
  2. Downscale it to fit the API limits before sending it to Claude.
  3. Scale Claude's returned coordinates back up to native space before
     performing the action.

The scaling math is kept as pure functions so it can be unit-tested without a
display or any GUI dependencies. The actual screen I/O is performed through a
``Backend`` that is imported lazily, so importing this module never requires a
display to be present.
"""

from __future__ import annotations

import base64
import io
import math
import time
from dataclasses import dataclass

# API image constraints (see the computer use documentation).
MAX_LONG_EDGE = 1568
MAX_TOTAL_PIXELS = 1_150_000

# Modifier keys that may accompany click/scroll actions via the ``text`` field.
_MODIFIER_KEYS = {"shift", "ctrl", "alt", "super"}


def get_scale_factor(width: int, height: int) -> float:
    """Return the factor to multiply ``width``/``height`` by to satisfy API limits.

    Never upscales (caps at 1.0).
    """
    long_edge = max(width, height)
    total_pixels = width * height
    long_edge_scale = MAX_LONG_EDGE / long_edge
    total_pixels_scale = math.sqrt(MAX_TOTAL_PIXELS / total_pixels)
    return min(1.0, long_edge_scale, total_pixels_scale)


def scaled_dimensions(width: int, height: int) -> tuple[int, int]:
    """Return the (width, height) a screenshot should be downscaled to."""
    scale = get_scale_factor(width, height)
    return int(width * scale), int(height * scale)


def to_native_coordinate(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    """Map a coordinate from scaled image space back to native screen space."""
    scale = get_scale_factor(width, height)
    if scale == 0:
        return x, y
    return round(x / scale), round(y / scale)


class ToolError(Exception):
    """Raised when an action cannot be performed; surfaced to Claude as an error."""


@dataclass
class ToolResult:
    """The result of running one computer action.

    ``output`` is human-readable text, ``base64_image`` is an optional
    base64-encoded PNG screenshot, and ``is_error`` flags failures.
    """

    output: str | None = None
    base64_image: str | None = None
    is_error: bool = False


class Backend:
    """Performs real screen I/O via pyautogui / Pillow.

    Imported lazily so that this module (and its pure helpers) can be used
    without a display attached.
    """

    def __init__(self) -> None:
        try:
            import pyautogui  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ToolError(
                "pyautogui is required to control the computer. "
                "Install alpaccaai with its GUI extras: pip install 'alpaccaai[gui]'"
            ) from exc

        # Disable the fail-safe corner so deliberate moves to (0, 0) don't abort,
        # but keep a small pause so target apps have time to react.
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.1
        self._pyautogui = pyautogui

    def size(self) -> tuple[int, int]:
        return tuple(self._pyautogui.size())  # type: ignore[return-value]

    def screenshot_png(self, width: int, height: int) -> bytes:
        """Capture the screen, downscale to API limits, return PNG bytes."""
        image = self._pyautogui.screenshot()
        target = scaled_dimensions(width, height)
        if target != image.size:
            from PIL import Image  # type: ignore

            image = image.resize(target, Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def move(self, x: int, y: int) -> None:
        self._pyautogui.moveTo(x, y)

    def click(self, x: int, y: int, button: str, count: int, modifiers: list[str]) -> None:
        for key in modifiers:
            self._pyautogui.keyDown(key)
        try:
            self._pyautogui.click(x=x, y=y, clicks=count, button=button, interval=0.05)
        finally:
            for key in reversed(modifiers):
                self._pyautogui.keyUp(key)

    def type_text(self, text: str) -> None:
        self._pyautogui.write(text, interval=0.01)

    def press_key(self, keys: list[str]) -> None:
        # A combination like "ctrl+s" is pressed as a hotkey; a single key is tapped.
        if len(keys) > 1:
            self._pyautogui.hotkey(*keys)
        else:
            self._pyautogui.press(keys[0])

    def scroll(self, x: int, y: int, direction: str, amount: int, modifiers: list[str]) -> None:
        self._pyautogui.moveTo(x, y)
        clicks = amount * 100
        for key in modifiers:
            self._pyautogui.keyDown(key)
        try:
            if direction in ("up", "down"):
                self._pyautogui.scroll(clicks if direction == "up" else -clicks)
            else:
                self._pyautogui.hscroll(clicks if direction == "right" else -clicks)
        finally:
            for key in reversed(modifiers):
                self._pyautogui.keyUp(key)


# Map Claude's xdotool-style key names to pyautogui names where they differ.
_KEY_ALIASES = {
    "super": "win",
    "return": "enter",
    "page_down": "pagedown",
    "page_up": "pageup",
}


def _normalise_keys(combo: str) -> list[str]:
    return [_KEY_ALIASES.get(part.lower(), part.lower()) for part in combo.split("+")]


class ComputerTool:
    """Dispatches Claude's computer-use actions to a :class:`Backend`."""

    def __init__(self, width: int, height: int, display_number: int | None = None,
                 backend: Backend | None = None) -> None:
        self.width = width
        self.height = height
        self.display_number = display_number
        self._backend = backend

    @property
    def backend(self) -> Backend:
        if self._backend is None:
            self._backend = Backend()
        return self._backend

    def to_params(self) -> dict:
        """The tool definition block to send to the Claude API.

        ``display_*`` must match the dimensions of the image actually sent,
        i.e. the *scaled* size, not the native screen size.
        """
        scaled_w, scaled_h = scaled_dimensions(self.width, self.height)
        params = {
            "type": "computer_20251124",
            "name": "computer",
            "display_width_px": scaled_w,
            "display_height_px": scaled_h,
            "enable_zoom": True,
        }
        if self.display_number is not None:
            params["display_number"] = self.display_number
        return params

    def _native(self, coordinate) -> tuple[int, int]:
        if not coordinate or len(coordinate) != 2:
            raise ToolError(f"Invalid coordinate: {coordinate!r}")
        x, y = coordinate
        scaled_w, scaled_h = scaled_dimensions(self.width, self.height)
        if not (0 <= x <= scaled_w and 0 <= y <= scaled_h):
            raise ToolError(
                f"Coordinate ({x}, {y}) is outside display bounds "
                f"({scaled_w}x{scaled_h})."
            )
        return to_native_coordinate(x, y, self.width, self.height)

    def screenshot(self) -> ToolResult:
        png = self.backend.screenshot_png(self.width, self.height)
        return ToolResult(base64_image=base64.b64encode(png).decode("ascii"))

    def run(self, action_input: dict) -> ToolResult:
        """Execute one action described by Claude's tool-use ``input``."""
        action = action_input.get("action")
        modifiers = []
        text = action_input.get("text")

        try:
            if action == "screenshot":
                return self.screenshot()

            if action == "mouse_move":
                x, y = self._native(action_input.get("coordinate"))
                self.backend.move(x, y)

            elif action in ("left_click", "right_click", "middle_click",
                            "double_click", "triple_click"):
                x, y = self._native(action_input.get("coordinate"))
                if text:
                    modifiers = _normalise_modifiers(text)
                button = {"left_click": "left", "right_click": "right",
                          "middle_click": "middle", "double_click": "left",
                          "triple_click": "left"}[action]
                count = {"double_click": 2, "triple_click": 3}.get(action, 1)
                self.backend.click(x, y, button, count, modifiers)

            elif action == "type":
                if text is None:
                    raise ToolError("'type' action requires 'text'.")
                self.backend.type_text(text)

            elif action == "key":
                if text is None:
                    raise ToolError("'key' action requires 'text'.")
                self.backend.press_key(_normalise_keys(text))

            elif action == "scroll":
                x, y = self._native(action_input.get("coordinate"))
                direction = action_input.get("scroll_direction", "down")
                amount = int(action_input.get("scroll_amount", 3))
                hold = action_input.get("text")
                if hold:
                    modifiers = _normalise_modifiers(hold)
                self.backend.scroll(x, y, direction, amount, modifiers)

            elif action == "wait":
                time.sleep(float(action_input.get("duration", 1)))

            else:
                raise ToolError(f"Unsupported action: {action!r}")

        except ToolError as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)
        except Exception as exc:  # surface unexpected backend failures to Claude
            return ToolResult(output=f"Error performing {action}: {exc}", is_error=True)

        # After a state-changing action, return a fresh screenshot so Claude can
        # observe the result (matching the docs' "evaluate after each step" advice).
        return self.screenshot()


def _normalise_modifiers(text: str) -> list[str]:
    mods = []
    for part in text.split("+"):
        key = part.lower()
        if key not in _MODIFIER_KEYS:
            raise ToolError(f"Unsupported modifier key: {part!r}")
        mods.append(_KEY_ALIASES.get(key, key))
    return mods
