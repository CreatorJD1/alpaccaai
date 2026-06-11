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
from alpecca import computer as computer_mod

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


@app.get("/studio")
def studio_page() -> HTMLResponse:
    """Her studio -- a window into where she designs and rigs her character.
    Read-only: you watch and can ask her to work, but never edit her design."""
    return HTMLResponse((WEB_DIR / "studio.html").read_text(encoding="utf-8"))


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
                "computer_use": computer_mod.available(),
            }}


# Computer use runs one task at a time. The driver runs off-thread; when it
# hits a consequential action it blocks on _confirm_event while the UI is asked.
import threading as _threading
_computer_lock = _threading.Lock()
_confirm_event = _threading.Event()
_confirm_decision = {"approved": False}


@app.post("/computer/task")
async def computer_task(req: Request) -> dict:
    """Hand Alpecca a task she carries out by seeing the screen and working the
    mouse/keyboard locally. Consequential steps pause for your confirmation
    (delivered over the WebSocket; answered at /computer/confirm)."""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    task = (body.get("task") or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="task required")
    if not computer_mod.available():
        return {"ok": False, "error": "computer use is off (set ALPECCA_COMPUTER_USE=1)"}
    if not _computer_lock.acquire(blocking=False):
        return {"ok": False, "error": "she's already working on something on the computer"}

    loop = asyncio.get_running_loop()

    def status(msg: str) -> None:
        asyncio.run_coroutine_threadsafe(
            _broadcast({"type": "computer_status", "text": msg}), loop)

    def confirm(action) -> bool:
        _confirm_event.clear()
        _confirm_decision["approved"] = False
        asyncio.run_coroutine_threadsafe(_broadcast({
            "type": "computer_confirm",
            "target": action.target, "reason": action.reason,
            "kind": action.kind, "text": action.text,
        }), loop)
        # Block the worker thread until the person answers (or times out -> no).
        got = _confirm_event.wait(timeout=120)
        return bool(got and _confirm_decision["approved"])

    async def run() -> None:
        try:
            result = await asyncio.to_thread(computer_mod.run_task, task, confirm, status)
            await _broadcast({"type": "computer_done", "ok": result.ok,
                              "summary": result.summary, "error": result.error})
        finally:
            _computer_lock.release()

    asyncio.create_task(run())
    return {"ok": True, "started": True}


@app.post("/computer/confirm")
async def computer_confirm(req: Request) -> dict:
    """Answer a pending consequential-action confirmation."""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    _confirm_decision["approved"] = bool(body.get("approved"))
    _confirm_event.set()
    return {"ok": True}


@app.get("/character")
def character() -> dict:
    """Her self-authored character design: sheet, kept gallery, rig spec. All
    read-only -- this is HER studio; the user views, never edits."""
    from alpecca import studio
    from config import CHARACTER_DIR
    sheet = studio.load_sheet()
    spec = CHARACTER_DIR / "RIG_SPEC.md"
    return {
        "sheet": sheet,
        "gallery": studio.gallery_index(),
        "reference": studio.reference_sheets(),
        "rig_spec": spec.read_text(encoding="utf-8") if spec.exists() else None,
    }


@app.get("/puppet")
def puppet() -> dict:
    """Her puppet state for the avatar player: live grounded channel values
    (from her real mood) and the library of animations SHE authored. The UI
    renders this; it doesn't choreograph her."""
    return mind.puppet_state()


@app.get("/poses")
def poses() -> dict:
    """Her pose library: each real-art pose tagged with what it expresses, so
    the UI can show whichever pose fits her mood + what she's doing."""
    from alpecca import posekit
    return posekit.manifest()


@app.get("/poses/img/{name}")
def pose_image(name: str) -> FileResponse:
    """Serve one pose from her library (library names only -- no arbitrary
    file access)."""
    from alpecca import posekit
    path = posekit.pose_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="no such pose")
    return FileResponse(path, media_type="image/png")


@app.post("/poses/retag")
async def poses_retag() -> dict:
    """Have her vision model re-tag every pose -- she looks at each render and
    says what it expresses. This is the AI that connects her art to her state.
    Falls back to seeded tags for any pose vision can't read."""
    from alpecca import posekit
    lib = posekit.load_library()

    async def run() -> None:
        for name in list(lib):
            path = posekit.pose_path(name)
            if not path:
                continue
            tags = await asyncio.to_thread(posekit.tag_pose, path.read_bytes())
            if tags:
                lib[name] = tags
                posekit.save_library(lib)
                await _broadcast({"type": "pose_tagged", "name": name, "tags": tags})
        await _broadcast({"type": "poses_retagged", "count": len(lib)})

    asyncio.create_task(run())
    return {"ok": True, "started": True, "count": len(lib)}


@app.post("/puppet/author")
async def puppet_author(req: Request) -> dict:
    """Ask Alpecca to choreograph one of her own animations now, while you
    watch. Optional {name}; otherwise she takes the next from her wishlist.
    Steps stream as `studio_status`; result as `puppet_authored`."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = str(body.get("name", "")).strip()
    if not _studio_lock.acquire(blocking=False):
        return {"ok": False, "error": "she's already working in the studio"}
    loop = asyncio.get_running_loop()

    def status(msg: str) -> None:
        asyncio.run_coroutine_threadsafe(
            _broadcast({"type": "studio_status", "text": msg}), loop)

    async def run() -> None:
        try:
            async with mind_lock:
                seq = await asyncio.to_thread(mind.author_animation, name, status)
            await _broadcast({"type": "puppet_authored",
                              "sequence": seq, "ok": bool(seq)})
        finally:
            _studio_lock.release()

    asyncio.create_task(run())
    return {"ok": True, "started": True}


_studio_lock = _threading.Lock()


@app.post("/studio/work")
async def studio_work() -> dict:
    """Ask Alpecca to do a unit of design work right now, while you watch. Her
    steps stream over the WebSocket as `studio_status`; the final outcome as
    `studio_done`. This is her studio's only control -- it asks her to work, it
    never edits her design."""
    if not _studio_lock.acquire(blocking=False):
        return {"ok": False, "error": "she's already in the studio"}
    loop = asyncio.get_running_loop()

    def status(msg: str) -> None:
        asyncio.run_coroutine_threadsafe(
            _broadcast({"type": "studio_status", "text": msg}), loop)

    async def run() -> None:
        try:
            async with mind_lock:
                outcome = await asyncio.to_thread(mind.studio_session, status)
            await _broadcast({"type": "studio_done",
                              "outcome": outcome or "nothing came of it this time"})
        finally:
            _studio_lock.release()

    asyncio.create_task(run())
    return {"ok": True, "started": True}


@app.get("/character/reference/{name}")
def character_reference(name: str) -> FileResponse:
    """Serve one of her canonical master sheets from data/character/reference."""
    import re
    from config import CHARACTER_DIR
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.png", name):
        raise HTTPException(status_code=404, detail="no such sheet")
    path = CHARACTER_DIR / "reference" / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="no such sheet")
    return FileResponse(path, media_type="image/png")


@app.get("/character/image/{name}")
def character_image(name: str) -> FileResponse:
    """Serve one image from her gallery. Names are constrained to the pattern
    the studio writes, so nothing else is reachable."""
    import re
    from config import CHARACTER_DIR
    if not re.fullmatch(r"self-[0-9-]+\.(png|jpg)", name):
        raise HTTPException(status_code=404, detail="no such image")
    path = CHARACTER_DIR / "gallery" / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="no such image")
    return FileResponse(path)


@app.get("/web/{path:path}")
def web_asset(path: str) -> FileResponse:
    """Serve vendored front-end assets (PIXI etc.) from web/, traversal-safe.
    Vendoring keeps the avatar renderer working with no internet -- the
    local-first line: nothing she needs should depend on a CDN."""
    safe = (WEB_DIR / path).resolve()
    try:
        safe.relative_to(WEB_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    if not safe.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(safe)


@app.get("/live2d")
def live2d_page() -> HTMLResponse:
    """Full-window rigged Live2D avatar, driven live by her real state. Shows a
    'drop a model in' note until a compiled model exists in data/avatar/live2d/."""
    return HTMLResponse((WEB_DIR / "live2d.html").read_text(encoding="utf-8"))


@app.get("/spine/manifest")
def spine_manifest() -> dict:
    """Whether her Spine rig (StretchyStudio export) exists + its skeleton and
    animation names. The /live2d page's primary rigged tier."""
    from alpecca import spine
    return spine.manifest()


@app.get("/spine/asset/{name}")
def spine_asset(name: str) -> FileResponse:
    """Serve a Spine asset (skeleton json / atlas / png) from data/avatar/spine/,
    traversal-blocked. pixi-spine pulls the atlas + textures off the skeleton."""
    from alpecca import spine
    p = spine.asset_path(name)
    if p is None:
        raise HTTPException(status_code=404, detail="no such asset")
    return FileResponse(p)


@app.get("/spine/pose")
def spine_pose() -> dict:
    """Her current animation choice (base/talk/blink) for the Spine driver."""
    from alpecca import spine
    m = spine.manifest()
    speaking = False
    return spine.choose_animation(m["animations"], mind.state.mood_label(), speaking)


@app.get("/talkinghead/manifest")
def talkinghead_manifest() -> dict:
    """Is the Talking Head Anime process feeding fresh frames? The /live2d page
    polls this and makes her neural face the top tier while it's live."""
    from alpecca import talkinghead
    return talkinghead.manifest()


@app.get("/talkinghead/pose")
def talkinghead_pose() -> dict:
    """Her current mood mapped to THA3 expressive pose params -- the runner
    pulls this each frame and merges it with blink + lip-sync."""
    from alpecca import talkinghead
    return {"pose": talkinghead.pose_for_state(mind.state),
            "speaking": False, "mood": mind.state.mood_label()}


@app.post("/talkinghead/frame")
async def talkinghead_push(req: Request) -> dict:
    """The THA3 runner POSTs each generated frame (JPEG bytes) here; we keep the
    newest in memory for the UI. Never written to disk."""
    from alpecca import talkinghead
    data = await req.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty frame")
    n = talkinghead.set_frame(data)
    return {"ok": True, "n": n}


@app.get("/talkinghead/frame")
def talkinghead_frame():
    """The latest neural frame for the UI to display."""
    from fastapi import Response
    from alpecca import talkinghead
    data, n = talkinghead.get_frame()
    if data is None:
        raise HTTPException(status_code=404, detail="no frame yet")
    return Response(content=data, media_type="image/jpeg",
                    headers={"X-Frame-N": str(n), "Cache-Control": "no-store"})


@app.get("/rig/manifest")
def rig_manifest() -> dict:
    """Whether a layered rig exists (data/avatar/rig/) + its manifest. The
    /live2d page uses this as the top render tier: layered rig > mesh > note."""
    from alpecca import rig
    return rig.manifest()


@app.get("/rig/layer/{name}")
def rig_layer(name: str) -> FileResponse:
    """Serve one rig layer PNG, restricted to files listed in the manifest."""
    from alpecca import rig
    p = rig.layer_path(name)
    if p is None:
        raise HTTPException(status_code=404, detail="no such layer")
    return FileResponse(p, media_type="image/png")


@app.get("/live2d/manifest")
def live2d_manifest() -> dict:
    """Whether a rigged Live2D model is present, and the param map for it."""
    from alpecca import live2d
    return live2d.manifest()


@app.get("/live2d/params")
def live2d_params() -> dict:
    """Her current mood mapped onto Cubism parameters (the slow expressive ones).
    The renderer polls/streams this and adds blink/breath/lip-sync locally."""
    from alpecca import live2d
    return {"params": live2d.params_for_state(mind.state),
            "halo": live2d.HALO_STATE.get("idle"), "mood": mind.state.mood_label()}


@app.get("/live2d/model/{path:path}")
def live2d_model(path: str) -> FileResponse:
    """Serve a model asset (model3.json/moc3/textures/physics/motions) from
    data/avatar/live2d/, traversal-blocked."""
    from alpecca import live2d
    f = live2d.asset_path(path)
    if f is None:
        raise HTTPException(status_code=404, detail="no such asset")
    return FileResponse(f)


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


@app.get("/avatar/portrait/{name}")
def avatar_portrait(name: str) -> FileResponse:
    """Serve one whitelisted avatar portrait image (her real character art,
    one pose per state). Unknown names and missing files 404."""
    path = avatar_mod.portrait_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="no such portrait")
    return FileResponse(path, media_type="image/png")


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
