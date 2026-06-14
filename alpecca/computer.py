"""Computer use: Alpecca sees the screen and works the mouse and keyboard.

This is the local, on-machine version of the screenshot -> reason -> act loop.
She captures the screen, her own vision model decides the next action, and
pyautogui carries it out -- then she looks again. No screenshots leave the
machine; this is the same privacy line as every other sense.

Two safety properties are built in, matching the owner's chosen settings:

  - **Opt-in.** Nothing here runs unless ALPECCA_COMPUTER_USE=1. Handing a
    program the mouse is a real grant, made once, on purpose.
  - **Confirm consequential actions.** Each proposed action is classified.
    Reversible things (open, click into a field, scroll, read) she does
    freely; anything consequential -- sending, deleting, buying, posting,
    installing, overwriting -- pauses for the person's yes/no. Classification
    is defense-in-depth: her vision model self-declares whether an action is
    consequential, AND a keyword net catches send/delete/buy/etc. on the
    action's target or typed text. Either trips the gate.

The driver (`run_task`) is injected with `confirm` and `status` callbacks so
the server can surface confirmations and progress over the WebSocket while the
loop runs off-thread. The pure pieces -- action parsing, the consequential
classifier, coordinate scaling -- are tested without any screen or model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from config import Computer as ComputerCfg, OLLAMA_HOST
from config import Vision as VisionCfg


# --- One proposed action ----------------------------------------------------

@dataclass
class Action:
    kind: str                      # left_click | type | key | scroll | done | wait
    coordinate: Optional[list] = None
    text: str = ""
    keys: str = ""                 # e.g. "ctrl+s", "enter"
    scroll_direction: str = "down"
    scroll_amount: int = 3
    target: str = ""               # her description of what she's acting on
    reason: str = ""               # why, in her words
    self_consequential: bool = False  # her own judgment
    done_summary: str = ""         # set when kind == "done"


def parse_action(raw: str) -> Optional[Action]:
    """Pull one action object out of the model's reply. Tolerant of the prose
    and code fences models wrap JSON in; returns None when there's no usable
    object."""
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        d = json.loads(text[start:end + 1])
    except Exception:
        return None
    kind = str(d.get("action") or d.get("kind") or "").strip().lower()
    if not kind:
        return None
    coord = d.get("coordinate") or d.get("coord")
    if isinstance(coord, list) and len(coord) == 2:
        try:
            coord = [int(coord[0]), int(coord[1])]
        except Exception:
            coord = None
    else:
        coord = None
    return Action(
        kind=kind,
        coordinate=coord,
        text=str(d.get("text", "")),
        keys=str(d.get("keys", "")),
        scroll_direction=str(d.get("scroll_direction", "down")),
        scroll_amount=int(d.get("scroll_amount", 3) or 3),
        target=str(d.get("target", "")),
        reason=str(d.get("reason", "")),
        self_consequential=bool(d.get("consequential", False)),
        done_summary=str(d.get("summary", "")),
    )


def is_consequential(action: Action) -> bool:
    """Should this action pause for confirmation? True if she flagged it, or if
    the keyword net trips on what she's acting on or typing. Pure + tested."""
    if action.self_consequential:
        return True
    haystack = f"{action.target} {action.text} {action.keys} {action.reason}".lower()
    return any(hint in haystack for hint in ComputerCfg.CONSEQUENTIAL_HINTS)


# --- Coordinate scaling ------------------------------------------------------

def scale_factor(width: int, height: int, long_edge: int) -> float:
    """How much the screenshot is shrunk before her vision model reads it.
    Coordinates she returns get divided by this to land on the real screen."""
    longest = max(width, height)
    if longest <= long_edge:
        return 1.0
    return long_edge / longest


# --- The prompt she works from ----------------------------------------------

_SYSTEM = (
    "You are operating this computer to help the person with a task. You see a "
    "screenshot and choose ONE next action. Coordinates are in the pixels of "
    "the image you are shown, origin top-left.\n\n"
    "Reply with STRICT JSON, no other text:\n"
    '{"action": "left_click|type|key|scroll|wait|done",\n'
    ' "coordinate": [x, y],            // for left_click/scroll\n'
    ' "text": "text to type",          // for type\n'
    ' "keys": "ctrl+s",                // for key (e.g. enter, ctrl+a)\n'
    ' "scroll_direction": "up|down",   // for scroll\n'
    ' "target": "what you are acting on, described",\n'
    ' "reason": "why, in one short clause",\n'
    ' "consequential": true|false,     // true if this SENDS, DELETES, BUYS, '
    'POSTS, INSTALLS, or OVERWRITES anything\n'
    ' "summary": "..."                 // ONLY for action=done: what you '
    "accomplished}\n\n"
    "Use action=done when the task is complete. Be honest about "
    "'consequential' -- when unsure, mark it true."
)


def propose_prompt(task: str, history: list[str]) -> str:
    """The per-step instruction: the goal plus what she's done so far."""
    done = "\n".join(f"- {h}" for h in history[-8:]) or "- (nothing yet)"
    return (f"Task: {task}\n\nWhat you've done so far:\n{done}\n\n"
            "Look at the screenshot and choose the single next action.")


# --- Screen + execution (guarded; absent hardware degrades to unavailable) ---

def available() -> bool:
    """Opt-in flag set, and pyautogui importable. Vision availability is
    checked at run time by the driver."""
    if not ComputerCfg.ENABLED:
        return False
    try:
        import pyautogui  # noqa: F401
        return True
    except Exception:
        return False


def _capture():
    """Native-resolution screenshot as a PIL Image, plus (w, h)."""
    try:
        import mss
        from PIL import Image
        with mss.mss() as sct:
            mon = sct.monitors[1]
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            return img, img.width, img.height
    except Exception:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        return img.convert("RGB"), img.width, img.height


def screenshot_for_model() -> tuple[Optional[bytes], float]:
    """Capture, downscale to the view long-edge, return (jpeg_bytes, scale).
    Scale is what her returned coordinates must be divided by."""
    import io
    img, w, h = _capture()
    scale = scale_factor(w, h, ComputerCfg.VIEW_LONG_EDGE)
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue(), scale


def execute(action: Action, scale: float) -> str:
    """Carry out one (already-approved) action via pyautogui. Returns a short
    result line for the loop's history. Coordinates are scaled back up from the
    model's view space to real screen pixels."""
    import pyautogui
    pyautogui.FAILSAFE = True   # slam the mouse to a corner to abort
    try:
        if action.kind == "left_click" and action.coordinate:
            x, y = action.coordinate[0] / scale, action.coordinate[1] / scale
            pyautogui.click(x, y)
            return f"clicked {action.target or f'({int(x)},{int(y)})'}"
        if action.kind == "type":
            pyautogui.typewrite(action.text, interval=0.02)
            return f"typed: {action.text[:60]}"
        if action.kind == "key":
            pyautogui.hotkey(*[k.strip() for k in action.keys.replace("+", " ").split()])
            return f"pressed {action.keys}"
        if action.kind == "scroll":
            amt = action.scroll_amount * (1 if action.scroll_direction == "up" else -1)
            pyautogui.scroll(amt * 100)
            return f"scrolled {action.scroll_direction}"
        if action.kind == "wait":
            import time
            time.sleep(1.0)
            return "waited"
        return f"unhandled action: {action.kind}"
    except Exception as exc:
        return f"action failed: {exc}"


# --- The driver: one task, start to finish ----------------------------------

@dataclass
class TaskResult:
    ok: bool
    summary: str = ""
    steps: list = field(default_factory=list)
    error: str = ""


def run_task(task: str,
             confirm: Callable[[Action], bool],
             status: Callable[[str], None],
             on_cursor: Optional[Callable[[float, float], None]] = None,
             max_steps: Optional[int] = None) -> TaskResult:
    """Drive the computer toward `task`. `confirm(action) -> bool` is called
    for every consequential action and must return the person's decision;
    `status(msg)` reports progress. Returns when she signals done, hits the
    step cap, or a consequential action is denied.

    Needs both pyautogui (available()) and her vision model. Absent either, it
    returns a clean failure rather than doing anything."""
    if not available():
        return TaskResult(False, error="computer use is off (ALPECCA_COMPUTER_USE=1)")
    from alpecca import vision  # local import: heavy, optional

    steps_cap = max_steps or ComputerCfg.MAX_STEPS
    history: list[str] = []
    try:
        import ollama
        client = ollama.Client(host=OLLAMA_HOST)
    except Exception:
        return TaskResult(False, error="vision model client unavailable")

    for _ in range(steps_cap):
        shot, scale = screenshot_for_model()
        if shot is None:
            return TaskResult(False, summary="", steps=history, error="couldn't capture the screen")
        try:
            resp = client.chat(
                model=VisionCfg.MODEL,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user",
                           "content": propose_prompt(task, history),
                           "images": [shot]}],
            )
            action = parse_action(resp["message"]["content"])
        except Exception as exc:
            return TaskResult(False, steps=history, error=f"vision step failed: {exc}")

        if action is None:
            status("(she couldn't decide a next step and stopped)")
            return TaskResult(False, steps=history, error="no parseable action")

        if action.kind == "done":
            status(f"done: {action.done_summary}")
            return TaskResult(True, summary=action.done_summary, steps=history)

        if is_consequential(action):
            status(f"asking before: {action.target or action.kind} -- {action.reason}")
            if not confirm(action):
                return TaskResult(False, summary="stopped: you declined a step",
                                  steps=history)

        status(f"{action.kind}: {action.target or action.text or action.keys}")
        # Let the UI move her on-screen cursor marker to where she's acting, so
        # her exploration is visible (a fraction of the screen, 0..1).
        if on_cursor and action.coordinate:
            try:
                import pyautogui
                sw, sh = pyautogui.size()
                on_cursor((action.coordinate[0] / scale) / sw,
                          (action.coordinate[1] / scale) / sh)
            except Exception:
                pass
        result = execute(action, scale)
        history.append(result)

    return TaskResult(False, summary="reached the step limit", steps=history)
