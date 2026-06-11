"""Tests for the pure scaling logic and action dispatch in ``alpaccaai.tools``.

These run without a display by injecting a fake backend.
"""

from __future__ import annotations

import math

import pytest

from alpaccaai.tools import (
    MAX_LONG_EDGE,
    MAX_TOTAL_PIXELS,
    ComputerTool,
    ToolError,
    get_scale_factor,
    scaled_dimensions,
    to_native_coordinate,
)


class FakeBackend:
    """Records calls instead of touching a real screen."""

    def __init__(self):
        self.calls = []

    def screenshot_png(self, width, height):
        self.calls.append(("screenshot", width, height))
        return b"\x89PNG\r\n\x1a\n"  # minimal PNG signature; enough for the test

    def move(self, x, y):
        self.calls.append(("move", x, y))

    def click(self, x, y, button, count, modifiers):
        self.calls.append(("click", x, y, button, count, tuple(modifiers)))

    def type_text(self, text):
        self.calls.append(("type", text))

    def press_key(self, keys):
        self.calls.append(("key", tuple(keys)))

    def scroll(self, x, y, direction, amount, modifiers):
        self.calls.append(("scroll", x, y, direction, amount, tuple(modifiers)))


def test_no_scaling_for_small_display():
    assert get_scale_factor(1024, 768) == 1.0
    assert scaled_dimensions(1024, 768) == (1024, 768)


def test_scaling_respects_long_edge():
    scale = get_scale_factor(3840, 2160)
    assert scale < 1.0
    w, h = scaled_dimensions(3840, 2160)
    assert max(w, h) <= MAX_LONG_EDGE
    assert w * h <= MAX_TOTAL_PIXELS + 1


def test_coordinate_round_trips_back_to_native():
    # A 4K display: a click at the scaled centre maps near the native centre.
    width, height = 3840, 2160
    sw, sh = scaled_dimensions(width, height)
    nx, ny = to_native_coordinate(sw // 2, sh // 2, width, height)
    assert math.isclose(nx, width / 2, rel_tol=0.02)
    assert math.isclose(ny, height / 2, rel_tol=0.02)


def test_tool_params_match_scaled_dimensions():
    tool = ComputerTool(3840, 2160, backend=FakeBackend())
    params = tool.to_params()
    sw, sh = scaled_dimensions(3840, 2160)
    assert params["display_width_px"] == sw
    assert params["display_height_px"] == sh
    assert params["type"] == "computer_20251124"
    assert params["enable_zoom"] is True


def test_display_number_included_only_when_set():
    assert "display_number" not in ComputerTool(800, 600, backend=FakeBackend()).to_params()
    tool = ComputerTool(800, 600, display_number=1, backend=FakeBackend())
    assert tool.to_params()["display_number"] == 1


def test_click_maps_coordinate_to_native_space():
    backend = FakeBackend()
    tool = ComputerTool(2576, 1449, backend=backend)  # forces downscaling
    sw, sh = scaled_dimensions(2576, 1449)
    tool.run({"action": "left_click", "coordinate": [sw // 2, sh // 2]})
    click = next(c for c in backend.calls if c[0] == "click")
    _, x, y, button, count, mods = click
    assert button == "left" and count == 1 and mods == ()
    assert math.isclose(x, 2576 / 2, rel_tol=0.02)


def test_double_and_triple_click_counts():
    backend = FakeBackend()
    tool = ComputerTool(800, 600, backend=backend)
    tool.run({"action": "double_click", "coordinate": [10, 10]})
    tool.run({"action": "triple_click", "coordinate": [10, 10]})
    counts = [c[4] for c in backend.calls if c[0] == "click"]
    assert counts == [2, 3]


def test_click_with_modifier_key():
    backend = FakeBackend()
    tool = ComputerTool(800, 600, backend=backend)
    tool.run({"action": "left_click", "coordinate": [10, 10], "text": "shift"})
    click = next(c for c in backend.calls if c[0] == "click")
    assert click[5] == ("shift",)


def test_type_and_key_actions():
    backend = FakeBackend()
    tool = ComputerTool(800, 600, backend=backend)
    tool.run({"action": "type", "text": "hello"})
    tool.run({"action": "key", "text": "ctrl+s"})
    assert ("type", "hello") in backend.calls
    assert ("key", ("ctrl", "s")) in backend.calls


def test_out_of_bounds_coordinate_is_an_error():
    backend = FakeBackend()
    tool = ComputerTool(800, 600, backend=backend)
    result = tool.run({"action": "left_click", "coordinate": [9999, 9999]})
    assert result.is_error
    assert "outside display bounds" in result.output


def test_unsupported_action_is_an_error():
    tool = ComputerTool(800, 600, backend=FakeBackend())
    result = tool.run({"action": "fly_to_the_moon"})
    assert result.is_error


def test_screenshot_returns_base64_image():
    tool = ComputerTool(800, 600, backend=FakeBackend())
    result = tool.run({"action": "screenshot"})
    assert result.base64_image
    assert not result.is_error


def test_invalid_modifier_is_rejected():
    tool = ComputerTool(800, 600, backend=FakeBackend())
    result = tool.run({"action": "left_click", "coordinate": [10, 10], "text": "bogus"})
    assert result.is_error
