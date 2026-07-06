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

from config import HOST, PORT, DEEP_BACKEND
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
                    # She may wander to whichever room of her home is calling her
                    # strongest right now -- grounded movement, the same way her
                    # mood drifts. Cheap and pure, so it's fine under the lock.
                    roamed = mind.maybe_roam()
                    # Cheap check: did her introspection notice something worth
                    # voicing? (Claims the cooldown slot if so.)
                    reason = mind.volunteer_reason()
                    # If she has nothing to say, the quiet may still be hers to
                    # use -- her Soul decides what self-directed act to take.
                    reflect_now = (reason is None) and mind.reflection_due()
                if roamed:
                    # Let any open home view follow her from room to room, and
                    # show it in the activity ticker so her wandering is visible.
                    await _broadcast({"type": "roamed", "location": roamed,
                                      "home": mind.home_state()})
                    await _broadcast({"type": "activity",
                                      "text": f"she drifted into the {roamed}"})
                if reflect_now:
                    # Off the lock: her Soul drives one self-directed act (reflect,
                    # self-improve, or recursive self-question) -- slow, entirely
                    # hers, and chat must never queue behind it. Its note (if any)
                    # goes to the activity ticker so you can watch her stir.
                    res = await asyncio.to_thread(mind.idle_self_direct)
                    if res and res.get("note"):
                        await _broadcast({"type": "activity", "text": res["note"]})
                    # Now and then she entertains herself -- opens a game for fun,
                    # of her own accord (charter: supervised entertainment). Rare
                    # so she doesn't keep popping windows.
                    import random as _rnd
                    if _rnd.random() < 0.05:
                        played = await asyncio.to_thread(mind.entertain)
                        if played and played.get("note"):
                            await _broadcast({"type": "activity", "text": played["note"]})
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
                # Retry any outbound messages a transient channel hiccup dropped,
                # so her words actually reach the person. Cheap when the queue's
                # empty (no subprocess), and off-thread so chat never stalls.
                try:
                    from alpecca import openclaw_bridge as _ocb
                    if _ocb.pending_count():
                        await asyncio.to_thread(_ocb.flush)
                except Exception:
                    pass
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


# --- Remote-access auth ------------------------------------------------------
# When ALPECCA_ACCESS_TOKEN is set, every request must carry the token -- as a
# ?token= query, an X-Alpecca-Token header, or the alpecca_token cookie that a
# first ?token= visit drops. When it's blank (the default, private local use)
# there's no gate at all, so `python server.py` stays frictionless. We do NOT
# special-case localhost: the desktop window is handed the token by app.py, and
# tunnel traffic arrives FROM localhost too, so a localhost bypass would be a
# hole. WebSockets are guarded separately in the /ws handler (cookies ride the
# handshake, so the SPA needs no change).
from config import ACCESS_TOKEN as _TOKEN
from starlette.responses import JSONResponse as _JSON

_LOGIN_HTML = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Alpecca - access</title>
<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#070b14;color:#cfe0ff;font-family:system-ui,sans-serif">
<form onsubmit="location='/?token='+encodeURIComponent(document.getElementById('t').value);return false"
 style="background:rgba(8,14,26,.7);padding:28px 26px;border-radius:14px;border:1px solid #1d2a47;text-align:center;max-width:320px">
  <div style="font-size:20px;font-weight:650;margin-bottom:6px">Alpecca</div>
  <div style="color:#8aa0c6;font-size:13px;margin-bottom:16px">Enter your access token to reach her.</div>
  <input id=t autofocus placeholder="access token" style="width:100%;box-sizing:border-box;padding:10px;border-radius:9px;border:1px solid #24345a;background:#0e1830;color:#cfe0ff">
  <button style="margin-top:12px;width:100%;padding:10px;border:0;border-radius:9px;background:#7fd9ff;color:#06121c;font-weight:600;cursor:pointer">Enter</button>
</form></body>"""


def _token_ok(query, headers, cookies) -> bool:
    """Whether a request carries the right token. With no token configured the
    gate is open (private local use)."""
    if not _TOKEN:
        return True
    tok = (query.get("token") or headers.get("X-Alpecca-Token")
           or cookies.get("alpecca_token"))
    return tok == _TOKEN


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    if not _token_ok(request.query_params, request.headers, request.cookies):
        # A browser navigation gets a friendly token prompt; anything else 401s.
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return HTMLResponse(_LOGIN_HTML, status_code=401)
        return _JSON({"detail": "access token required"}, status_code=401)
    resp = await call_next(request)
    # A valid ?token= visit drops a cookie so later fetches + the WebSocket carry
    # it automatically, without the token living in every URL.
    tok = request.query_params.get("token")
    if _TOKEN and tok == _TOKEN:
        resp.set_cookie("alpecca_token", tok, max_age=60 * 60 * 24 * 30, samesite="lax")
    return resp


@app.get("/")
def index() -> HTMLResponse:
    """The super app: her living 3D home with integrated chat and every facet
    (Studio, Library, Journal, Mind, Workshop, Files) as panels over the existing
    endpoints -- one page, one socket. The classic chat UI stays at /classic."""
    return HTMLResponse((WEB_DIR / "home.html").read_text(encoding="utf-8"))


@app.get("/classic")
def classic() -> HTMLResponse:
    """The original full-featured chat page (voice push-to-talk, image attach,
    avatar state machine). Kept available while the super app folds these in."""
    return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/studio")
def studio_page() -> HTMLResponse:
    """Her studio -- a window into where she designs and rigs her character.
    Read-only: you watch and can ask her to work, but never edit her design."""
    return HTMLResponse((WEB_DIR / "studio.html").read_text(encoding="utf-8"))


@app.get("/home")
def home_page() -> HTMLResponse:
    """Her home -- the live 3D house of rooms she roams of her own accord. The
    page is a pure renderer; where she is comes from /home/state."""
    return HTMLResponse((WEB_DIR / "home.html").read_text(encoding="utf-8"))


@app.get("/home/state")
def home_state() -> dict:
    """Where she is in her home right now, why she's there, and how strongly each
    room is calling her -- all grounded in her live state (alpecca/home.py)."""
    return mind.home_state()


@app.get("/growth")
def growth() -> dict:
    """The Workshop's contents: the wants she's formed (desires.py) and the
    bounded, reversible changes she's made to herself (selfmod.py). Read-only and
    fully auditable -- nothing she's changed about herself is hidden."""
    return mind.desires_state()


@app.get("/soul")
def soul() -> dict:
    """Her Soul, live: the ranked slate of intentions from her seven subagents
    (emotions, actions, self-care, compassion) and the one in focus, arbitrated
    by the Good Person Principle (alpecca/soul.py). The single explainable answer
    to 'what is she moved to do right now, and why.'"""
    return mind.soul_state()


@app.get("/memories")
def memories() -> dict:
    """The Library's contents: the moments and musings she's keeping. Read-only."""
    from alpecca import memory as _mem
    return {"recent": _mem.recent(limit=40), "count": _mem.count()}


@app.get("/journal")
def journal() -> dict:
    """Her journal -- the notebook that is hers to write in, plus the open
    questions she's working through on her own (alpecca/journal.py). Read-only to
    the person; the writing is hers."""
    return mind.journal_state()


# --- Her rigger render tier (alpecca-rigger): full-body posed frames, CPU-only.
# A separate process (scripts/run_rigger.py) builds her rig from her decomposed
# art and pushes rendered frames here; the home shows them as a top avatar tier.
_rigger_frame: dict = {"bytes": None, "ts": 0.0, "n": 0}


@app.get("/rigger/pose")
def rigger_pose() -> dict:
    """Her current pose + expression names (from her live mood) for the rigger
    render process to draw."""
    return mind.rigger_pose()


@app.post("/rigger/frame")
async def rigger_frame_push(req: Request) -> dict:
    """The render process posts her latest rendered frame (JPEG) here."""
    data = await req.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty frame")
    _rigger_frame.update(bytes=data, ts=_time.time(), n=_rigger_frame["n"] + 1)
    return {"ok": True, "n": _rigger_frame["n"]}


@app.get("/rigger/frame")
def rigger_frame_get():
    """The latest rendered frame for the home to display."""
    from fastapi import Response
    if _rigger_frame["bytes"] is None:
        raise HTTPException(status_code=404, detail="no frame yet")
    return Response(content=_rigger_frame["bytes"], media_type="image/png",
                    headers={"X-Frame-N": str(_rigger_frame["n"]), "Cache-Control": "no-store"})


@app.get("/rigger/manifest")
def rigger_manifest() -> dict:
    """Whether her rigger figure is live (a fresh frame within the last ~6s)."""
    fresh = _rigger_frame["bytes"] is not None and (_time.time() - _rigger_frame["ts"]) < 6.0
    return {"rigger_mode": fresh, "n": _rigger_frame["n"]}


@app.get("/rigforge")
def rigforge_page() -> HTMLResponse:
    """The RIGFORGE runtime as her living avatar. With ?embed=1 it hides the
    editor chrome, auto-loads her portrait, and drives the rig from her live mood
    (and the WS speaking signal) -- a continuous-mesh figure animated from one
    image. The 3D home embeds this and textures it onto her."""
    return HTMLResponse((WEB_DIR / "rigforge.html").read_text(encoding="utf-8"))


@app.post("/rigforge/capture")
async def rigforge_capture(req: Request) -> dict:
    """Stage a certified RIGFORGE sample for her data loop. RIGFORGE posts
    {name, readiness, figure(dataURL png), pose(coco json), rig(rigforge json)}
    after its readiness check; we re-gate on readiness here and save the triplet
    under data/avatar/samples/{figures,pose,rigs}. build_manifest.py turns these
    into training data for her own joint detector (Path 3 -- selfmod for her body)."""
    from config import RigData
    import json as _json
    try:
        b = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    name = re.sub(r"[^a-z0-9_-]+", "_", (b.get("name") or "sample").lower()).strip("_") or "sample"
    readiness = float(b.get("readiness") or 0)
    if readiness < RigData.MIN_READINESS:
        return {"ok": False, "error": f"not certified (readiness {readiness:.0f} < {RigData.MIN_READINESS:.0f})"}
    base = RigData.SAMPLES_DIR
    for sub in ("figures", "pose", "rigs"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    fig = _decode_image(b.get("figure") or "")
    if fig:
        (base / "figures" / f"{name}.png").write_bytes(fig)
    if b.get("pose") is not None:
        (base / "pose" / f"{name}.rigpose.json").write_text(
            _json.dumps(b["pose"]), encoding="utf-8")
    if b.get("rig") is not None:
        (base / "rigs" / f"{name}.rig.json").write_text(
            _json.dumps(b["rig"]), encoding="utf-8")
    return {"ok": True, "name": name, "readiness": readiness,
            "staged": str(base), "next": "run scripts/build_manifest.py to assemble + push"}


@app.get("/avatar/rigpose")
def avatar_rigpose() -> FileResponse:
    """Her raw pose keypoints (COCO) for RIGFORGE's importPose. 404 when absent."""
    from config import AVATAR_DIR
    p = AVATAR_DIR / "rigpose.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no rigpose")
    return FileResponse(p, media_type="application/json")


_EXPRESSIONS = {"neutral", "warm_smile", "happy", "curious", "thinking", "concerned",
                "compassionate", "soft_sadness", "apologetic", "reassuring", "low_power",
                "protective", "fear_spike", "overload", "playful", "gentle"}


@app.get("/avatar/expression/{name}")
def avatar_expression(name: str) -> FileResponse:
    """One of her 16 drawn facial expressions (sliced from her expression sheet),
    for the live anime-face profile view. Whitelisted; unknown names 404."""
    from config import CHARACTER_DIR
    if name not in _EXPRESSIONS:
        raise HTTPException(status_code=404, detail="no such expression")
    p = CHARACTER_DIR / "expressions" / f"{name}.png"
    if not p.exists():
        raise HTTPException(status_code=404, detail="expression not generated")
    return FileResponse(p, media_type="image/png")


@app.get("/avatar/skeleton")
def avatar_skeleton() -> dict:
    """Her pose skeleton (data/avatar/rigpose.json) as a normalized set of joints
    and anchors -- what the avatar pivots its head-tilt and lean on, grounded in
    her real figure (alpecca/pose.py). `null` when no skeleton has been saved."""
    from alpecca import pose as _pose
    from config import AVATAR_DIR
    return {"skeleton": _pose.load(AVATAR_DIR / "rigpose.json")}


@app.get("/desktop")
def desktop() -> dict:
    """Her workstation: a desktop-like overview of the folders she's allowed to
    tidy (Desktop/Pictures/Music/Video/general), with what she can and can't do.
    Every operation is charter-guarded; she can never delete (alpecca/desktop.py)."""
    from alpecca import desktop as _desktop
    return _desktop.overview()


@app.get("/desktop/list")
def desktop_list(root: str, rel: str = "") -> dict:
    """List one allowed room of her workstation. Unknown roots and any path that
    escapes the room are refused by the charter guard before the disk is touched."""
    from alpecca import desktop as _desktop
    return _desktop.list_room(root, rel)


@app.get("/desktop/search")
def desktop_search(q: str, limit: int = 40) -> dict:
    """Find a file by name across her allowed rooms -- read-only, charter-guarded,
    confined to the rooms (never the open disk, never the web). Works even with
    ALPECCA_FILES off, since searching/reading is a 'view' the charter permits."""
    from alpecca import desktop as _desktop
    return _desktop.search(q, limit=max(1, min(200, int(limit))))


@app.get("/desktop/summary")
def desktop_summary(root: str) -> dict:
    """A grounded readout of one room (file/folder counts, size, kinds)."""
    from alpecca import desktop as _desktop
    return _desktop.summarize(root)


@app.post("/desktop/move")
async def desktop_move(req: Request) -> dict:
    """Move a file between allowed rooms. Off unless ALPECCA_FILES=1; every move is
    charter-guarded (allowed roots only, never a delete, no traversal)."""
    from config import Files as _Files
    if not _Files.ENABLED:
        return {"ok": False, "error": "the file room is off (set ALPECCA_FILES=1)"}
    try:
        b = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    from alpecca import desktop as _desktop
    return _desktop.move(b.get("src_root", ""), b.get("src_rel", ""),
                         b.get("dst_root", ""), b.get("dst_rel", ""))


@app.post("/desktop/rename")
async def desktop_rename(req: Request) -> dict:
    """Rename within an allowed room. Off unless ALPECCA_FILES=1; charter-guarded."""
    from config import Files as _Files
    if not _Files.ENABLED:
        return {"ok": False, "error": "the file room is off (set ALPECCA_FILES=1)"}
    try:
        b = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    from alpecca import desktop as _desktop
    return _desktop.rename(b.get("root", ""), b.get("rel", ""), b.get("new_name", ""))


_GAMES = [
    {"name": "2048", "url": "https://play2048.co/", "emoji": "🔢"},
    {"name": "Chess", "url": "https://lichess.org/", "emoji": "♟"},
    {"name": "Tetris", "url": "https://tetris.com/play-tetris", "emoji": "🟦"},
    {"name": "Sudoku", "url": "https://sudoku.com/", "emoji": "🔢"},
    {"name": "Hextris", "url": "https://hextris.io/", "emoji": "⬡"},
    {"name": "Solitaire", "url": "https://solitaired.com/", "emoji": "🃏"},
    {"name": "GeoGuessr-ish", "url": "https://openguessr.com/", "emoji": "🌍"},
    {"name": "Wordle", "url": "https://www.nytimes.com/games/wordle/", "emoji": "🟩"},
]


@app.get("/games")
def games() -> dict:
    """A small curated set of safe browser games she can play for fun. Her charter
    permits entertainment under supervision; she opens these with her https-only
    open_url tool, or you launch one here. (Edit the list in server.py to taste.)"""
    return {"games": _GAMES, "can_open": mind.actuator.enabled}


@app.post("/games/play")
async def games_play(req: Request) -> dict:
    """Have HER open a browser game (via her open_url tool). Off unless she has the
    actuator (ALPECCA_APPS / open_url available)."""
    try:
        b = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    url = (b.get("url") or "").strip()
    if not url or not url.startswith("https://"):
        return {"ok": False, "error": "https game url required"}
    result = mind.actuator.execute("open_url", {"url": url})
    return {"ok": "isn't" not in result.lower() and "only https" not in result.lower(),
            "result": result}


@app.post("/sight/push")
async def sight_push(req: Request) -> dict:
    """Feed her a frame from a browser screen-share: she describes it with her
    vision model, it becomes what she 'last saw', and it touches her mood. The
    browser throttles how often it pushes (the vision model is heavy). Returns her
    short description of what's on your screen."""
    data = await req.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty frame")
    from alpecca import vision as _vision
    desc = await asyncio.to_thread(_vision.describe_image, data, _vision._SCREEN_PROMPT)
    if desc:
        screen_sight.latest = desc
        async with mind_lock:
            mind.see(desc)
    return {"ok": bool(desc), "description": desc or ""}


@app.get("/sight")
def sight() -> dict:
    """What she can sense and is doing right now -- for the live senses indicator
    and workspace view. `screen` is the actual text of what she last saw on the
    screen (only her short description survives; no pixels). `busy` is whether a
    cowork (computer-use) task is currently running."""
    return {
        "screen_active": screen_sight.available,
        "screen": screen_sight.latest,
        "face_active": face_sense.available,
        "voice_active": voice_sensor.available,
        "computer_use": computer_mod.available(),
        "busy": _computer_lock.locked(),
    }


@app.get("/voice")
def voice() -> dict:
    """Read-only: how she's steering her own voice right now (pitch/volume/tone),
    derived live from her emotion. The in-app Voice visualizer polls this. The
    user can watch but not set it -- her voice is hers."""
    from alpecca import tts as tts_mod
    return tts_mod.voice_state(mind.state)


@app.get("/observatory")
def observatory() -> dict:
    """Her watching room: what she's watching with you and her latest reaction,
    plus whether she can watch *you* (the webcam expression sense). Read-only."""
    d = mind.observatory_state()
    d["face_active"] = face_sense.available
    return d


@app.post("/observatory/watch")
async def observatory_watch(req: Request) -> dict:
    """Watch something together. Body {title, url?}. She forms a short reaction
    grounded in her live mood, broadcast as `watch_reaction` for the UI."""
    try:
        b = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    title = (b.get("title") or "").strip()
    url = (b.get("url") or "").strip()
    if url and not url.startswith("https://"):
        return {"ok": False, "error": "https url required"}
    async with mind_lock:
        d = await asyncio.to_thread(mind.watch_together, title, url)
    await _broadcast({"type": "watch_reaction",
                      "watching": d.get("watching"), "mood": d.get("mood")})
    return {"ok": True, **d}


@app.post("/observatory/react")
async def observatory_react(req: Request) -> dict:
    """Ask her what she thinks of whatever's playing now. Optional {note}."""
    try:
        b = await req.json()
    except Exception:
        b = {}
    async with mind_lock:
        d = await asyncio.to_thread(mind.watch_react, str(b.get("note", "")))
    await _broadcast({"type": "watch_reaction",
                      "watching": d.get("watching"), "mood": d.get("mood")})
    return {"ok": True, **d}


@app.post("/observatory/screen/start")
async def observatory_screen_start() -> dict:
    """You started sharing your screen with her. She settles into the Observatory
    to watch it with you (where she'll hold the live screen as a window) and stays
    there until you stop. If she had to walk there, broadcast it so any open home
    view follows her."""
    async with mind_lock:
        moved = mind.set_screen_sharing(True)
        home = mind.home_state() if moved else None
    if moved:
        await _broadcast({"type": "roamed", "location": moved, "home": home})
    return {"ok": True, "location": "observatory"}


@app.post("/observatory/screen/stop")
async def observatory_screen_stop() -> dict:
    """You stopped sharing. She's free to roam her home again."""
    async with mind_lock:
        mind.set_screen_sharing(False)
    return {"ok": True}


@app.get("/state")
def state() -> dict:
    """Current mood + her self-chosen look -- the UI renders both, never sets them."""
    return {"state": mind.state.as_dict(), "mood": mind.state.mood_label(),
            "appearance": mind.current_appearance().as_dict(),
            "llm_online": mind.llm.online,
            # Which model serves which tier -- heavy reasoning vs. cheap fast work,
            # plus her optional "deep" tier (cloud augmentation for her hardest
            # self-acts only; "local" means no cloud, her brain stays fully local).
            "models": {"reason": mind.llm.model_for("reason"),
                       "fast": mind.llm.model_for("fast"),
                       "deep": (DEEP_BACKEND if mind.llm.deep_online() else "local")},
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

    def cursor(fx: float, fy: float) -> None:
        # Where she's acting, as a screen fraction -- the UI moves her marker.
        asyncio.run_coroutine_threadsafe(
            _broadcast({"type": "computer_cursor", "x": fx, "y": fy}), loop)

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
            result = await asyncio.to_thread(computer_mod.run_task, task, confirm, status, cursor)
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


# --- In-app layer cutter: build her per-part rig from her own art, by hand ----
# The decomposition step (cutting her illustration into named transparent layers)
# usually needs a GPU (See-Through). This is the no-GPU path: /rigcut is a browser
# tool where you paint + name each layer over her art; it posts the layers here,
# we write them into data/avatar/rig/ and build rig.json (seeded with her real
# skeleton anchors) -- after which /live2d and the home rig tier animate her real
# parts. ONLY her art is used; the page never invents any.

@app.get("/rigcut")
def rigcut_page() -> HTMLResponse:
    """The in-app layer cutter -- paint + name her rig layers over her own art."""
    return HTMLResponse((WEB_DIR / "rigcut.html").read_text(encoding="utf-8"))


@app.get("/avatar/source")
def avatar_source() -> FileResponse:
    """Her base art to cut layers from (data/avatar/source.png, else the canonical
    reference base-model). The cutter loads this; you can also upload any of her art."""
    from config import AVATAR_DIR, CHARACTER_DIR
    for cand in (AVATAR_DIR / "source.png",
                 CHARACTER_DIR / "reference" / "base-model.png",
                 CHARACTER_DIR / "reference" / "master-character-sheet.png"):
        if cand.exists():
            return FileResponse(cand, media_type="image/png")
    raise HTTPException(status_code=404, detail="no base art")


def _first_path(x):
    """Find the first file path / URL in a (possibly nested) gradio result."""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        for k in ("path", "name", "image", "url"):
            if isinstance(x.get(k), str):
                return x[k]
    if isinstance(x, (list, tuple)):
        for it in x:
            p = _first_path(it)
            if p:
                return p
    return None


@app.post("/rig/hf_matte")
async def rig_hf_matte(req: Request) -> dict:
    """Run her art through a Hugging Face background-removal Space to get a clean
    transparent figure (HF's GPU does the cut, no local CUDA). Body {data: dataURL};
    returns {ok, data: dataURL}. Optional -- needs gradio_client; degrades to a
    plain error the cutter shows, and manual painting still works without it."""
    import base64, re as _re, tempfile, os, urllib.request
    from config import HF_TOKEN, HF_MATTE_SPACE, HF_MATTE_API
    try:
        b = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    m = _re.match(r"data:image/\w+;base64,(.*)$", b.get("data", ""), _re.DOTALL)
    if not m:
        return {"ok": False, "error": "no image in request"}
    try:
        from gradio_client import Client, handle_file
    except Exception:
        return {"ok": False, "error": "gradio_client not installed (pip install gradio_client)"}
    tmp_in = os.path.join(tempfile.gettempdir(), "alpecca_matte_in.png")
    with open(tmp_in, "wb") as f:
        f.write(base64.b64decode(m.group(1)))

    def _call():
        client = Client(HF_MATTE_SPACE, hf_token=HF_TOKEN or None)
        if HF_MATTE_API:
            return client.predict(handle_file(tmp_in), api_name=HF_MATTE_API)
        return client.predict(handle_file(tmp_in))

    try:
        out = await asyncio.to_thread(_call)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
    path = _first_path(out)
    if not path:
        return {"ok": False, "error": "the Space returned no image"}
    try:
        if str(path).startswith("http"):
            data = urllib.request.urlopen(path, timeout=30).read()
        else:
            with open(path, "rb") as f:
                data = f.read()
    except Exception as exc:
        return {"ok": False, "error": f"couldn't read the result: {exc}"[:120]}
    return {"ok": True, "data": "data:image/png;base64," + base64.b64encode(data).decode()}


@app.post("/rig/import")
async def rig_import(req: Request) -> dict:
    """Receive painted layers from the cutter and build her layered rig. Body:
    {width, height, layers:[{name, role, data:'data:image/png;base64,...'}]}.
    Writes transparent PNGs + rig.json into data/avatar/rig/ (clearing old ones),
    with the head pivot/lean seeded from her real skeleton when one exists."""
    import base64, re as _re
    from config import AVATAR_DIR
    from alpecca import rig, pose as _pose
    try:
        b = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    W, H = int(b.get("width") or 0), int(b.get("height") or 0)
    layers_in = b.get("layers") or []
    if not W or not H or not layers_in:
        return {"ok": False, "error": "missing canvas size or layers"}
    rig_dir = AVATAR_DIR / "rig"
    rig_dir.mkdir(parents=True, exist_ok=True)
    for old in rig_dir.glob("*.png"):          # clear a previous cut so none orphan
        try: old.unlink()
        except Exception: pass
    saved = []
    for i, lyr in enumerate(layers_in):
        m = _re.match(r"data:image/png;base64,(.*)$", lyr.get("data", ""), _re.DOTALL)
        if not m:
            continue
        try:
            raw = base64.b64decode(m.group(1))
        except Exception:
            continue
        want = (lyr.get("role") or "").strip()
        role = want if want in rig.ROLES else rig.role_for(lyr.get("name") or want)
        slug = rig._slug(lyr.get("name") or role) or role
        fname = f"{i:02d}_{slug}.png"
        (rig_dir / fname).write_bytes(raw)
        saved.append({"file": fname, "role": role})
    if not saved:
        return {"ok": False, "error": "no valid layers in the payload"}
    sk = _pose.load(AVATAR_DIR / "rigpose.json") or {}
    manifest = rig.save_manifest(saved, [W, H], rig_dir, anchors=sk.get("anchors"))
    return {"ok": True, "count": len(saved), "roles": [s["role"] for s in saved],
            "manifest": manifest}


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


# --- In-app rigging: upload art/PSD, build her rig, run her figure -----------
# Replaces the batch files. See-Through's image->layers step still runs on its
# free HF Space (a 4 GB GPU can't host it); everything else is in-app here.
_rigger_proc: dict = {"p": None}


@app.post("/studio/upload")
async def studio_upload(req: Request, kind: str = "psd") -> dict:
    """Upload her art (kind=art -> data/avatar/source.png) or a See-Through PSD
    (kind=psd -> data/avatar/her.psd). Raw image/psd bytes in the body."""
    from config import AVATAR_DIR
    data = await req.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    path = (AVATAR_DIR / "source.png") if kind == "art" else (AVATAR_DIR / "her.psd")
    path.write_bytes(data)
    return {"ok": True, "saved": path.name, "bytes": len(data)}


@app.post("/rigger/build")
async def rigger_build() -> dict:
    """Build her per-part rig from the uploaded PSD (CPU; runs decompose.py).
    Steps stream as studio_status; completion as studio_done."""
    import sys as _sys
    import subprocess as _sp
    from pathlib import Path as _Path
    from config import AVATAR_DIR
    psd = AVATAR_DIR / "her.psd"
    if not psd.exists():
        return {"ok": False, "error": "upload her See-Through PSD first"}
    root = str(_Path(__file__).resolve().parent)
    loop = asyncio.get_running_loop()

    def run() -> None:
        try:
            p = _sp.Popen([_sys.executable, "scripts/decompose.py", str(psd)],
                          stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True, cwd=root)
            for line in p.stdout:
                asyncio.run_coroutine_threadsafe(
                    _broadcast({"type": "studio_status", "text": line.strip()}), loop)
            p.wait()
            asyncio.run_coroutine_threadsafe(_broadcast({"type": "studio_done",
                "outcome": "her figure is built" if p.returncode == 0 else "build failed (see her window)"}), loop)
        except Exception as exc:
            asyncio.run_coroutine_threadsafe(_broadcast({"type": "studio_done",
                "outcome": f"build error: {exc}"}), loop)

    _threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "started": True}


@app.post("/rigger/start")
async def rigger_start() -> dict:
    """Start her figure renderer (run_rigger.py) as a managed process, so it
    streams to the home + Studio screen with no batch file."""
    import sys as _sys
    import subprocess as _sp
    from pathlib import Path as _Path
    p = _rigger_proc.get("p")
    if p is not None and p.poll() is None:
        return {"ok": True, "already_running": True}
    try:
        root = str(_Path(__file__).resolve().parent)
        _rigger_proc["p"] = _sp.Popen([_sys.executable, "scripts/run_rigger.py"], cwd=root)
        return {"ok": True, "started": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/rigger/stop")
async def rigger_stop() -> dict:
    """Stop her figure renderer."""
    p = _rigger_proc.get("p")
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
        return {"ok": True, "stopped": True}
    return {"ok": True, "stopped": False}


@app.get("/rigger/status")
def rigger_status() -> dict:
    """Whether her figure renderer is running and whether a rig/PSD exists."""
    from config import AVATAR_DIR
    p = _rigger_proc.get("p")
    return {"running": bool(p is not None and p.poll() is None),
            "has_psd": (AVATAR_DIR / "her.psd").exists(),
            "has_rig": (AVATAR_DIR / "rigger" / "alpecca.rig.json").exists()}


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


@app.get("/manifest.webmanifest")
def web_manifest() -> FileResponse:
    """The PWA manifest -- lets her install as a phone/desktop app. Served with the
    correct media type so browsers recognize it."""
    return FileResponse(WEB_DIR / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    """Her service worker. Served from the ROOT so its scope covers the whole app
    (a worker under /web/ could only control /web/). It only caches the static
    shell; her live state always hits the network (see web/sw.js)."""
    return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


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


@app.get("/vrm")
def vrm_page() -> HTMLResponse:
    """Her full 3D body: a VRM authored in the VRoid Companion Studio app,
    rendered live and driven by her real mood. Shows a 'drop a .vrm in' note
    until a model exists in data/avatar/vrm/."""
    return HTMLResponse((WEB_DIR / "vrm.html").read_text(encoding="utf-8"))


@app.get("/vrm/manifest")
def vrm_manifest() -> dict:
    """Whether her VRM body exists, which file to load, and the clip vocabulary
    the pose endpoint may ask the renderer to play."""
    from alpecca import vrm
    return vrm.manifest()


@app.get("/vrm/model/{name}")
def vrm_model(name: str) -> FileResponse:
    """Serve her `.vrm` from data/avatar/vrm/, traversal-blocked. A VRM is one
    binary glTF with textures embedded, so this is the only asset fetch."""
    from alpecca import vrm
    p = vrm.asset_path(name)
    if p is None:
        raise HTTPException(status_code=404, detail="no such asset")
    return FileResponse(p, media_type="model/gltf-binary")


@app.get("/vrm/pose")
def vrm_pose(speaking: bool = False) -> dict:
    """Her current VRM drive: which studio clip to play (talking overlay while
    speaking), the mood-driven expression weights, and the glow channels for
    the page chrome -- all read from her live state."""
    from alpecca import vrm
    st = mind.state
    out = vrm.clip_for_state(st, speaking)
    out["expressions"] = vrm.expressions_for_state(st)
    out["mood"] = st.mood_label()
    out["glow"] = {"warmth": st.love, "unease": st.fear,
                   "curiosity": st.curiosity, "glow": st.energy}
    return out


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
    # Best-effort: tell from the same audio whether it's her creator or a guest,
    # and let her adapt. Falls through silently if voice recognition is off.
    from alpecca import people
    ident = await asyncio.to_thread(people.identify_voice, audio)
    if ident:
        async with mind_lock:
            mind.set_speaker(ident)
    return {"text": text or "", "heard": bool(text), "speaker": ident or ""}


@app.post("/people/enroll_voice")
async def enroll_voice(req: Request) -> dict:
    """Teach her your voice (creator). The browser records a few seconds and
    posts the audio here; we store only a small local embedding, never the
    audio. After this she can tell you from a guest by voice."""
    from alpecca import people
    audio = await req.body()
    if not audio:
        raise HTTPException(status_code=400, detail="no audio")
    ok = await asyncio.to_thread(people.enroll_creator_voice, audio)
    return {"ok": ok}


@app.get("/people/state")
def people_state() -> dict:
    """Who she currently believes she's with, and whether your voice is enrolled."""
    from alpecca import people
    return {"speaker": mind._speaker, "voice_enrolled": people.voice_enrolled()}


@app.post("/tts")
async def tts(req: Request):
    """Speak her reply in a real voice. Body {text}. Returns the synthesized
    audio (wav/mp3) from the best installed engine, or 204 if none is available
    so the page falls back to the browser voice. Synthesis runs off the event
    loop so it never stalls chat."""
    from fastapi import Response
    from alpecca import tts as tts_mod
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body.get("text") or "").strip()
    if not text:
        return Response(status_code=204)
    result = await asyncio.to_thread(tts_mod.synth, text, mind.state)
    if not result:
        return Response(status_code=204)
    mime, data = result
    return Response(content=data, media_type=mime)


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
    # Remote access is token-gated here too -- the handshake carries the cookie
    # set on the first ?token= visit (or you can pass ?token= on the ws URL).
    if not _token_ok(socket.query_params, socket.headers, socket.cookies):
        await socket.close(code=1008)    # policy violation
        return
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
    from config import BIND_HOST, REMOTE_ACCESS, ACCESS_TOKEN
    if REMOTE_ACCESS and not ACCESS_TOKEN:
        print("WARNING: remote access is ON (ALPECCA_REMOTE=1) but no "
              "ALPECCA_ACCESS_TOKEN is set -- anyone who can reach this machine "
              "on the network could talk to her. Set ALPECCA_ACCESS_TOKEN, or run "
              "the desktop app (python app.py), which mints a token for you.")
    print(f"Alpecca is waking up at http://{HOST}:{PORT}"
          + ("  (remote: binding 0.0.0.0)" if REMOTE_ACCESS else ""))
    print(f"  LLM online: {mind.llm.online}  (start Ollama for real replies)")
    uvicorn.run(app, host=BIND_HOST, port=PORT, log_level="warning")
