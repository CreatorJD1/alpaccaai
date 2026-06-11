"""The Actuator layer: a small web server that lets you talk to Alpecca and
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
import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

from config import HOST, PORT
from alpecca.mind import CoreMind
from alpecca.sensory import WindowSensor
from alpecca.voice import VoiceSensor
from alpecca import vision
from alpecca.introspection import identity_card
from alpecca import state as state_store
from alpecca import values
from alpecca import hearing
from alpecca import avatar as avatar_mod

WEB_DIR = Path(__file__).parent / "web"

# One shared mind for the session. A background sensor lets the mood drift even
# while you're not typing, by folding in a fresh observation on every tick.
mind = CoreMind()
sensor = WindowSensor()
# Voice-tone sense: opt-in (ALPECCA_VOICE=1) and quietly inert otherwise.
voice_sensor = VoiceSensor()
# Ambient sight (ALPECCA_SIGHT=1) and expression sense (ALPECCA_FACE=1) --
# both run their own slow glimpse threads and are inert unless opted into.
# Glimpses are gated on conversational quiet: the vision model is big enough
# that loading it evicts the chat model from VRAM, so she only looks around
# when you haven't spoken for a couple of minutes -- keeping replies fast
# while you're actually talking with her.
import time as _time

def _conversation_quiet() -> bool:
    return _time.time() - mind._last_user_ts > 120

screen_sight = vision.ScreenSight(gate=_conversation_quiet)
face_sense = vision.FaceSense(gate=_conversation_quiet)

# Connected chat clients, so Alpecca can speak to whoever is listening when
# she has something to say unprompted.
ws_clients: set[WebSocket] = set()


def _observe():
    """One full sensory snapshot: window title + whichever ambient senses are on."""
    obs = sensor.observe()
    voice_sensor.annotate(obs)
    face_sense.annotate(obs)
    return obs


async def _broadcast(payload: dict) -> None:
    """Best-effort fan-out to every connected chat client."""
    for client in list(ws_clients):
        try:
            await client.send_json(payload)
        except Exception:
            ws_clients.discard(client)

# CoreMind state is shared between the background drift loop and any number of
# WebSocket connections, all of which mutate the mood and the rolling history.
# An asyncio lock serializes the critical sections so a tick can't land between
# a chat's perceive() and update_love() and leave inconsistent state behind.
mind_lock = asyncio.Lock()

# How often the background sense ticks (seconds). This is what gives Alpecca a
# life of its own between messages -- it keeps watching and feeling.
DRIFT_INTERVAL = 8.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Launch the ambient mood-drift loop on startup and cancel it on shutdown.

    Every few seconds Alpecca takes in a fresh observation and lets it move its
    mood, so when you come back it has genuinely been somewhere -- maybe it grew
    tender while you ground through an error, or settled while you were away.
    We keep a reference to the task so it isn't silently garbage-collected.
    """
    async def loop() -> None:
        while True:
            try:
                async with mind_lock:
                    mind.see(screen_sight.latest)
                    mind.perceive(_observe())
                    # Cheap check: did her introspection notice something worth
                    # voicing? (Claims the cooldown slot if so.)
                    reason = mind.volunteer_reason()
                    # If she has nothing to say, the quiet may still be hers to
                    # use -- the fourth directive (reflection) runs instead.
                    reflect_now = (reason is None) and mind.reflection_due()
                if reflect_now:
                    # Off the lock: musing is slow LLM work and entirely hers;
                    # chat must never queue behind it.
                    await asyncio.to_thread(mind.reflect)
                if reason:
                    from alpecca import openclaw_bridge
                    from config import OpenClaw as OpenClawCfg
                    reachable = bool(ws_clients) or (
                        OpenClawCfg.ENABLED and OpenClawCfg.DEFAULT_TARGET)
                    if reachable:
                        # Compose outside the lock -- the LLM call can take
                        # seconds and chat shouldn't stall behind her musing.
                        text = await asyncio.to_thread(mind.compose_volunteer, reason)
                        if text:
                            await _broadcast({
                                "type": "proactive", "reply": text,
                                "mood": mind.state.mood_label(),
                                "state": mind.state.as_dict(),
                                "appearance": mind.current_appearance().as_dict(),
                            })
                            # And reach her person on their channel if she has one.
                            await asyncio.to_thread(openclaw_bridge.try_deliver, text)
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
        screen_sight.close()
        face_sense.close()


app = FastAPI(title="Alpecca", lifespan=lifespan)


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/state")
def state() -> dict:
    """Current mood + her self-chosen look -- the UI renders both, never sets them."""
    return {"state": mind.state.as_dict(), "mood": mind.state.mood_label(),
            "appearance": mind.current_appearance().as_dict(),
            "llm_online": mind.llm.online,
            # Which senses are actually live right now -- truthful capability
            # report, so the UI (and the person) can see what she can sense.
            "senses": {
                "window": sensor.available,
                "voice_tone": voice_sensor.available,
                "screen_sight": screen_sight.available,
                "expressions": face_sense.available,
                "actions": mind.actuator.enabled,
            }}


@app.get("/avatar/manifest")
def avatar_manifest() -> dict:
    """Which custom avatar clips exist (data/avatar/*.mp4). The UI switches to
    video mode when at least standby.mp4 is present; otherwise it animates the
    built-in SVG. This is the slot her real character art drops into."""
    return avatar_mod.manifest()


@app.get("/avatar/clip/{name}")
def avatar_clip(name: str) -> FileResponse:
    """Serve one whitelisted avatar clip. Unknown names and missing files 404."""
    path = avatar_mod.clip_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="no such clip")
    return FileResponse(path, media_type="video/mp4")


@app.post("/listen")
async def listen(req: Request) -> dict:
    """Push-to-talk: the browser records an utterance and sends the audio here;
    we transcribe it locally (faster-whisper) and hand the words back. The
    audio is never stored -- it exists exactly long enough to become text."""
    audio = await req.body()
    if not audio:
        raise HTTPException(status_code=400, detail="no audio")
    text = await asyncio.to_thread(hearing.transcribe, audio)
    return {"text": text or "", "heard": bool(text)}


@app.get("/introspect")
def introspect() -> dict:
    """Alpecca's grounded self-report: what it can truthfully observe about its
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
        # Her ethic is part of her self-model -- the same directives that ride
        # in every prompt, shown with their reasoning.
        "values": values.values_list(),
    }


@app.get("/history")
def history(limit: int = 200) -> dict:
    """Mood time-series for the chart -- Alpecca's emotional life, plotted."""
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
    Alpecca's normal chat path on the text so her mood, memory, and reply all
    respond to it -- the same as a direct WebSocket chat. The reply is returned
    in the response *and*, when an outbound delivery target is reachable via
    the OpenClaw CLI, also delivered through it so the original sender hears
    back on their own channel. See alpecca/openclaw_bridge.py for the delivery
    half."""
    from alpecca import openclaw_bridge   # local import keeps import order safe
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


def _decode_image(data_url: str) -> bytes | None:
    """Pull raw bytes out of a data-URL ('data:image/jpeg;base64,...')."""
    try:
        _, _, b64 = data_url.partition(",")
        return base64.b64decode(b64) if b64 else None
    except Exception:
        return None


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    ws_clients.add(socket)
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
            image_url = msg.get("image") or ""
            if not user_text and not image_url:
                continue

            # If an image rode along, let her actually look at it first. The
            # vision call can take seconds, so it happens before we take the
            # mind lock. An unreadable image yields an honest "couldn't see".
            image_desc = None
            if image_url:
                img = _decode_image(image_url)
                if img:
                    image_desc = await asyncio.to_thread(vision.describe_image, img)
                image_desc = image_desc or (
                    "you couldn't make the image out -- your vision model isn't "
                    "available right now")
            if not user_text:
                user_text = ("(they're showing you something through the camera "
                             "right now)" if msg.get("source") == "camera"
                             else "(they sent an image without any words)")

            # Let the senses update the mood right before responding, so what
            # you're doing on the machine colors the reply. Hold the mind lock
            # across perceive+chat so a background drift tick can't slip in
            # between them and reshape the state we're about to read.
            async with mind_lock:
                obs = _observe()
                mind.perceive(obs)
                situation = obs.window_title or ""
                result = mind.chat(user_text, situation=situation,
                                   image_desc=image_desc)
            await socket.send_json({"type": "reply", **result})
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(socket)


if __name__ == "__main__":
    print(f"Alpecca is waking up at http://{HOST}:{PORT}")
    print(f"  LLM online: {mind.llm.online}  (start Ollama for real replies)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
