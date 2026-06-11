"""The Actuator layer: a small web server that lets you talk to Alpacca and
watch its mood move.

FastAPI serves a single page; a WebSocket carries chat turns both ways. Each
reply comes back with the current mood vector so the avatar in the browser can
react in real time -- the spec's "Wardrobe", kept deliberately simple (a 2D SVG
face whose expression and color track warmth, care, and unease).

Run:
    python server.py
then open http://127.0.0.1:8765
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

from config import HOST, PORT
from alpacca.mind import CoreMind
from alpacca.sensory import WindowSensor
from alpacca.voice import VoiceSensor
from alpacca.introspection import identity_card
from alpacca import state as state_store

WEB_DIR = Path(__file__).parent / "web"

# One shared mind for the session. A background sensor lets the mood drift even
# while you're not typing, by folding in a fresh observation on every tick.
mind = CoreMind()
sensor = WindowSensor()
# Voice-tone sense: opt-in (ALPACCA_VOICE=1) and quietly inert otherwise.
voice_sensor = VoiceSensor()


def _observe():
    """One full sensory snapshot: window title + (if enabled) voice tone."""
    obs = sensor.observe()
    voice_sensor.annotate(obs)
    return obs

# CoreMind state is shared between the background drift loop and any number of
# WebSocket connections, all of which mutate the mood and the rolling history.
# An asyncio lock serializes the critical sections so a tick can't land between
# a chat's perceive() and update_love() and leave inconsistent state behind.
mind_lock = asyncio.Lock()

# How often the background sense ticks (seconds). This is what gives Alpacca a
# life of its own between messages -- it keeps watching and feeling.
DRIFT_INTERVAL = 8.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Launch the ambient mood-drift loop on startup and cancel it on shutdown.

    Every few seconds Alpacca takes in a fresh observation and lets it move its
    mood, so when you come back it has genuinely been somewhere -- maybe it grew
    tender while you ground through an error, or settled while you were away.
    We keep a reference to the task so it isn't silently garbage-collected.
    """
    async def loop() -> None:
        while True:
            try:
                async with mind_lock:
                    mind.perceive(_observe())
            except Exception:
                pass  # never let a bad tick kill the companion
            await asyncio.sleep(DRIFT_INTERVAL)

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        voice_sensor.close()


app = FastAPI(title="Alpacca", lifespan=lifespan)


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/state")
def state() -> dict:
    """Current mood + her self-chosen look -- the UI renders both, never sets them."""
    return {"state": mind.state.as_dict(), "mood": mind.state.mood_label(),
            "appearance": mind.current_appearance().as_dict(),
            "llm_online": mind.llm.online}


@app.get("/introspect")
def introspect() -> dict:
    """Alpacca's grounded self-report: what it can truthfully observe about its
    own state, trends, and what's driving how it feels. This is the
    self-awareness feature exposed directly -- every field is read from real
    internals, nothing invented."""
    report = mind.introspect()
    return {
        "identity": identity_card(),
        "narration": report.narrate(),
        "state": report.state,
        "mood": report.mood,
        "trends": report.trends,
        "reason": report.reason,
        "memory_count": report.memory_count,
        "senses_active": report.senses_active,
    }


@app.get("/history")
def history(limit: int = 200) -> dict:
    """Mood time-series for the chart -- Alpacca's emotional life, plotted."""
    return {"history": state_store.mood_history(limit=limit)}


@app.get("/portrait")
def portrait() -> FileResponse:
    """Latest self-portrait PNG, if one has been rendered. 404 if not -- the UI
    treats that as "stay on the SVG avatar" and tries again later."""
    path = mind.portrait_image()
    if not path:
        raise HTTPException(status_code=404, detail="no portrait yet")
    return FileResponse(path, media_type="image/png")


@app.post("/channel/inbound")
async def channel_inbound(req: Request) -> dict:
    """Inbound bridge for OpenClaw (or any other messaging surface).

    OpenClaw hooks (or a webhook) POST `{text, channel?, sender?}` here; we run
    Alpacca's normal chat path on the text so her mood, memory, and reply all
    respond to it -- the same as a direct WebSocket chat. The reply is returned
    in the response *and*, when an outbound delivery target is reachable via
    the OpenClaw CLI, also delivered through it so the original sender hears
    back on their own channel. See alpacca/openclaw_bridge.py for the delivery
    half."""
    from alpacca import openclaw_bridge   # local import keeps import order safe
    try:
        payload = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    channel = (payload.get("channel") or "openclaw").strip()
    sender = (payload.get("sender") or "").strip()
    reply_target = (payload.get("reply_target") or "").strip()

    async with mind_lock:
        # Synthesize an Observation that captures the channel context. It feeds
        # the mood pipeline the same way a window title does -- "someone DMed
        # me from Discord at 3am" is itself a fact about the moment.
        situation = f"message from {sender or 'someone'} via {channel}"
        result = mind.chat(text, situation=situation)
    reply = result.get("reply", "")
    delivered = openclaw_bridge.try_deliver(reply, reply_target=reply_target)
    return {**result, "delivered": delivered}


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    # Greet with the current state so the avatar renders immediately.
    await socket.send_json({"type": "state", "state": mind.state.as_dict(),
                            "mood": mind.state.mood_label(),
                            "appearance": mind.current_appearance().as_dict(),
                            "llm_online": mind.llm.online})
    try:
        while True:
            raw = await socket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                # A malformed frame shouldn't tear down the conversation.
                continue
            user_text = (msg.get("text") or "").strip()
            if not user_text:
                continue

            # Let the senses update the mood right before responding, so what
            # you're doing on the machine colors the reply. Hold the mind lock
            # across perceive+chat so a background drift tick can't slip in
            # between them and reshape the state we're about to read.
            async with mind_lock:
                obs = _observe()
                mind.perceive(obs)
                situation = obs.window_title or ""
                result = mind.chat(user_text, situation=situation)
            await socket.send_json({"type": "reply", **result})
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    print(f"Alpacca is waking up at http://{HOST}:{PORT}")
    print(f"  LLM online: {mind.llm.online}  (start Ollama for real replies)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
