"""Bridge to OpenClaw -- Alpecca's reach beyond the local browser.

OpenClaw is a personal-assistant gateway that fronts a couple dozen messaging
channels (Telegram, Discord, iMessage, WhatsApp...). We integrate via the two
simplest surfaces it documents, deliberately avoiding its full Gateway WS
protocol (which would mean implementing device pairing, challenge signing, and
scope negotiation):

  - **Inbound**: an OpenClaw internal hook listens for `message:received` and
    POSTs `{text, channel, sender, reply_target}` to Alpecca's
    `POST /channel/inbound` endpoint. Alpecca runs her normal chat path and
    returns her reply. (See README for the hook handler template.)
  - **Outbound**: this module shells out to `openclaw message send` to deliver
    Alpecca's reply back through whatever channel the original message came in
    on. No protocol implementation, no auth tokens to manage -- if the CLI is
    on PATH and configured, it just works.

If OpenClaw isn't installed, every function here returns a benign falsy result
and the chat loop continues unaffected. The `/channel/inbound` endpoint still
works as a generic "anyone-can-POST-text-to-Alpecca" surface; it just doesn't
deliver replies anywhere outside the HTTP response body.
"""
from __future__ import annotations

import subprocess
import threading
from typing import Optional

from config import OpenClaw as OpenClawCfg

# A small, bounded outbound queue. When delivering her words to the person's
# channel fails transiently (CLI hiccup, a momentary network blip), we hold the
# message and retry it on the next flush rather than silently dropping it -- so a
# reply or a proactive check-in she meant for you actually arrives. Bounded so a
# long outage can't grow it without limit; a *fatal* failure (CLI not installed)
# is never queued, since retrying it would never succeed.
_QUEUE_MAX = 50
_QUEUE_MAX_ATTEMPTS = 5
_pending: list[dict] = []           # {text, target, attempts}
_qlock = threading.Lock()


def _resolve_target(reply_target: str) -> Optional[str]:
    """Pick the delivery target, preferring the per-message hint over the
    config default. Empty / unset means we shouldn't try to deliver."""
    target = reply_target.strip() or OpenClawCfg.DEFAULT_TARGET.strip()
    return target or None


def _send_once(text: str, target: str) -> dict:
    """One delivery attempt via the OpenClaw CLI. `fatal` marks failures that
    will never succeed on retry (CLI absent), so the queue can drop them."""
    argv = [OpenClawCfg.EXEC, "message", "send",
            "--target", target, "--message", text]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return {"ok": False, "fatal": True, "reason": "openclaw not on PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "fatal": False, "reason": "openclaw timed out"}
    except Exception as exc:                  # pragma: no cover -- belt-and-braces
        return {"ok": False, "fatal": False, "reason": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "fatal": False, "reason": f"exit {proc.returncode}",
                "stderr": proc.stderr.strip()[:200]}
    return {"ok": True, "target": target}


def _enqueue(text: str, target: str) -> None:
    with _qlock:
        if len(_pending) >= _QUEUE_MAX:
            _pending.pop(0)                   # drop the oldest -- bounded
        _pending.append({"text": text, "target": target, "attempts": 0})


def pending_count() -> int:
    """How many outbound messages are waiting to be retried (cheap; no I/O)."""
    with _qlock:
        return len(_pending)


def flush() -> dict:
    """Retry every queued outbound message. Call periodically (the server's idle
    loop does). Succeeded messages leave the queue; transient failures stay (up
    to a few attempts); fatal failures are dropped. Returns {sent, pending}."""
    if not OpenClawCfg.ENABLED:
        return {"sent": 0, "pending": 0}
    with _qlock:
        items = list(_pending)
        _pending.clear()
    sent, keep = 0, []
    for it in items:
        res = _send_once(it["text"], it["target"])
        if res.get("ok"):
            sent += 1
            continue
        it["attempts"] += 1
        if not res.get("fatal") and it["attempts"] < _QUEUE_MAX_ATTEMPTS:
            keep.append(it)
    if keep:
        with _qlock:
            _pending[:0] = keep               # put unsent back at the front, in order
    return {"sent": sent, "pending": len(keep)}


def try_deliver(text: str, reply_target: str = "") -> dict:
    """Best-effort outbound delivery via the OpenClaw CLI. On a transient failure
    the message is queued for retry (see `flush`); on a fatal one (CLI absent) or
    a config miss it's not. The inbound message has already been answered in
    Alpecca's HTTP response either way -- this is the bonus delivery leg."""
    if not OpenClawCfg.ENABLED:
        return {"attempted": False, "reason": "openclaw bridge disabled"}
    if not text:
        return {"attempted": False, "reason": "empty reply"}
    target = _resolve_target(reply_target)
    if not target:
        return {"attempted": False, "reason": "no delivery target"}
    res = _send_once(text, target)
    if res.get("ok"):
        return {"attempted": True, "ok": True, "target": target}
    queued = not res.get("fatal", False)
    if queued:
        _enqueue(text, target)                # hold it; flush() will retry
    return {"attempted": True, "ok": False, "reason": res.get("reason", ""),
            "queued": queued, **({"stderr": res["stderr"]} if "stderr" in res else {})}
