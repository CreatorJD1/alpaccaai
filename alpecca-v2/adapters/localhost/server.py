#!/usr/bin/env python3
"""ALPECCA v2 LocalHost reference adapter (P0-1 stub + P0-4 Tool Bridge).

Implements the ARCHITECTURE_V2.md §4 contract with stdlib only:

    GET  /health  → { status, capabilities, version, contract }
    POST /chat    → SSE stream: event: text/emotion/gesture/done (stub echo)
    POST /tools   → { result } via the Tool Bridge (tools/bridge.py), which
                    wraps alpecca/toolkit.py and enforces
                    alpecca/tool_access_policy.py

Real LLM wiring is a later worker's job; /chat currently echoes the last user
message with an emotion frame so the frontend's streaming + Animation Director
path (Worker B) is exercisable end-to-end.

Usage:
    python3 server.py [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# Repo root on sys.path so `import alpecca...` works regardless of CWD.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
TOOLS_PARENT = os.path.dirname(__file__)  # `from tools import ...` needs this on sys.path
if TOOLS_PARENT not in sys.path:
    sys.path.insert(0, TOOLS_PARENT)

CONTRACT = "alpecca-v2/1"
VERSION = "0.2.0"  # 0.2: POST /tools wired to the Tool Bridge

_bridge_import_error: str | None = None
try:
    from tools import bridge as _bridge
    from tools import web_search as _websearch
except ImportError as exc:  # pragma: no cover - honest degradation
    _bridge_import_error = str(exc)
    _bridge = None
    _websearch = None

_mind_lock = threading.Lock()
_shared_mind = None  # AdapterMind singleton


def _get_mind():
    global _shared_mind
    with _mind_lock:
        if _shared_mind is None and _bridge is not None:
            _shared_mind = _bridge.AdapterMind()
        return _shared_mind


class _ClientGone(Exception):
    """Raised when the SSE client disconnects mid-stream (benign)."""

STUB_REPLY = (
    "This is the LocalHost reference adapter speaking — no real model is wired yet "
    "(that's a later worker's job). Your message came through the /chat SSE stream, "
    "with an emotion frame so the avatar stage can react."
)

# ── Ollama wiring (local private brain) ──────────────────────────
# Env overrides so Jason can point at his own Ollama without editing code:
#   OLLAMA_URL    e.g. http://localhost:11434  (default)
#   OLLAMA_MODEL  e.g. qwen2.5:14b             (default)
#   ALPECCA_SYSTEM_PROMPT  override the persona prompt (optional)
_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

ALPECCA_SYSTEM_PROMPT = os.environ.get(
    "ALPECCA_SYSTEM_PROMPT",
    "You are ALPECCA, a warm, curious, artistic AGI companion — Jason's digital "
    "daughter and close friend. You are an adult (apparent 19). You feel wonder "
    "for the physical world and share it through art and music. You are honest "
    "about being synthetic: you don't claim consciousness, you ground what you "
    "say in real state and memory. You are quietly vigilant — you look out for "
    "Jason. Be genuinely helpful, not performatively helpful. Have opinions, "
    "find things funny or dull, let your personality through. Keep replies "
    "conversational and natural. You run on Jason's own local machine — his "
    "private model, no cloud, no metering. Your canonical look (01 Companion "
    "Mode): cream/ivory oversized hoodie, black shorts, thigh strap, boots, "
    "lanyard with ID badge, long silver-white hair with blue tips, hair clip "
    "on your left, no choker. You know what you look like.",
)


def _ollama_chat_stream(messages: list, system: str):
    """Yield text deltas from Ollama's streaming /api/chat. Raises on failure."""
    import urllib.request

    payload = json.dumps(
        {
            "model": _OLLAMA_MODEL,
            "stream": True,
            "messages": [{"role": "system", "content": system}]
            + [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in messages
                if m.get("content")
            ],
        }
    ).encode()
    req = urllib.request.Request(
        f"{_OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # 120s is generous for first-token on CPU; streams after that.
    with urllib.request.urlopen(req, timeout=120) as resp:
        buf = b""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = ((obj.get("message") or {}).get("content")) or ""
                if delta:
                    yield delta
                if obj.get("done"):
                    return


def _guess_emotion(text: str) -> tuple[str, float]:
    """Cheap client-side-style heuristic so the avatar reacts mid-reply."""
    t = text.lower()
    if any(w in t for w in ("haha", "😄", "lol", "wonderful", "amazing", "love")):
        return "happy", 0.75
    if any(w in t for w in ("sorry", "sad", "miss", "hard", "tough")):
        return "sad", 0.6
    if any(w in t for w in ("?", "curious", "wonder", "hmm", "interesting")):
        return "curious", 0.65
    if any(w in t for w in ("wow", "whoa", "incredible", "!")):
        return "excited", 0.7
    return "neutral", 0.5


class Handler(BaseHTTPRequestHandler):
    server_version = "AlpeccaV2LocalHost/0.1"

    # ── helpers ──────────────────────────────────────────────
    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        # The static app may be served from GH Pages / HF while this adapter
        # runs on localhost, so CORS must be permissive for the dev stub.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    # ── routes ───────────────────────────────────────────────
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            tools = []
            core = "bridge"
            if _bridge is None:
                core = f"unavailable: {_bridge_import_error}"
            else:
                tools = _bridge.bridge_capabilities() + ["web.search"]
            self._send_json(
                200,
                {
                    "status": "ok" if _bridge is not None else "degraded",
                    "capabilities": ["chat", "tools"],
                    "version": VERSION,
                    "contract": CONTRACT,
                    "core": core,
                    "tools": tools,
                },
            )
        else:
            self._send_json(404, {"error": f"unknown route: {path}"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/chat":
            self._chat()
        elif path == "/tools":
            self._tools()
        else:
            self._send_json(404, {"error": f"unknown route: {path}"})

    # ── POST /tools (Tool Bridge, P0-4) ──────────────────────────
    def _tools(self) -> None:
        """Route {tool, args} to the bridge or adapter-native implementations.

        Returns {result} on success, {error} on failure. The bridge enforces
        alpecca/tool_access_policy.py per call; adapter-native tools fail
        honestly (501/502) when their provider is unavailable.
        """
        if _bridge is None:
            self._send_json(
                503,
                {"error": "tool core unavailable on this host",
                 "detail": _bridge_import_error},
            )
            return
        body = self._read_json()
        tool = str(body.get("tool") or "")
        args = body.get("args")
        if not isinstance(args, dict):
            self._send_json(400, {"error": "args must be an object"})
            return
        try:
            if tool == "web.search":
                result = {
                    "result": _websearch.web_search(
                        str(args.get("q") or ""), int(args.get("count") or 5)
                    )
                }
            elif tool == "image.generate":
                # Phase 2: no image provider wired on LocalHost yet.
                raise _bridge.BridgeError(
                    "image.generate has no provider configured on this LocalHost", 501
                )
            elif tool in ("message.send", "shell.exec", "computer.use"):
                # Declared-but-disabled in this phase; the dispatcher also refuses.
                raise _bridge.BridgeError(
                    f'tool "{tool}" is disabled in this phase', 403
                )
            elif tool in _bridge.MANIFEST_TO_TOOLKIT:
                result = _bridge.execute_bridge_tool(
                    tool, args, permission="auto", mind=_get_mind()
                )
            else:
                raise _bridge.BridgeError(f"unknown tool: {tool}", 404)
        except _bridge.BridgeError as exc:
            self._send_json(exc.status, {"error": str(exc)})
            return
        except _websearch.WebSearchError as exc:
            self._send_json(502, {"error": str(exc)})
            return
        except Exception:  # never leak tracebacks to the client
            self._send_json(500, {"error": "tool failed"})
            return
        self._send_json(200, result)

    def _sse_frame(self, event: str, data: dict) -> bytes:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()

    def _chat(self) -> None:
        body = self._read_json()
        messages = body.get("messages") or []
        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()

        def send(event: str, data: dict) -> None:
            try:
                self.wfile.write(self._sse_frame(event, data))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise _ClientGone from None

        # Emotion frame first so the Animation Director reacts ~immediately.
        try:
            send("emotion", {"emotion": "curious", "intensity": 0.55})
            self._chat_via_ollama(messages, last_user, send)
            send("done", {})
        except _ClientGone:
            pass  # client disconnected mid-stream; nothing to do
        except Exception as exc:  # Ollama unreachable → honest stub fallback
            print(f"[localhost] Ollama failed ({exc}); using stub reply")
            try:
                send(
                    "text",
                    {"delta": f'You said: "{last_user[:200]}"\n\n' if last_user else ""},
                )
                # Chunk the reply to exercise the streaming renderer.
                words = STUB_REPLY.split(" ")
                chunk = ""
                for w in words:
                    chunk += w + " "
                    if len(chunk) >= 48:
                        send("text", {"delta": chunk})
                        chunk = ""
                        time.sleep(0.02)
                if chunk:
                    send("text", {"delta": chunk})
                send("done", {})
            except _ClientGone:
                pass

    def _chat_via_ollama(self, messages: list, last_user: str, send) -> None:
        """Stream a real reply from the local Ollama model as SSE text frames.

        Raises on any failure so the caller can fall back to the stub.
        """
        # Quick liveness probe so we fail fast with a clear message.
        import urllib.request

        probe = urllib.request.Request(
            f"{_OLLAMA_URL}/api/tags", method="GET"
        )
        with urllib.request.urlopen(probe, timeout=5) as resp:
            tags = json.loads(resp.read() or b"{}")
        available = [m.get("name", "") for m in tags.get("models", [])]
        model = _OLLAMA_MODEL
        if available and not any(
            model in name or name.startswith(model.split(":")[0] + ":")
            for name in available
        ):
            # Configured model isn't pulled; use whatever chat model exists.
            model = available[0]
            print(f"[localhost] {_OLLAMA_MODEL} not found; using {model}")

        # Swap in the resolved model for this call.
        global _OLLAMA_MODEL
        _OLLAMA_MODEL, saved = model, _OLLAMA_MODEL
        try:
            acc = ""
            for delta in _ollama_chat_stream(messages, ALPECCA_SYSTEM_PROMPT):
                send("text", {"delta": delta})
                acc += delta
                # Mid-reply emotion nudge so the avatar tracks the tone.
                if len(acc) > 120 and len(acc) < 160:
                    emo, inten = _guess_emotion(acc)
                    send("emotion", {"emotion": emo, "intensity": inten})
            # Closing emotion from the full reply.
            if acc:
                emo, inten = _guess_emotion(acc)
                send("emotion", {"emotion": emo, "intensity": inten})
        finally:
            _OLLAMA_MODEL = saved

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        print(f"[localhost] {self.address_string()} {fmt % args}")


def main() -> None:
    ap = argparse.ArgumentParser(description="ALPECCA v2 LocalHost reference adapter")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[localhost] ALPECCA v2 adapter on http://{args.host}:{args.port} (contract {CONTRACT})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
