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
from typing import Optional

from config import OpenClaw as OpenClawCfg


def _resolve_target(reply_target: str) -> Optional[str]:
    """Pick the delivery target, preferring the per-message hint over the
    config default. Empty / unset means we shouldn't try to deliver."""
    target = reply_target.strip() or OpenClawCfg.DEFAULT_TARGET.strip()
    return target or None


def try_deliver(text: str, reply_target: str = "") -> dict:
    """Best-effort outbound delivery via the OpenClaw CLI.

    Returns a small status dict the caller can surface in its response. We
    swallow every error class -- OpenClaw not installed, target malformed,
    network blip -- because the inbound message has already been answered in
    Alpecca's HTTP response; this is just the bonus delivery leg.
    """
    if not OpenClawCfg.ENABLED:
        return {"attempted": False, "reason": "openclaw bridge disabled"}
    if not text:
        return {"attempted": False, "reason": "empty reply"}
    target = _resolve_target(reply_target)
    if not target:
        return {"attempted": False, "reason": "no delivery target"}

    argv = [OpenClawCfg.EXEC, "message", "send",
            "--target", target, "--message", text]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return {"attempted": True, "ok": False, "reason": "openclaw not on PATH"}
    except subprocess.TimeoutExpired:
        return {"attempted": True, "ok": False, "reason": "openclaw timed out"}
    except Exception as exc:                  # pragma: no cover -- belt-and-braces
        return {"attempted": True, "ok": False, "reason": str(exc)}

    if proc.returncode != 0:
        return {"attempted": True, "ok": False,
                "reason": f"exit {proc.returncode}",
                "stderr": proc.stderr.strip()[:200]}
    return {"attempted": True, "ok": True, "target": target}
