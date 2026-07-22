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
import hashlib
import html
import importlib.util
import io
import json
import math
import os
import re
import secrets
import sqlite3
import socket
import sys
import threading
import time
import uuid
import zipfile
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import NoReturn
from urllib.parse import parse_qs, quote, urlparse

# A configured cross-host authority makes direct execution unsafe because it
# would construct CoreMind before acquiring a fencing epoch. Imports remain
# available to tests and the guarded launcher, but `python server.py` must not
# bypass scripts/run_full.py once continuity failover is enabled.
if (
    __name__ == "__main__"
    and os.environ.get("ALPECCA_CONTINUITY_LEASE_URL", "").strip()
    and not os.environ.get("ALPECCA_CONTINUITY_FENCING_EPOCH", "").strip()
):
    raise SystemExit(
        "Cross-host continuity is configured. Start Alpecca through "
        "scripts/run_full.py so a singleton lease is acquired first."
    )

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
import uvicorn

from config import (HOME, HOST, PORT, DEEP_BACKEND, OLLAMA_HOST,
                    COLAB_URL, COLAB_MODEL, COLAB_API_KEY,
                     MINDSCAPE_ENABLED, MINDSCAPE_CLOUD_URL, MINDSCAPE_TOKEN,
                     MINDSCAPE_SYNC_TIMEOUT, MINDSCAPE_AUTO_SYNC_INTERVAL,
                     MINDSCAPE_EVENT_SYNC_MIN_INTERVAL, MINDSCAPE_VAULT_ENABLED,
                     MINDSCAPE_VAULT_URL, MINDSCAPE_VAULT_TOKEN,
                     MINDSCAPE_VAULT_SYNC_TIMEOUT, MINDSCAPE_VAULT_AUTO_SYNC_INTERVAL,
                     MINDSCAPE_VAULT_ARCHIVE_INTERVAL, MINDSCAPE_VAULT_ARCHIVE_MAX_BYTES,
                     PUBLIC_URL, EMBED_BACKFILL,
                    CORE_MEMORY_LEARN_ONLY, DISCORD_CLIENT_ID,
                    CLOUDFLARE_HOSTNAME, OLLAMA_TIMEOUT_SECONDS, STREAM_CHAT,
                    DB_PATH, VISION_CLOUD_MODEL, VISION_CLOUD_TRANSPORT_ROUTE,
                    VISION_CLOUD_DEPLOYMENT, VISION_CLOUD_PROCESSING_LOCATION,
                    ZEROGPU_VISION_TRANSPORT_ROUTE, ZEROGPU_VISION_DEPLOYMENT,
                    ZEROGPU_VISION_MODEL, ZEROGPU_VISION_PROCESSING_LOCATION)
from config import Automation as AutomationCfg
from alpecca.mind import (
    CoreMind,
    ProactiveCandidate,
    _server_validated_discord_perception,
)
from alpecca.sensory import WindowSensor
from alpecca.voice import VoiceSensor
from alpecca import vision
from alpecca.introspection import identity_card
from alpecca import state as state_store
from alpecca import values
from alpecca import hearing
from alpecca import avatar as avatar_mod
from alpecca import computer as computer_mod
from alpecca import runtime_status as runtime_status_mod
from alpecca import mindscape as mindscape_mod
from alpecca import mindscape_vault as mindscape_vault_mod
from alpecca import continuity_journal as continuity_journal_mod
from alpecca import memory as memory_store
from alpecca import mindpage as mindpage_mod
from alpecca import journal as journal_mod
from alpecca import cognition as cognition_mod
from alpecca import instance as instance_mod
from alpecca import routines as routines_mod
from alpecca import watchers as watchers_mod
from alpecca import auth as auth_mod
from alpecca import capabilities as capabilities_mod
from alpecca import capability_leases as capability_leases_mod
from alpecca import host_resources as host_resources_mod
from alpecca import resource_coordinator as resource_coordinator_mod
from alpecca import turn_context as turn_context_mod
from alpecca import commitments as commitments_mod
from alpecca import commitment_executor as commitment_executor_mod
from alpecca import behavior_trial_candidates as behavior_trial_candidates_mod
from alpecca import behavior_trial_profile as behavior_trial_profile_mod
from alpecca import behavior_trial_review_decisions as behavior_trial_review_decisions_mod
from alpecca import behavior_trial_settlement as behavior_trial_settlement_mod
from alpecca import attachment_ingress as attachment_ingress_mod
from alpecca import egress_consent as egress_consent_mod
from alpecca import interactive_egress as interactive_egress_mod
from alpecca import audio_ingress as audio_ingress_mod
from alpecca import bridge_actor_identity as bridge_actor_identity_mod
from alpecca import bridge_actor_transport as bridge_actor_transport_mod
from alpecca import discord_creator_identity as discord_creator_identity_mod
from alpecca import discord_autonomy as discord_autonomy_mod
from alpecca import file_ingress as file_ingress_mod
from alpecca import notification_anchor as notification_anchor_mod
from alpecca import notification_outbox as notification_outbox_mod
from alpecca import web_push_adapter as web_push_adapter_mod
from alpecca import web_push_runtime as web_push_runtime_mod
from alpecca import knowledge_blocks as knowledge_blocks_mod
from alpecca import preferences as preferences_mod
from alpecca import overload as overload_mod
from alpecca import incident_learning as incident_learning_mod
from alpecca import brain_graph as brain_graph_mod
from alpecca import pagefile_approval as pagefile_approval_mod
from alpecca import pagefile_telemetry as pagefile_telemetry_mod
from alpecca import system_pressure as system_pressure_mod
from alpecca import trusted_devices as trusted_devices_mod
from alpecca import restore_approval as restore_approval_mod
from alpecca.behavior_trial_controller import (
    BehaviorTrialController,
    TRIAL_ABORT_REASON,
    TRIAL_EXPIRATION_REASON,
)
from alpecca.qualified_response_ledger import QualifiedResponseLedger


def _environment_enabled(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() not in {
        "", "0", "false", "no", "off",
    }


DISCORD_MEDIA_ENABLED = _environment_enabled("ALPECCA_DISCORD_MEDIA")


async def _read_bounded_body(req: Request, *, max_bytes: int) -> bytes:
    """Read one request body without allowing Starlette to buffer past a cap."""
    raw_length = req.headers.get("content-length", "").strip()
    if raw_length:
        try:
            declared_length = int(raw_length)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="invalid content-length",
                headers={"Cache-Control": "no-store"},
            )
        if declared_length < 0:
            raise HTTPException(
                status_code=400,
                detail="invalid content-length",
                headers={"Cache-Control": "no-store"},
            )
        if declared_length > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="attachment is too large",
                headers={"Cache-Control": "no-store"},
            )

    body = bytearray()
    async for chunk in req.stream():
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="attachment is too large",
                headers={"Cache-Control": "no-store"},
            )
        body.extend(chunk)
    return bytes(body)


def _parse_json_object(raw: bytes) -> dict[str, object]:
    """Parse exact UTF-8 request bytes as one JSON object."""
    try:
        value = json.loads(raw)
    except (RecursionError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise HTTPException(
            status_code=400,
            detail="body must be JSON",
            headers={"Cache-Control": "no-store"},
        )
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=400,
            detail="body must be a JSON object",
            headers={"Cache-Control": "no-store"},
        )
    return value


async def _read_bounded_json_object(
    req: Request, *, max_bytes: int
) -> dict[str, object]:
    """Parse one bounded UTF-8 JSON object without buffering an unlimited body."""
    raw = await _read_bounded_body(req, max_bytes=max_bytes)
    return _parse_json_object(raw)


async def _record_capability_use(
    capability: str,
    *,
    action: str,
    principal: str,
    source: str,
) -> bool:
    """Commit content-free use evidence before a private capability proceeds."""
    try:
        observation_id = await asyncio.to_thread(
            capabilities_mod.record_use,
            capability,
            action=action,
            allowed=True,
            principal_role="creator" if principal == "creator" else "unknown",
            source=source,
        )
    except Exception:
        return False
    return observation_id is not None


def _raise_capability_audit_unavailable() -> None:
    raise HTTPException(
        status_code=503,
        detail={"code": "capability_audit_unavailable"},
        headers={"Cache-Control": "no-store"},
    )

ROOT_DIR = Path(__file__).parent
WEB_DIR = ROOT_DIR / "web"
HOUSE_HQ_DIR = ROOT_DIR / "apps" / "house-hq"
HOUSE_HQ_DIST = HOUSE_HQ_DIR / "dist"
HOUSE_HQ_PUBLIC = HOUSE_HQ_DIR / "public"

# One shared mind for the session. A background sensor lets the mood drift even
# while you're not typing, by folding in a fresh observation on every tick.
behavior_trial_controller = BehaviorTrialController()
# Candidate specifications are derived from server-owned baseline evidence and
# sealed after authorization initializes below.  They do not alter runtime
# behavior until the existing separate approval and start actions complete.
behavior_trial_candidate_store = behavior_trial_candidates_mod.BehaviorTrialCandidateStore(DB_PATH)
# A frozen review may be acknowledged once, but the decision remains separate
# from behavior registration, approval, start, and every runtime write.
behavior_trial_review_decision_store = (
    behavior_trial_review_decisions_mod.BehaviorTrialReviewDecisionStore(DB_PATH)
)
# A separate sealed profile store is the only boundary that may retain a
# completed trial value. The trial controller itself always rolls back first.
behavior_trial_profile_store = behavior_trial_profile_mod.BehaviorTrialProfileStore(
    DB_PATH
)
# Outcome rows remain server-owned. The only public view is aggregate evidence
# in the existing creator-only behavior-trial status response.
qualified_response_ledger = QualifiedResponseLedger(DB_PATH)
# Settlement snapshots freeze only closed, fully settled trial evidence. They
# do not own or alter the runtime override.
behavior_trial_settlement_mod.init_db(DB_PATH)

# A persisted runtime override is not trusted until startup has closed any
# interrupted trial. This event starts unset deliberately and is reset for
# every lifespan entry.
_behavior_trial_recovery_ready = threading.Event()
_behavior_trial_profile_ready = threading.Event()
_behavior_trial_profile_error = "profile seal and retained value not loaded"
# Linearizes the small set of runtime gate transitions with outcome reservation.
# It never surrounds an LLM call, network await, or ``mind_lock`` acquisition.
_behavior_trial_transition_lock = threading.RLock()
# Private sensor/file grants fail closed until startup has revoked every lease
# left active by a previous process. The rest of Alpecca can still start.
_capability_lease_recovery_ready = threading.Event()


def _behavior_profile_generation(profile: Mapping[str, object]) -> str:
    """Return a stable, non-secret identity for one retained profile epoch."""
    material = json.dumps(
        {
            "parameter": str(profile.get("parameter") or "chatter_chance"),
            "source_trial_id": profile.get("source_trial_id"),
            "updated_at": profile.get("updated_at"),
            "value": float(profile["value"]),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _behavior_trial_chatter_gate() -> dict[str, object]:
    """Supply one atomic probability/profile/trial snapshot to ``CoreMind``."""
    snapshot = getattr(behavior_trial_controller, "proactive_gate_snapshot", None)
    if callable(snapshot):
        return snapshot(include_trial=_behavior_trial_recovery_ready.is_set())
    # Compatibility for isolated adapters that expose only the original scalar
    # supplier. The empty generation keeps these reads out of RSI evidence.
    chance = float(behavior_trial_controller.default_chatter_chance)
    if _behavior_trial_recovery_ready.is_set():
        chance = float(behavior_trial_controller.chatter_chance())
    return {
        "chance": chance,
        "trial_id": None,
        "profile_generation": "",
        "gated_at": _time.time(),
    }


def _behavior_trial_chatter_chance() -> float:
    """Compatibility view for callers that need only the live probability."""
    return float(_behavior_trial_chatter_gate()["chance"])


def _run_behavior_trial_transition(fn, /, *args, **kwargs):
    with _behavior_trial_transition_lock:
        return fn(*args, **kwargs)


async def _expire_due_behavior_trials_once() -> None:
    """Reconcile runtime-only trials after recovery without touching the mind lock."""
    if not _behavior_trial_recovery_ready.is_set():
        return
    try:
        closed_trials = await asyncio.to_thread(
            _run_behavior_trial_transition,
            behavior_trial_controller.maintain_runtime_state,
        )
    except Exception:
        # Runtime maintenance is retried by the next background tick. A storage
        # failure must not block startup, chat, or unrelated autonomous work.
        return
    if not closed_trials:
        return

    trial_ids: list[int] = []
    for trial in closed_trials:
        if not isinstance(trial, Mapping):
            continue
        trial_id = trial.get("id")
        if isinstance(trial_id, int) and not isinstance(trial_id, bool) and trial_id > 0:
            trial_ids.append(trial_id)
    try:
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="behavior_trial_maintenance",
            content=(
                f"Closed {len(closed_trials)} behavior trial(s) during runtime "
                "maintenance without starting or extending a trial."
            ),
            confidence=1.0,
            privacy_class="local",
            metadata={
                "trial_count": len(closed_trials),
                "trial_ids": trial_ids,
                "terminal_state": "rolled_back",
            },
        ))
    except Exception:
        # Runtime maintenance is already durable; failing to record its
        # evidence must not make the running companion unavailable.
        pass


async def _settle_closed_behavior_trials_once() -> None:
    """Freeze closed, fully settled trial evidence outside ``mind_lock``."""
    if not _behavior_trial_recovery_ready.is_set():
        return
    try:
        settlements = await asyncio.to_thread(
            behavior_trial_settlement_mod.settle_closed_trials,
            DB_PATH,
        )
    except Exception:
        # Settlement is retried on the next drift tick. It never starts,
        # extends, rolls back, or retunes a trial.
        return
    if not settlements:
        return
    trial_ids: list[int] = []
    statuses: list[str] = []
    for settlement in settlements:
        if not isinstance(settlement, Mapping):
            continue
        trial_id = settlement.get("trial_id")
        if isinstance(trial_id, int) and not isinstance(trial_id, bool) and trial_id > 0:
            trial_ids.append(trial_id)
        status = settlement.get("status")
        if isinstance(status, str):
            statuses.append(status)
    try:
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="behavior_trial_settlement",
            content=(
                f"Settled {len(settlements)} closed behavior trial(s) for creator "
                "review without applying a behavior change."
            ),
            confidence=1.0,
            privacy_class="local",
            metadata={
                "trial_count": len(settlements),
                "trial_ids": trial_ids,
                "statuses": statuses,
                "runtime_change": False,
            },
        ))
    except Exception:
        # The frozen settlement is already durable. Audit failure cannot reopen
        # the trial or cause a second settlement.
        pass


mind = CoreMind(
    chatter_chance_supplier=_behavior_trial_chatter_gate,
)
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
    """Allow an ambient screenshot only when chat and host pressure permit it."""
    if _time.time() - mind._last_user_ts <= 120:
        return False
    # Screen sight invokes the local vision model and can compete with the
    # chat model on the 4 GB GPU.  It is useful self-observation during a calm
    # moment, not work to force through a measured high/critical condition.
    sampler = globals().get("_host_resource_sampler")
    if sampler is None:
        return True
    try:
        snapshot = sampler.snapshot(force=False)
        advisory = snapshot.get("advisory") if isinstance(snapshot, Mapping) else None
        if isinstance(advisory, Mapping) and advisory.get("defer_optional_work") is True:
            return False
    except Exception:
        # An unavailable advisory cannot be replaced with invented pressure.
        pass
    return True

screen_sight = vision.ScreenSight(gate=_conversation_quiet)
face_sense = vision.FaceSense(gate=_conversation_quiet)

# Connected chat clients, so Alpecca can speak to whoever is listening when
# she has something to say unprompted.
ws_clients: set[WebSocket] = set()
_ws_portal_epochs: dict[WebSocket, str] = {}
_ws_portal_turns: dict[WebSocket, turn_context_mod.TurnContext] = {}
_active_ws_portal: tuple[WebSocket, str] | None = None

BACKGROUND_WS_SOURCES = {
    "house-presence",
    "house-perception",
    "room-terminal",
    "recursive-memory",
    "recursive-memory-visible",
    "house-event",
    "mindscape",
}


def _ws_background_source(source: str) -> bool:
    return (source or "").strip().lower() in BACKGROUND_WS_SOURCES


def _server_conversation_id(
    principal: str,
    surface: str,
    *,
    ephemeral_seed: str = "",
) -> str:
    """Return a server-owned durable conversation identifier.

    Alpecca currently has one authenticated creator principal, so that
    principal keeps one durable conversation per surface across reconnects and
    process restarts. Future guest support needs a server-issued subject before
    it can persist safely; until then guest contexts are deliberately scoped to
    a server-generated connection/request seed instead of any caller-supplied
    speaker, source, or display name.
    """
    role = "creator" if principal == "creator" else "guest"
    clean_surface = re.sub(r"[^a-z0-9]+", "-", str(surface or "unknown").lower())
    clean_surface = clean_surface.strip("-")[:48] or "unknown"
    if role == "creator":
        return f"creator-{clean_surface}-primary"
    clean_seed = re.sub(r"[^a-z0-9]+", "-", str(ephemeral_seed or uuid.uuid4().hex).lower())
    clean_seed = clean_seed.strip("-")[:64] or uuid.uuid4().hex
    return f"guest-{clean_surface}-{clean_seed}"


def _websocket_route_surface(socket: WebSocket) -> str:
    path = str(getattr(getattr(socket, "url", None), "path", ""))
    return "house-hq" if path == "/ws/house-hq" else "websocket"


def _proactive_turn_context() -> turn_context_mod.TurnContext:
    active = _active_ws_portal
    if active is not None:
        socket, epoch = active
        surface = _websocket_route_surface(socket)
        return turn_context_mod.TurnContext.create(
            _server_conversation_id("creator", surface),
            principal="creator",
            surface=surface,
            portal_epoch=epoch,
        )
    return turn_context_mod.TurnContext.create(
        _server_conversation_id("creator", "channel"),
        principal="creator",
        surface="channel",
        portal_epoch="local-channel",
    )


def _record_ws_background_observation(
    source: str,
    text: str,
    room: str = "",
    metadata: dict | None = None,
) -> dict:
    clean_source = (source or "ws-background").strip()[:48]
    clean_room = (room or "").strip()[:80]
    obs_id = cognition_mod.record_observation(cognition_mod.CognitionObservation(
        source=clean_source,
        room=clean_room,
        content=text.strip()[:2000],
        confidence=0.75,
        privacy_class="local",
        metadata=metadata or {},
    ))
    intent = cognition_mod.set_intent(cognition_mod.IntentState(
        "observing",
        f"Alpecca recorded a background {clean_source} event without treating it as chat.",
        target=clean_room or clean_source,
        confidence=0.72,
    ))
    return {"observation_id": obs_id, "intent": intent}


def _observe():
    """One full sensory snapshot: window title + whichever ambient senses are on."""
    obs = sensor.observe()
    voice_sensor.annotate(obs)
    face_sense.annotate(obs)
    return obs


def _sense_status() -> dict:
    return {
        "window": sensor.available,
        "voice_tone": voice_sensor.available,
        "screen_sight": screen_sight.available,
        "expressions": face_sense.available,
        "actions": mind.actuator.enabled,
        "computer_use": computer_mod.available(),
    }


def _runtime_status(check_models: bool = True) -> dict:
    from alpecca import tts as tts_mod
    models = {
        "reason": mind.llm.model_for("reason"),
        "fast": mind.llm.model_for("fast"),
        "deep": DEEP_BACKEND if mind.llm.deep_online() else "local",
        "last_call": mind.llm.last_call(),
    }
    ollama = None
    if check_models:
        ollama = runtime_status_mod.check_ollama(
            OLLAMA_HOST,
            models["reason"],
            models["fast"],
        )
        models["colab"] = runtime_status_mod.check_colab(
            COLAB_URL,
            model=COLAB_MODEL,
            api_key=COLAB_API_KEY,
        )
    status = runtime_status_mod.build_runtime_status(
        models=models,
        llm_online=mind.llm.online,
        deep_backend=DEEP_BACKEND,
        deep_online=mind.llm.deep_online(),
        voice=tts_mod.voice_state(mind.state),
        senses=_sense_status(),
        ollama=ollama,
    )
    status["optional_work"] = _optional_work_telemetry()
    status["host_resources"] = _host_resource_sampler.snapshot()
    return status


def _living_systems_context(check_models: bool = False) -> dict:
    runtime = _runtime_status(check_models=check_models)
    capabilities = runtime_status_mod.cognition_capabilities(runtime)
    setup = mindscape_mod.cloud_setup_plan(
        ROOT_DIR / "deploy" / "mindscape-worker",
        cloud_url=MINDSCAPE_CLOUD_URL,
        token_configured=bool(MINDSCAPE_TOKEN),
    )
    voice_cap = capabilities.get("voice") if isinstance(capabilities.get("voice"), dict) else {}
    voice_raw = runtime.get("voice") if isinstance(runtime.get("voice"), dict) else {}
    return {
        "runtime": runtime,
        "voice": {**voice_raw, **voice_cap},
        "senses": _sense_status(),
        "mindscape": setup,
        "capabilities": capabilities,
    }


def _mindscape_snapshot(check_models: bool = True) -> dict:
    senses = _sense_status()
    runtime = _runtime_status(check_models=check_models)
    cognition = mind.cognition_state(
        senses=senses,
        capabilities=runtime_status_mod.cognition_capabilities(runtime),
    )
    return mindscape_mod.continuity_snapshot(
        state={
            "state": mind.state.as_dict(),
            "mood": mind.state.mood_label(),
        },
        cognition=cognition,
        memories=memory_store.recent(limit=20),
        journal=mind.journal_state(),
        runtime=runtime,
        home=mind.home_state(),
        cloud_url=MINDSCAPE_VAULT_URL or MINDSCAPE_CLOUD_URL,
        enabled=bool(MINDSCAPE_VAULT_ENABLED or MINDSCAPE_ENABLED),
    )


def _retire_ws_portal(socket: WebSocket, *, portal_epoch: str | None = None,
                      reason: str = "disconnect") -> bool:
    """Fence one portal without allowing an old finalizer to close its successor."""
    global _active_ws_portal
    current = _ws_portal_epochs.get(socket)
    if current is None or (portal_epoch is not None and current != portal_epoch):
        return False
    _ws_portal_epochs.pop(socket, None)
    turn = _ws_portal_turns.pop(socket, None)
    if turn is not None:
        turn.cancel(reason)
    ws_clients.discard(socket)
    if _active_ws_portal == (socket, current):
        _active_ws_portal = None
    lease_store = globals().get("_capability_lease_store")
    if isinstance(lease_store, capability_leases_mod.CapabilityLeaseStore):
        try:
            lease_store.stop_connection(current, reason=reason)
        except Exception:
            # The portal epoch is fenced in memory even if receipt storage is
            # temporarily unavailable; no later request can treat it as live.
            pass
    # The inactive transition only clears one boolean and performs no model or
    # disk work. Do it synchronously with portal fencing so a successor cannot
    # inherit an Observatory pin from the disconnected screen-share lease.
    mind.set_screen_sharing(False)
    return True


def _open_ws_portal(socket: WebSocket, portal_epoch: str | None = None) -> str:
    """Claim the single writable WebSocket portal and retire its predecessor."""
    global _active_ws_portal
    epoch = str(portal_epoch or uuid.uuid4().hex)
    previous = _active_ws_portal
    if previous is not None:
        _retire_ws_portal(
            previous[0], portal_epoch=previous[1], reason="portal_epoch_replaced",
        )
    _ws_portal_epochs[socket] = epoch
    _active_ws_portal = (socket, epoch)
    ws_clients.add(socket)
    return epoch


def _ws_portal_epoch_current(socket: WebSocket, portal_epoch: str) -> bool:
    return (
        _active_ws_portal == (socket, portal_epoch)
        and _ws_portal_epochs.get(socket) == portal_epoch
    )


def _begin_ws_portal_turn(socket: WebSocket,
                          turn: turn_context_mod.TurnContext) -> bool:
    if (
        not _ws_portal_epoch_current(socket, turn.portal_epoch)
        or turn.cancelled.is_set()
    ):
        turn.cancel("stale_portal_epoch")
        return False
    previous = _ws_portal_turns.get(socket)
    if previous is not None and previous is not turn:
        previous.cancel("superseded_turn")
    _ws_portal_turns[socket] = turn
    return True


def _finish_ws_portal_turn(socket: WebSocket,
                           turn: turn_context_mod.TurnContext) -> bool:
    if _ws_portal_turns.get(socket) is not turn:
        return False
    _ws_portal_turns.pop(socket, None)
    return True


def _ws_portal_allows(socket: WebSocket,
                      turn: turn_context_mod.TurnContext | None = None,
                      *, portal_epoch: str | None = None,
                      allow_cancelled: bool = False) -> bool:
    current = _ws_portal_epochs.get(socket)
    if current is None or not _ws_portal_epoch_current(socket, current):
        return False
    if portal_epoch is not None and current != portal_epoch:
        return False
    if turn is None:
        return True
    return (
        current == turn.portal_epoch
        and _ws_portal_turns.get(socket) is turn
        and (allow_cancelled or not turn.cancelled.is_set())
    )


async def _send_ws_json(socket: WebSocket, payload: dict, *,
                        turn: turn_context_mod.TurnContext | None = None,
                        portal_epoch: str | None = None,
                        allow_cancelled: bool = False) -> bool:
    """Send only through the current portal epoch; retire failed transports."""
    if not _ws_portal_allows(
        socket, turn, portal_epoch=portal_epoch,
        allow_cancelled=allow_cancelled,
    ):
        if socket not in _ws_portal_epochs:
            ws_clients.discard(socket)
        return False
    current = _ws_portal_epochs.get(socket)
    try:
        await socket.send_json(payload)
        return True
    except Exception:
        _retire_ws_portal(
            socket, portal_epoch=current, reason="send_failed",
        )
        return False


async def _broadcast(payload: dict,
                     turn: turn_context_mod.TurnContext | None = None) -> int:
    """Best-effort fan-out; return the number of current portals reached."""
    delivered = 0
    for client in list(ws_clients):
        if await _send_ws_json(client, payload, turn=turn):
            delivered += 1
    return delivered


async def _expire_due_qualified_response_outcomes_once(
    *, now: float | None = None,
) -> list[dict]:
    """Close durable response windows without holding the in-memory mind lock."""
    stamp = _time.time() if now is None else now
    try:
        closed = await asyncio.to_thread(
            qualified_response_ledger.expire_due,
            now=stamp,
        )
    except Exception:
        # Ledger maintenance is best-effort. It must not interrupt chat,
        # delivery, or the independent initiative backoff timer.
        return []
    if not closed:
        return []

    terminal_counts = {"unanswered": 0, "cancelled": 0}
    for row in closed:
        state = str(row.get("state") or "") if isinstance(row, Mapping) else ""
        if state in terminal_counts:
            terminal_counts[state] += 1
    try:
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="qualified_response_outcome_maintenance",
            content=(
                f"Closed {len(closed)} qualified response outcome(s) after their "
                "response window."
            ),
            confidence=1.0,
            privacy_class="local",
            metadata={
                "closure_count": len(closed),
                "unanswered": terminal_counts["unanswered"],
                "cancelled": terminal_counts["cancelled"],
            },
        ))
    except Exception:
        # Closure is already durable. Failing to add a local observation does
        # not reopen it or change the metric.
        pass
    await _reconcile_behavior_trial_candidate_once()
    return closed


def _qualified_response_outcome_eligible(
    candidate: object | None,
    initiative: dict | None,
    proactive_turn: turn_context_mod.TurnContext | None,
) -> bool:
    """Restrict qualified-response exposure to typed chatter on a live portal."""
    return (
        isinstance(candidate, ProactiveCandidate)
        and candidate.origin == "chatter"
        and isinstance(initiative, dict)
        and initiative.get("allowed") is True
        and isinstance(proactive_turn, turn_context_mod.TurnContext)
        and proactive_turn.principal == "creator"
        and proactive_turn.surface in {"websocket", "house-hq"}
    )


def _reserve_qualified_response_dispatch(
    turn: turn_context_mod.TurnContext,
    candidate: ProactiveCandidate,
) -> str | None:
    """Synchronously validate and reserve at one transition linearization point."""
    with _behavior_trial_transition_lock:
        delivery_id = uuid.uuid4().hex
        dispatched_at = _time.time()
        if not _behavior_trial_recovery_ready.is_set():
            return None
        if (
            not isinstance(candidate, ProactiveCandidate)
            or candidate.origin != "chatter"
            or not candidate.profile_generation
            or candidate.gate_chance is None
            or candidate.gate_draw is None
            or candidate.gated_at is None
            or not math.isfinite(candidate.gate_chance)
            or not math.isfinite(candidate.gate_draw)
            or not math.isfinite(candidate.gated_at)
            or not 0.0 <= candidate.gate_draw < candidate.gate_chance <= 1.0
            or not 0.0 <= candidate.gated_at <= dispatched_at
        ):
            return None
        try:
            live_gate = behavior_trial_controller.proactive_gate_snapshot(
                gated_at=dispatched_at,
                include_trial=True,
            )
            live_chance = float(live_gate["chance"])
        except Exception:
            # An unverifiable transition is never silently reclassified as
            # baseline evidence.
            return None
        if (
            candidate.trial_id != live_gate.get("trial_id")
            or candidate.profile_generation
            != str(live_gate.get("profile_generation") or "")
            or candidate.gate_chance != live_chance
        ):
            return None
        try:
            qualified_response_ledger.begin_dispatch(
                delivery_id=delivery_id,
                scope_key=turn.scope_key,
                surface=turn.surface,
                proactive_turn_id=turn.turn_id,
                response_window_seconds=INITIATIVE_RESPONSE_WINDOW_SECONDS,
                trial_id=candidate.trial_id,
                dispatched_at=dispatched_at,
            )
        except Exception:
            return None
        return delivery_id


async def _begin_qualified_response_dispatch(
    turn: turn_context_mod.TurnContext,
    candidate: ProactiveCandidate,
) -> str | None:
    """Reserve a verified exposure off the event loop without a transition gap."""
    return await asyncio.to_thread(
        _reserve_qualified_response_dispatch,
        turn,
        candidate,
    )


async def _confirm_qualified_response_dispatch(delivery_id: str) -> bool:
    """Count an exposure only after a portal confirms delivery."""
    try:
        row = await asyncio.to_thread(
            qualified_response_ledger.confirm_delivery,
            delivery_id,
            delivered_at=_time.time(),
        )
    except Exception:
        return False
    confirmed = (
        isinstance(row, Mapping)
        and str(row.get("state") or "") in {"pending", "responded"}
    )
    if confirmed and str(row.get("state") or "") == "responded":
        await _reconcile_behavior_trial_candidate_once()
    return confirmed


async def _cancel_qualified_response_dispatch(delivery_id: str) -> None:
    """Keep failed, queued, and unconfirmed sends outside the denominator."""
    try:
        await asyncio.to_thread(
            qualified_response_ledger.cancel_dispatch,
            delivery_id,
            cancelled_at=_time.time(),
        )
    except Exception:
        # A later idempotent expiry pass will still cancel any surviving
        # dispatching row. Do not let a ledger failure affect delivery.
        pass


async def _record_qualified_creator_response(
    turn: turn_context_mod.TurnContext,
    user_text: str,
    source: str,
) -> bool:
    """Match one authenticated, contentful portal turn without retaining text."""
    if (
        not isinstance(turn, turn_context_mod.TurnContext)
        or turn.principal != "creator"
        or not isinstance(user_text, str)
        or not user_text.strip()
        or _ws_background_source(source)
    ):
        return False
    try:
        row = await asyncio.to_thread(
            qualified_response_ledger.record_creator_response,
            scope_key=turn.scope_key,
            surface=turn.surface,
            response_turn_id=turn.turn_id,
            received_at=_time.time(),
        )
    except Exception:
        # Evidence collection must never block the authenticated chat turn.
        return False
    recorded = isinstance(row, Mapping)
    if recorded and str(row.get("state") or "") == "responded":
        await _reconcile_behavior_trial_candidate_once()
    return recorded


def _schedule_ignored_outreach(initiative: dict | None) -> bool:
    """Arm backoff only after verified delivery and a real response window."""
    if not isinstance(initiative, dict) or not initiative.get("allowed"):
        return False
    scope = str(initiative.get("scope") or "")
    dedupe_key = str(initiative.get("dedupe_key") or "")
    if not scope or not dedupe_key:
        return False

    async def observe_response_window() -> None:
        await asyncio.sleep(INITIATIVE_RESPONSE_WINDOW_SECONDS)
        # Durable outcome closure precedes the in-memory backoff so the same
        # response window is resolved in a stable server-owned ledger first.
        await _expire_due_qualified_response_outcomes_once(now=_time.time())
        await asyncio.to_thread(
            mind.mark_initiative_ignored,
            scope,
            dedupe_key,
        )

    task = asyncio.create_task(observe_response_window())
    _initiative_outcome_tasks.add(task)
    task.add_done_callback(_initiative_outcome_tasks.discard)
    return True


async def _deliver_proactive_once(
    text: str,
    initiative: dict | None = None,
    *,
    proactive_turn: turn_context_mod.TurnContext | None = None,
    outcome_candidate: object | None = None,
) -> dict:
    """Deliver one proactive event to exactly one currently reachable surface."""
    if ws_clients:
        delivery_id = None
        if _qualified_response_outcome_eligible(
            outcome_candidate,
            initiative,
            proactive_turn,
        ):
            delivery_id = await _begin_qualified_response_dispatch(
                proactive_turn,
                outcome_candidate,
            )
        try:
            delivered = await _broadcast({
                "type": "proactive", "reply": text,
                "mood": mind.state.mood_label(),
                "state": mind.state.as_dict(),
                "appearance": mind.current_appearance().as_dict(),
            })
        except Exception:
            delivered = 0
        if delivered:
            if delivery_id and not await _confirm_qualified_response_dispatch(delivery_id):
                await _cancel_qualified_response_dispatch(delivery_id)
            _schedule_ignored_outreach(initiative)
            return {"surface": "portal", "delivered": True, "count": delivered}
        if delivery_id:
            await _cancel_qualified_response_dispatch(delivery_id)

    from alpecca import openclaw_bridge
    result = await _bounded_thread(
        "openclaw_deliver",
        openclaw_bridge.try_deliver,
        text,
        timeout=BACKGROUND_DELIVERY_TIMEOUT,
    )
    delivered = bool(isinstance(result, dict) and result.get("ok") is True)
    queued = bool(isinstance(result, dict) and result.get("queued") is True)
    if delivered:
        _schedule_ignored_outreach(initiative)
    elif isinstance(initiative, dict):
        scope = str(initiative.get("scope") or "")
        dedupe_key = str(initiative.get("dedupe_key") or "")
        if scope and dedupe_key:
            await asyncio.to_thread(
                mind.clear_initiative_outreach,
                scope,
                dedupe_key,
            )
    return {
        "surface": "channel",
        "delivered": delivered,
        "queued": queued,
        "result": result,
    }

# ``mind_lock`` only protects the short observation snapshot.  Turn commit
# barriers fence writes after generation; no LLM call runs under this lock.
mind_lock = asyncio.Lock()
_hearing_lock = asyncio.Lock()
active_chat_turns = 0
active_tts_requests = 0
last_chat_turn_started = 0.0
CHAT_PRIORITY_QUIET_SECONDS = 12.0
_host_resource_sampler = host_resources_mod.HostResourceSampler()


def _host_resource_snapshot_supplier() -> dict[str, object]:
    """Read the current shared sampler cache when CoreMind builds a Soul snapshot."""
    return _host_resource_sampler.snapshot(force=False)


def _governed_learning_status_supplier() -> dict[str, object]:
    """Return a bounded recovery-gated lifecycle projection for CoreMind.

    This is deliberately read-only. The Soul receives only status facts and
    cannot register, approve, start, settle, retain, or revert a behavior trial.
    """
    if not _behavior_trial_recovery_ready.is_set():
        return {"recovery_ready": False}
    snapshot: dict[str, object] = dict(behavior_trial_controller.status_snapshot())
    snapshot["recovery_ready"] = True
    try:
        snapshot["registration_candidate"] = _behavior_trial_candidate_public_summary()
        snapshot["registration_candidate_available"] = True
    except Exception:
        snapshot["registration_candidate"] = None
        snapshot["registration_candidate_available"] = False
    try:
        settlements = behavior_trial_settlement_mod.list_settlements(DB_PATH, limit=5)
        snapshot["review_settlements"] = [
            {
                "trial_id": item.get("trial_id"),
                "status": item.get("status"),
                "outcome": item.get("outcome"),
            }
            for item in settlements
            if isinstance(item, Mapping)
        ]
        snapshot["review_settlements_available"] = True
    except Exception:
        snapshot["review_settlements"] = []
        snapshot["review_settlements_available"] = False
    try:
        decisions = behavior_trial_review_decision_store.list(limit=5)
        snapshot["profile_decisions"] = [
            {
                "trial_id": item.get("trial_id"),
                "decision": item.get("decision"),
            }
            for item in decisions
            if isinstance(item, Mapping)
        ]
        snapshot["profile_decisions_available"] = True
    except Exception:
        snapshot["profile_decisions"] = []
        snapshot["profile_decisions_available"] = False
    return snapshot


if hasattr(mind, "set_host_resource_supplier"):
    mind.set_host_resource_supplier(_host_resource_snapshot_supplier)
else:
    # CoreMind's transitional constructor seam keeps server startup compatible
    # until the public setter is available in the shared core module.
    mind._host_resource_snapshot_supplier = _host_resource_snapshot_supplier
if hasattr(mind, "set_governed_learning_supplier"):
    mind.set_governed_learning_supplier(_governed_learning_status_supplier)
else:
    mind._governed_learning_supplier = _governed_learning_status_supplier
_optional_work_coordinator = resource_coordinator_mod.ResourceCoordinator()
INITIATIVE_RESPONSE_WINDOW_SECONDS = max(
    30.0,
    float(os.environ.get("ALPECCA_INITIATIVE_RESPONSE_WINDOW", "120")),
)
_initiative_outcome_tasks: set[asyncio.Task] = set()
# Must OUTLAST the LLM's own request bound (ALPECCA_OLLAMA_TIMEOUT), or the UI
# gives up on turns the brain would have finished: her qwen3.5:9b takes ~25s
# warm and ~40s on a cold load, and the old hardcoded 30s here served the
# canned "deeper model is taking too long" line right before the real reply
# landed. Override with ALPECCA_WS_CHAT_TIMEOUT.
WS_CHAT_REPLY_TIMEOUT_SECONDS = float(os.environ.get(
    "ALPECCA_WS_CHAT_TIMEOUT", str(max(45.0, OLLAMA_TIMEOUT_SECONDS + 15.0))))
_mindscape_sync_status = {
    "enabled": bool(MINDSCAPE_ENABLED),
    "cloud_configured": bool(MINDSCAPE_CLOUD_URL),
    "cloud_url": MINDSCAPE_CLOUD_URL,
    "auto_interval": MINDSCAPE_AUTO_SYNC_INTERVAL,
    "event_min_interval": MINDSCAPE_EVENT_SYNC_MIN_INTERVAL,
    "last_attempt": 0.0,
    "last_success": 0.0,
    "last_trigger": 0.0,
    "last_trigger_reason": "",
    "last_status": "not_started",
    "last_error": "",
    "attempts": 0,
    "successes": 0,
    "event_triggers": 0,
    "event_skips": 0,
}

# The legacy Worker is retained only as a compatibility fallback.  Once the
# separately configured Vault is live, it becomes the sole automatic cloud
# continuity target so private state is not mirrored in plaintext twice.
_mindscape_vault_status = {
    "enabled": bool(MINDSCAPE_VAULT_ENABLED),
    "configured": bool(MINDSCAPE_VAULT_URL and MINDSCAPE_VAULT_TOKEN),
    "cloud_url": MINDSCAPE_VAULT_URL,
    "auto_interval": MINDSCAPE_VAULT_AUTO_SYNC_INTERVAL,
    "archive_interval": MINDSCAPE_VAULT_ARCHIVE_INTERVAL,
    "last_attempt": 0.0,
    "last_success": 0.0,
    "last_archive_attempt": 0.0,
    "last_archive_success": 0.0,
    "last_status": "not_started",
    "last_archive_status": "not_started",
    "last_error": "",
    "attempts": 0,
    "successes": 0,
    "transport_token_source": "environment" if MINDSCAPE_VAULT_TOKEN else "not_loaded",
}
_mindscape_vault_token_cache: str | None = None
_mindscape_event_sync_task: asyncio.Task | None = None

# How often the background sense ticks (seconds). This is what gives Alpecca a
# life of its own between messages -- it keeps watching and feeling.
DRIFT_INTERVAL = 8.0
BACKGROUND_DRIFT_TIMEOUT = 3.0
BACKGROUND_REFLECT_TIMEOUT = 10.0
BACKGROUND_LIVING_TIMEOUT = 4.0
BACKGROUND_VOLUNTEER_TIMEOUT = 8.0
BACKGROUND_DELIVERY_TIMEOUT = 6.0
BACKGROUND_MINDSCAPE_TIMEOUT = 12.0
BACKGROUND_LIVING_INTERVAL = 40.0
BACKGROUND_EMBED_BACKFILL_INTERVAL = 120.0
try:
    # Derived-index work is local, bounded, and useful by default. Keep it
    # deliberately infrequent so an idle companion does not churn through old
    # page transcripts while the creator is using the laptop.
    BACKGROUND_MINDPAGE_CONTENT_INDEX_INTERVAL = max(
        30.0,
        float(os.environ.get("ALPECCA_MINDPAGE_CONTENT_INDEX_INTERVAL", "300")),
    )
except (TypeError, ValueError):
    BACKGROUND_MINDPAGE_CONTENT_INDEX_INTERVAL = 300.0
try:
    BACKGROUND_MINDPAGE_TIER_MAINTENANCE_INTERVAL = max(
        60.0,
        float(os.environ.get("ALPECCA_MINDPAGE_TIER_MAINTENANCE_INTERVAL", "900")),
    )
except (TypeError, ValueError):
    BACKGROUND_MINDPAGE_TIER_MAINTENANCE_INTERVAL = 900.0
_background_autonomy_status = {
    "enabled": True,
    "started_at": _time.time(),
    "drift_interval": DRIFT_INTERVAL,
    "living_interval": BACKGROUND_LIVING_INTERVAL,
    "last_drift_at": 0.0,
    "last_living_at": 0.0,
    "last_living_reason": "",
    "last_living_line": "",
    "last_living_system": "",
    "last_living_room": "",
    "last_living_question": "",
    "last_living_observation_id": None,
    "last_living_memory_id": None,
    "last_living_journal_id": None,
    "last_learning_record_id": None,
    "last_living_self_feedback": {},
    "last_living_next_action": {},
    "last_living_engagement_proposal": {},
    "last_backfill_at": 0.0,
    "last_backfill_run": {},
    "mindpage_content_index_backfill_interval": BACKGROUND_MINDPAGE_CONTENT_INDEX_INTERVAL,
    "last_mindpage_content_index_backfill_at": 0.0,
    "last_mindpage_content_index_backfill_run": {},
    "mindpage_tier_maintenance_interval": BACKGROUND_MINDPAGE_TIER_MAINTENANCE_INTERVAL,
    "last_mindpage_tier_maintenance_at": 0.0,
    "last_mindpage_tier_maintenance_run": {},
    "last_error": "",
    "tick_count": 0,
    "living_tick_count": 0,
}


def _remember_living_result(living: dict, *, counted: bool = False) -> None:
    """Persist the latest autonomous world tick for app-visible state."""
    if not isinstance(living, dict):
        return
    learning_record = living.get("learning_record") if isinstance(living.get("learning_record"), dict) else {}
    activated = living.get("activated_system") if isinstance(living.get("activated_system"), dict) else {}
    room = living.get("room") if isinstance(living.get("room"), dict) else {}
    self_feedback = living.get("self_feedback") if isinstance(living.get("self_feedback"), dict) else {}
    next_action = living.get("next_action") if isinstance(living.get("next_action"), dict) else {}
    engagement = living.get("engagement_proposal") if isinstance(living.get("engagement_proposal"), dict) else {}
    update = {
        "last_living_at": _time.time(),
        "last_living_reason": str(living.get("reason") or "background")[:80],
        "last_living_line": str(living.get("line") or "")[:500],
        "last_living_system": str(activated.get("id") or "")[:80],
        "last_living_room": str(room.get("name") or "")[:120],
        "last_living_question": str(living.get("question") or "")[:500],
        "last_living_observation_id": living.get("observation_id"),
        "last_living_memory_id": living.get("memory_id"),
        "last_living_journal_id": living.get("journal_id"),
        "last_learning_record_id": learning_record.get("id"),
        "last_living_self_feedback": self_feedback,
        "last_living_next_action": next_action,
        "last_living_engagement_proposal": engagement,
        "last_error": "",
    }
    if counted:
        update["living_tick_count"] = int(_background_autonomy_status.get("living_tick_count") or 0) + 1
    _background_autonomy_status.update(update)


def _background_autonomy_snapshot() -> dict:
    now = _time.time()
    last_living = float(_background_autonomy_status.get("last_living_at") or 0.0)
    next_living_in = max(0.0, BACKGROUND_LIVING_INTERVAL - (now - last_living)) if last_living else 0.0
    return {
        **_background_autonomy_status,
        "now": now,
        "next_living_in": round(next_living_in, 3),
        "recursive_engagement": cognition_mod.recent_recursive_engagement(limit=5),
        "current_intent": cognition_mod.current_intent(),
    }


def _ws_chat_timeout_result(user_text: str,
                            turn: turn_context_mod.TurnContext | None = None,
                            *, record: bool = True) -> dict:
    turn = turn or turn_context_mod.TurnContext.default()
    low = user_text.strip().lower()
    if low in {"hi", "hello", "hey", "hiya", "yo"}:
        reply = "Hi. I'm here with you. What should we focus on next?"
    elif any(term in low for term in ("stop walking", "stand still", "stay still", "stop moving")):
        reply = "Okay. I'll stay still and listen while the deeper core catches up."
    else:
        reply = (
            "I'm here with you. My deeper model is taking too long, so I'm staying "
            "in grounded live mode for this turn. Try that again if you want me to "
            "send it through the full core."
        )
    if turn.principal != "creator":
        return {"reply": reply}
    model_use = {
        "requested_tier": "reason",
        "used_tier": "fallback",
        "backend": "timeout",
        "model": "",
        "ok": False,
        "fallback": True,
        "error": "WebSocket chat generation timed out.",
        "turn": turn.audit_metadata(),
    }
    # A timeout cancels its TurnContext before this fallback is built. Keep the
    # user-visible bounded reply, but do not create a late chat/intent write.
    if record and not turn.cancelled.is_set():
        try:
            chat_turn_fields = {
                "user_text": user_text,
                "reply": reply,
                "room": getattr(mind, "_location", ""),
                "mood": mind.state.mood_label(),
                "intent": "replying",
                "model_use": model_use,
                "memory_evidence": [],
                "privacy_class": turn.memory_scope,
            }
            if "scope" in getattr(cognition_mod.ChatTurn, "__dataclass_fields__", {}):
                chat_turn_fields["scope"] = turn.memory_scope
            cognition_mod.record_chat_turn(cognition_mod.ChatTurn(**chat_turn_fields))
            cognition_mod.set_intent(cognition_mod.IntentState(
                "waiting",
                "Alpecca returned a bounded fallback reply after the live model stalled.",
                target=turn.principal,
            ))
        except Exception:
            pass
    return {
        "reply": reply,
        "mood": mind.state.mood_label(),
        "state": mind.state.as_dict(),
        "location": getattr(mind, "_location", ""),
        "moved": False,
        "memories_used": [],
        "memory_evidence": [],
        "self_reflection": "The live model timed out before finishing a full reply.",
        "appearance": mind.current_appearance().as_dict(),
        "llm_online": mind.llm.online,
        "model_use": model_use,
        "intent": cognition_mod.current_intent(),
        "turn": turn.audit_metadata(),
    }


def _record_chat_stall_learning(*, safe: bool) -> None:
    """Connect verified chat completion state to the incident learner."""
    try:
        cue = "chat-reply-stall"
        if safe:
            signal = incident_learning_mod.assess_cues([cue])
            if signal.incident_id is None:
                return
            incident_learning_mod.record_outcome(signal.incident_id, safe=True)
        else:
            incident_learning_mod.record_incident(
                source="chat_runtime",
                cue=cue,
                summary="A live chat turn exceeded its bounded reply deadline.",
                severity=0.62,
                controllability=0.55,
                prediction_error=0.85,
            )
        mind._active_incident_signal = incident_learning_mod.assess_cues([cue])
    except Exception:
        # Chat delivery and its fallback must survive learning-ledger failure.
        pass


def _compact_reply_compare(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _reply_repeats_user_text(user_text: str, reply: str) -> bool:
    user = _compact_reply_compare(user_text)
    response = _compact_reply_compare(reply)
    if not user or not response:
        return False
    if response == user:
        return True
    echo_prefixes = (
        _compact_reply_compare("You said"),
        _compact_reply_compare("I hear you"),
        _compact_reply_compare("You wrote"),
        _compact_reply_compare("Repeating back"),
    )
    if any(response.startswith(prefix + user) for prefix in echo_prefixes):
        return True
    if len(user) >= 8 and response.startswith(user) and len(response) <= len(user) + 18:
        return True
    return False


def _repair_echo_reply(user_text: str, result: dict,
                       turn: turn_context_mod.TurnContext | None = None) -> dict:
    reply = str((result or {}).get("reply") or "").strip()
    if not _reply_repeats_user_text(user_text, reply):
        return result
    # CoreMind has already committed the rejected draft. This is a
    # presentation-only repair, never another chat/cognition write.
    repaired = _ws_chat_timeout_result(user_text, turn=turn, record=False)
    if turn is not None and turn.principal != "creator":
        return {**result, **repaired}
    repaired["model_use"] = {
        **(result.get("model_use") or {}),
        "requested_tier": (result.get("model_use") or {}).get("requested_tier", "reason"),
        "used_tier": "fallback",
        "backend": (result.get("model_use") or {}).get("backend", "echo_guard"),
        "ok": False,
        "fallback": True,
        "error": "Model reply repeated the user message and was replaced by the echo guard.",
    }
    repaired["self_reflection"] = "A repeated-message reply was blocked before it reached the player."
    return {**result, **repaired}


def _house_chat_reply_tier(user_text: str) -> str:
    """House HQ player chat should use the same natural core as Discord.

    Background chatter can use the fast tier, but direct player messages in the
    embodied HQ are the main relationship surface. Routing them to the fast tier
    made the HQ feel less responsive/natural than Discord whenever the fast
    model or Colab path was weaker, stale, or unavailable.
    """
    return "reason"


async def _locked_ws_chat_turn(turn: turn_context_mod.TurnContext,
                               user_text: str, image_desc: str | None = None,
                               attachment_context: str = "",
                               situation_hint: str = "",
                               reply_tier: str = "reason",
                               on_token=None,
                                activity_recorded: bool = False,
                                private_context: bool = False,
                                _trusted_perception: object | None = None,
                                _persist_verified_discord_memory: bool = False,
                                _persist_verified_discord_history: bool = False,
                                _verified_discord_memory_text: str = "") -> dict:
    # Keep sensor state coherent, but never hold this state lock across a model
    # call. A synchronous worker is serialized below until it finishes even if
    # its caller has already timed out.
    creator_authority = turn.principal == "creator"
    if not turn.allow_work():
        if creator_authority:
            return {"cancelled": True, "turn": turn.audit_metadata()}
        return {
            "reply": "",
            "cancelled": True,
            "turn": {"commit_state": turn.barrier.state},
        }
    if creator_authority:
        async with mind_lock:
            if not turn.allow_work():
                return {"cancelled": True, "turn": turn.audit_metadata()}
            obs = _observe()
            if not turn.allow_work():
                return {"cancelled": True, "turn": turn.audit_metadata()}
            mind.perceive(obs)
        if not turn.allow_work():
            return {"cancelled": True, "turn": turn.audit_metadata()}
        if not activity_recorded:
            mind.note_initiative_user_activity(turn.scope_key)
        situation = situation_hint or obs.window_title or ""
        kwargs = {"on_token": on_token} if on_token is not None else {}
        if attachment_context:
            kwargs["attachment_context"] = attachment_context
        kwargs.update({
            "image_desc": image_desc,
            "private_context": private_context,
        })
    else:
        situation = ""
        kwargs = {}
        if _trusted_perception is not None:
            kwargs["_trusted_perception"] = _trusted_perception
        if _persist_verified_discord_memory:
            kwargs["_persist_verified_discord_memory"] = True
            kwargs["_persist_verified_discord_history"] = bool(
                _persist_verified_discord_history
            )
            kwargs["_verified_discord_memory_text"] = _verified_discord_memory_text
    result = await asyncio.to_thread(
        mind.chat,
        user_text,
        situation=situation,
        reply_tier=reply_tier,
        turn=turn,
        **kwargs,
    )
    if result.get("cancelled"):
        return result
    return _repair_echo_reply(user_text, result, turn=turn)


def _consume_late_turn(task: "asyncio.Task") -> None:
    """Observe a shielded worker's result so it cannot become an unhandled task."""
    try:
        task.result()
    except (asyncio.CancelledError, Exception):
        pass


def _finish_late_ws_chat_turn(task: "asyncio.Task") -> None:
    """Release foreground priority only after a timed-out worker really exits."""
    global active_chat_turns
    _consume_late_turn(task)
    active_chat_turns = max(0, active_chat_turns - 1)
    _sync_optional_work_foreground()


async def _ws_chat_turn_with_timeout(user_text: str, image_desc: str | None = None,
                                     attachment_context: str = "",
                                     situation_hint: str = "",
                                     reply_tier: str = "reason",
                                     on_token=None,
                                     activity_recorded: bool = False,
                                      turn: turn_context_mod.TurnContext | None = None,
                                      private_context: bool = False,
                                      _trusted_perception: object | None = None,
                                      _persist_verified_discord_memory: bool = False,
                                      _persist_verified_discord_history: bool = False,
                                      _verified_discord_memory_text: str = "") -> dict:
    global active_chat_turns, last_chat_turn_started
    turn = turn or turn_context_mod.TurnContext.create(
        _server_conversation_id("creator", "direct"),
        principal="creator",
        surface="direct",
    )
    active_chat_turns += 1
    _sync_optional_work_foreground()
    last_chat_turn_started = _time.time()
    attachment_kwargs = (
        {"attachment_context": attachment_context}
        if attachment_context else {}
    )
    worker = asyncio.create_task(
        _locked_ws_chat_turn(
            turn,
            user_text,
            image_desc=image_desc,
            private_context=private_context,
            situation_hint=situation_hint,
            reply_tier=reply_tier,
            on_token=on_token,
            activity_recorded=activity_recorded,
            _trusted_perception=_trusted_perception,
            _persist_verified_discord_memory=_persist_verified_discord_memory,
            _persist_verified_discord_history=_persist_verified_discord_history,
            _verified_discord_memory_text=_verified_discord_memory_text,
            **attachment_kwargs,
        )
    )
    release_priority_on_exit = True
    try:
        result = await asyncio.wait_for(
            asyncio.shield(worker), timeout=WS_CHAT_REPLY_TIMEOUT_SECONDS,
        )
        if not result.get("cancelled") and str(result.get("reply") or "").strip():
            _record_chat_stall_learning(safe=True)
        return result
    except asyncio.TimeoutError:
        turn.cancel("timeout")
        release_priority_on_exit = False
        worker.add_done_callback(_finish_late_ws_chat_turn)
        _record_chat_stall_learning(safe=False)
        return _ws_chat_timeout_result(user_text, turn=turn)
    except asyncio.CancelledError:
        turn.cancel("cancelled")
        release_priority_on_exit = False
        worker.add_done_callback(_finish_late_ws_chat_turn)
        raise
    finally:
        if release_priority_on_exit:
            active_chat_turns = max(0, active_chat_turns - 1)
            # Keep the short quiet grace period authoritative after the turn ends.
            _sync_optional_work_foreground()


async def _pump_reply_tokens(socket: WebSocket, q: "asyncio.Queue",
                             request_id: str, source: str,
                             turn: turn_context_mod.TurnContext) -> None:
    """Forward streamed reply tokens to one client until the None sentinel.
    Send errors just end the pump -- a vanished client shouldn't take the
    chat turn (or the server) down with it."""
    while True:
        tok = await q.get()
        if tok is None:
            return
        sent = await _send_ws_json(
            socket,
            {"type": "reply_token", "request_id": request_id,
             "source": source, "token": tok},
            turn=turn,
        )
        if not sent:
            return


def _player_chat_priority_active() -> bool:
    return active_chat_turns > 0 or (_time.time() - last_chat_turn_started) < CHAT_PRIORITY_QUIET_SECONDS


def _sync_optional_work_foreground() -> None:
    """Reflect current chat/TTS pressure into the optional-work coordinator."""
    _optional_work_coordinator.set_foreground(
        chat_active=_player_chat_priority_active(),
        tts_active=active_tts_requests > 0,
    )


def _optional_work_telemetry() -> dict:
    """Return a compact status view without exposing coordinator internals."""
    snapshot = _optional_work_coordinator.snapshot()
    recent = _optional_work_coordinator.telemetry()[-8:]
    return {
        "chat_active": snapshot["chat_active"],
        "tts_active": snapshot["tts_active"],
        "active": {
            "job_id": snapshot["active_job_id"],
            "category": snapshot["active_category"],
            "cancelled": snapshot["active_cancelled"],
        },
        "recent": [
            {
                "event": item.event,
                "category": item.category,
                "detail": item.detail,
            }
            for item in recent
        ],
    }


def _optional_work_deferred(result: object) -> bool:
    return isinstance(result, dict) and result.get("status") == "deferred"


def _optional_work_noncompletion(result: object) -> bool:
    """Whether optional work must not advance a schedule or emit completion UI."""
    return (
        isinstance(result, dict)
        and result.get("status") in {"deferred", "cancelled", "cancel_requested"}
    )


def _worker_reported_cancellation(result: object) -> bool:
    """Recognize the compact result shape used by cooperative maintenance work."""
    return isinstance(result, dict) and (
        result.get("cancelled") is True or result.get("status") == "cancelled"
    )


def _optional_cancellation_result(
    status: str,
    lease: resource_coordinator_mod.OptionalWorkLease,
    *,
    reason: str,
    result: object = None,
) -> dict:
    """Keep cancellation explicit without discarding bounded worker counters."""
    payload = dict(result) if isinstance(result, dict) else {}
    payload.update({
        "status": status,
        "category": lease.category,
        "reason": reason,
    })
    return payload


def _host_pressure_optional_work_deferral(
    category: resource_coordinator_mod.OptionalCategory,
) -> dict | None:
    """Return a compact deferral only when cached host evidence explicitly asks for it."""
    try:
        snapshot = _host_resource_sampler.snapshot(force=False)
    except Exception:
        # Resource observation is advisory; unavailable evidence must not block work.
        return None
    if not isinstance(snapshot, Mapping):
        return None

    advisory = snapshot.get("advisory")
    if not isinstance(advisory, Mapping) or advisory.get("defer_optional_work") is not True:
        return None

    severity = advisory.get("severity")
    if not isinstance(severity, str):
        resource = advisory.get("resource")
        assessment = snapshot.get("assessment")
        for evidence in (resource, assessment):
            if isinstance(evidence, Mapping) and isinstance(evidence.get("severity"), str):
                severity = evidence["severity"]
                break
    if not isinstance(severity, str):
        severity = "unknown"

    raw_reasons = advisory.get("reasons")
    reasons = []
    if isinstance(raw_reasons, (list, tuple)):
        reasons = [
            reason.strip()[:80]
            for reason in raw_reasons
            if isinstance(reason, str) and reason.strip()
        ][:4]
    return {
        "status": "deferred",
        "reason": "host-pressure",
        "category": category,
        "advisory": {"severity": severity, "reasons": reasons},
    }


async def _release_optional_work_when_settled(
    coordinator: resource_coordinator_mod.ResourceCoordinator,
    lease: resource_coordinator_mod.OptionalWorkLease,
    settled: threading.Event,
) -> None:
    """Keep a timed-out worker's lease reserved until its thread really exits."""
    await asyncio.to_thread(settled.wait)
    coordinator.finish(lease)


async def _bounded_thread(label: str, fn, *args, timeout: float = 5.0, **kwargs):
    """Run background work without letting it hold the server's attention forever.

    `asyncio.to_thread` cannot kill a stuck worker thread, but timing out the
    await keeps the HTTP/WebSocket server responsive and records which autonomy
    step got too slow.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=max(0.2, float(timeout)),
        )
    except asyncio.TimeoutError:
        _mindscape_sync_status["last_status"] = "background_timeout"
        _mindscape_sync_status["last_error"] = f"{label} exceeded {timeout:.1f}s"
        return None


async def _optional_bounded_thread(
    category: resource_coordinator_mod.OptionalCategory,
    label: str,
    fn,
    *args,
    timeout: float = 5.0,
    cooperative: bool = False,
    **kwargs,
):
    """Run optional work through one lease while retaining bounded-thread behavior."""
    coordinator = _optional_work_coordinator
    host_pressure_deferral = _host_pressure_optional_work_deferral(category)
    if host_pressure_deferral is not None:
        return host_pressure_deferral
    _sync_optional_work_foreground()
    decision = coordinator.start(category)
    if not decision.accepted or decision.lease is None:
        return {
            "status": "deferred",
            "reason": decision.reason,
            "category": category,
        }

    lease = decision.lease
    settled = threading.Event()

    def guarded():
        try:
            if cooperative:
                call_kwargs = {**kwargs, "cancel_event": lease.cancellation_event}
                return fn(*args, **call_kwargs)
            return fn(*args, **kwargs)
        finally:
            settled.set()

    try:
        result = await _bounded_thread(label, guarded, timeout=timeout)
    except BaseException as exc:
        coordinator.fail(lease, exc)
        raise

    if settled.is_set():
        worker_cancelled = cooperative and _worker_reported_cancellation(result)
        if worker_cancelled and not lease.cancelled:
            # A safe worker only reports this after observing its injected event.
            coordinator.cancel(lease, "worker-cancelled")
        cancellation_requested = lease.cancelled
        coordinator.finish(lease)
        if worker_cancelled:
            return _optional_cancellation_result(
                "cancelled",
                lease,
                reason="worker-observed",
                result=result,
            )
        if cancellation_requested:
            return _optional_cancellation_result(
                "cancel_requested",
                lease,
                reason="foreground",
                result=result,
            )
    else:
        # `_bounded_thread` has already recorded its timeout and returned None.
        # Its native thread still runs, so retain the single-flight slot until it
        # reaches a safe natural exit.
        foreground_cancelled = lease.cancelled
        coordinator.cancel(lease, "timeout")
        asyncio.create_task(
            _release_optional_work_when_settled(coordinator, lease, settled)
        )
        return _optional_cancellation_result(
            "cancel_requested",
            lease,
            reason="foreground" if foreground_cancelled else "timeout",
        )
    return result


def _compact_mindpage_content_index_run(result: object) -> dict:
    """Keep app-visible maintenance state useful without retaining page content."""
    if result is None:
        return {"status": "timed_out"}
    if not isinstance(result, dict):
        return {"status": "completed"}
    compact = {"status": str(result.get("status") or "completed")[:40]}
    for key in ("scanned", "indexed", "errors", "pending"):
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            compact[key] = max(0, min(value, 1_000_000))
    return compact


def _compact_mindpage_tier_maintenance_run(result: object) -> dict:
    """Keep page-tier maintenance telemetry content-free and bounded."""
    if not isinstance(result, dict):
        return {"status": "completed" if result else "timed_out"}
    compact: dict[str, object] = {
        "status": "completed" if result.get("ran") else (
            "cancelled" if result.get("cancelled") else "skipped"
        )
    }
    for key in ("updated", "hot_to_warm", "warm_to_cold"):
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            compact[key] = max(0, min(value, 1_000_000))
    return compact


async def _maintain_mindpage_tiers(*, now: float | None = None):
    """Run bounded page aging only while the companion is idle."""
    scheduled_at = float(_time.time() if now is None else now)
    if _player_chat_priority_active():
        return {"status": "deferred", "reason": "chat-active", "category": "routine"}
    last_run = float(
        _background_autonomy_status.get("last_mindpage_tier_maintenance_at") or 0.0
    )
    elapsed = scheduled_at - last_run
    if last_run and elapsed < BACKGROUND_MINDPAGE_TIER_MAINTENANCE_INTERVAL:
        return {
            "status": "skipped",
            "reason": "interval",
            "next_in": round(BACKGROUND_MINDPAGE_TIER_MAINTENANCE_INTERVAL - elapsed, 3),
        }
    try:
        result = await _optional_bounded_thread(
            "routine",
            "mindpage_tier_maintenance",
            mindpage_mod.maintain_pages,
            min_interval_s=BACKGROUND_MINDPAGE_TIER_MAINTENANCE_INTERVAL,
            timeout=10.0,
            cooperative=True,
        )
    except Exception as exc:
        result = {"status": "error", "error": type(exc).__name__}
    if _optional_work_noncompletion(result):
        return result
    _background_autonomy_status["last_mindpage_tier_maintenance_at"] = scheduled_at
    _background_autonomy_status["last_mindpage_tier_maintenance_run"] = (
        _compact_mindpage_tier_maintenance_run(result)
    )
    return result


async def _maintain_mindpage_content_index(*, now: float | None = None):
    """Backfill a small legacy Mindpage index batch only when the companion is idle."""
    scheduled_at = float(_time.time() if now is None else now)
    if _player_chat_priority_active():
        return {"status": "deferred", "reason": "chat-active", "category": "backfill"}

    last_run = float(
        _background_autonomy_status.get("last_mindpage_content_index_backfill_at") or 0.0
    )
    elapsed = scheduled_at - last_run
    if last_run and elapsed < BACKGROUND_MINDPAGE_CONTENT_INDEX_INTERVAL:
        return {
            "status": "skipped",
            "reason": "interval",
            "next_in": round(BACKGROUND_MINDPAGE_CONTENT_INDEX_INTERVAL - elapsed, 3),
        }

    try:
        result = await _optional_bounded_thread(
            "backfill",
            "mindpage_content_index_backfill",
            mindpage_mod.backfill_content_index,
            batch=8,
            timeout=10.0,
            cooperative=True,
        )
    except Exception as exc:
        result = {"status": "error", "error": type(exc).__name__}

    if _optional_work_noncompletion(result):
        # A refused lease is not a run: leave the due timestamp untouched so it
        # is retried promptly once chat, TTS, or another optional job releases.
        return result

    _background_autonomy_status["last_mindpage_content_index_backfill_at"] = scheduled_at
    _background_autonomy_status["last_mindpage_content_index_backfill_run"] = (
        _compact_mindpage_content_index_run(result)
    )
    return result


async def _state_thread(label: str, fn, *args, **kwargs):
    """Run state-mutating background work without orphaning a timed-out writer."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except Exception as exc:
        _mindscape_sync_status["last_status"] = "background_error"
        _mindscape_sync_status["last_error"] = f"{label} failed: {type(exc).__name__}: {exc}"
        return None


async def _warm_alpecca_voice(timeout: float | None = None) -> dict:
    """Warm BOTH of her real voices so the first spoken line is instant.

    The old version returned early when the F5 worker was healthy -- but
    tts.synth's auto mode routes calm, everyday speech to Kokoro, so the
    engine that serves the FIRST reply was exactly the one left cold (~40s
    lazy model load on the first synth). Now: probe F5 health AND always run
    one tiny Kokoro synth ("mm.") to pay the cold load up front, unless the
    configured backend can never reach Kokoro. Stays a background task; the
    server never waits on it."""
    from config import TTS_BACKEND, VOICE_WARMUP_TIMEOUT
    from alpecca import tts as tts_mod
    from alpecca import open_tts
    bound = float(timeout if timeout is not None else VOICE_WARMUP_TIMEOUT)
    engines: dict = {"f5": False, "kokoro": False}
    error = ""
    try:
        worker = await asyncio.wait_for(
            asyncio.to_thread(open_tts._worker_health, 1.2),
            timeout=min(2.0, max(0.5, bound)),
        )
        if worker.get("ready"):
            engines["f5"] = True
            tts_mod._last_engine = "f5-tts-worker"
            tts_mod._last_error = ""
    except Exception:
        pass  # F5 absent/slow is fine; Kokoro warmup below is the point
    if TTS_BACKEND not in ("off", "browser", "none", "edge", "f5", "f5-tts", "open"):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(tts_mod._synth_kokoro, "mm.", mind.state),
                timeout=max(1.0, bound),
            )
            engines["kokoro"] = bool(result)
            if not result:
                error = getattr(tts_mod, "_last_error", "")
        except asyncio.TimeoutError:
            error = "kokoro warmup timed out"
            tts_mod._last_error = error
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            tts_mod._last_error = error
    ok = engines["f5"] or engines["kokoro"]
    engine = "f5-tts-worker" if engines["f5"] and not engines["kokoro"] else (
        "kokoro" if engines["kokoro"] else "")
    return {"ok": ok, "engine": engine, "engines": engines,
            "error": "" if ok else error}


def _mindscape_vault_transport_token() -> str:
    """Return the dedicated Vault Worker token without reporting its value."""
    global _mindscape_vault_token_cache
    if MINDSCAPE_VAULT_TOKEN:
        _mindscape_vault_status["transport_token_source"] = "environment"
        return MINDSCAPE_VAULT_TOKEN
    if not (MINDSCAPE_VAULT_ENABLED and MINDSCAPE_VAULT_URL):
        return ""
    if _mindscape_vault_token_cache:
        return _mindscape_vault_token_cache
    try:
        token, source = mindscape_vault_mod.load_or_create_transport_token()
    except mindscape_vault_mod.VaultError as exc:
        _mindscape_vault_status["transport_token_source"] = "unavailable"
        _mindscape_vault_status["last_error"] = type(exc).__name__
        return ""
    _mindscape_vault_token_cache = token
    _mindscape_vault_status["transport_token_source"] = source
    return token


def _mindscape_vault_configured() -> bool:
    return bool(MINDSCAPE_VAULT_ENABLED and MINDSCAPE_VAULT_URL and _mindscape_vault_transport_token())


def _continuity_journal_flush() -> dict:
    """Flush append-only continuity only while this process owns the fence."""
    cloud_url = str(MINDSCAPE_VAULT_URL or os.environ.get(
        "ALPECCA_MINDSCAPE_VAULT_URL", ""
    )).strip()
    token = str(MINDSCAPE_VAULT_TOKEN or os.environ.get(
        "ALPECCA_MINDSCAPE_VAULT_TOKEN", ""
    )).strip()
    lease = {
        "lease_id": os.environ.get("ALPECCA_CONTINUITY_LEASE_ID", "").strip(),
        "fencing_epoch": os.environ.get("ALPECCA_CONTINUITY_FENCING_EPOCH", "").strip(),
        "holder": os.environ.get("ALPECCA_CONTINUITY_LEASE_HOLDER", "").strip(),
    }
    if not cloud_url:
        return {"ok": False, "status": "not_configured"}
    try:
        recovery_key, _source = mindscape_vault_mod.load_or_create_encryption_key()
        if not token:
            token, _token_source = mindscape_vault_mod.load_or_create_transport_token()
    except mindscape_vault_mod.VaultError:
        return {"ok": False, "status": "credentials_unavailable"}
    return continuity_journal_mod.flush_pending(
        cloud_url,
        token,
        recovery_key,
        lease=lease,
        db_path=DB_PATH,
        timeout=min(10.0, max(2.0, float(MINDSCAPE_VAULT_SYNC_TIMEOUT))),
    )


def _legacy_mindscape_sync_configured() -> bool:
    """Keep the old plaintext mirror dormant once Vault is configured."""
    return bool(MINDSCAPE_ENABLED and MINDSCAPE_CLOUD_URL and not _mindscape_vault_configured())


def _mindscape_vault_status_view() -> dict:
    status = dict(_mindscape_vault_status)
    status["enabled"] = bool(MINDSCAPE_VAULT_ENABLED)
    status["configured"] = _mindscape_vault_configured()
    status["ready_for_auto_sync"] = bool(
        status["configured"] and float(MINDSCAPE_VAULT_AUTO_SYNC_INTERVAL or 0) > 0
    )
    try:
        local = mindscape_vault_mod.local_status(DB_PATH)
    except Exception as exc:
        status["local_status"] = {"status": "unavailable", "error": type(exc).__name__}
    else:
        status["local_status"] = {
            name: local[name]
            for name in (
                "next_sequence", "last_success_sequence", "last_success_ts",
                "last_archive_ts", "pending_snapshots", "pending_archives",
            )
        }
    return status


def _mindscape_sync_status_view() -> dict:
    d = dict(_mindscape_sync_status)
    d["ready_for_auto_sync"] = bool(
        _legacy_mindscape_sync_configured() and d["auto_interval"] > 0
    )
    d["active_cloud_target"] = "vault" if _mindscape_vault_configured() else (
        "legacy" if _legacy_mindscape_sync_configured() else "none"
    )
    d["vault"] = _mindscape_vault_status_view()
    return d


async def _mindscape_vault_thread(label: str, fn, *args, timeout: float, **kwargs):
    """Bound Vault work without overwriting the legacy sync status on timeout."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=max(0.2, float(timeout)),
        )
    except asyncio.TimeoutError:
        _mindscape_vault_status["last_status"] = "background_timeout"
        _mindscape_vault_status["last_error"] = f"{label} exceeded {timeout:.1f}s"
        return None
    except Exception as exc:
        _mindscape_vault_status["last_status"] = "background_error"
        _mindscape_vault_status["last_error"] = f"{label}: {type(exc).__name__}"
        return None


def _mindscape_vault_mirror_snapshot(snap: dict) -> dict:
    _mindscape_vault_status["attempts"] += 1
    _mindscape_vault_status["last_attempt"] = _time.time()
    try:
        recovery_key, _key_source = mindscape_vault_mod.load_or_create_encryption_key()
        transport_token = _mindscape_vault_transport_token()
        if not transport_token:
            raise mindscape_vault_mod.VaultError("vault transport token is unavailable")
        result = mindscape_vault_mod.sync_snapshot(
            snap,
            MINDSCAPE_VAULT_URL,
            transport_token,
            recovery_key,
            db_path=DB_PATH,
            timeout=MINDSCAPE_VAULT_SYNC_TIMEOUT,
        )
    except mindscape_vault_mod.VaultError as exc:
        result = {"ok": False, "status": "vault_key_error", "message": type(exc).__name__}
    _mindscape_vault_status["last_status"] = str(result.get("status") or "unknown")
    _mindscape_vault_status["last_error"] = "" if result.get("ok") else str(result.get("status") or "failed")
    if result.get("ok"):
        _mindscape_vault_status["successes"] += 1
        _mindscape_vault_status["last_success"] = _time.time()
    return result


async def _mindscape_vault_sync_once(reason: str = "manual", check_models: bool = False) -> dict:
    if not _mindscape_vault_configured():
        _mindscape_vault_status["last_status"] = "not_configured"
        _mindscape_vault_status["last_error"] = ""
        return {"ok": False, "status": "not_configured"}
    if reason not in {"manual", "shutdown"} and _player_chat_priority_active():
        _mindscape_vault_status["last_status"] = "deferred_for_chat"
        _mindscape_vault_status["last_error"] = ""
        return {"ok": False, "status": "deferred_for_chat"}
    try:
        async with mind_lock:
            snap = await asyncio.wait_for(
                asyncio.to_thread(_mindscape_snapshot, check_models),
                timeout=BACKGROUND_MINDSCAPE_TIMEOUT,
            )
    except asyncio.TimeoutError:
        _mindscape_vault_status["last_status"] = "snapshot_timeout"
        _mindscape_vault_status["last_error"] = "snapshot_timeout"
        return {"ok": False, "status": "snapshot_timeout"}
    except Exception as exc:
        _mindscape_vault_status["last_status"] = "snapshot_error"
        _mindscape_vault_status["last_error"] = type(exc).__name__
        return {"ok": False, "status": "snapshot_error"}
    result = await _mindscape_vault_thread(
        "mindscape_vault_sync",
        _mindscape_vault_mirror_snapshot,
        snap,
        timeout=max(BACKGROUND_MINDSCAPE_TIMEOUT, float(MINDSCAPE_VAULT_SYNC_TIMEOUT) + 2.0),
    )
    return result or {"ok": False, "status": "mirror_timeout"}


def _mindscape_vault_archive() -> dict:
    _mindscape_vault_status["last_archive_attempt"] = _time.time()
    try:
        recovery_key, _key_source = mindscape_vault_mod.load_or_create_encryption_key()
        transport_token = _mindscape_vault_transport_token()
        if not transport_token:
            raise mindscape_vault_mod.VaultError("vault transport token is unavailable")
        if mindscape_vault_mod.archive_due(MINDSCAPE_VAULT_ARCHIVE_INTERVAL, db_path=DB_PATH):
            mindscape_vault_mod.queue_database_archive(
                recovery_key,
                source_db=DB_PATH,
                state_db=DB_PATH,
                max_bytes=MINDSCAPE_VAULT_ARCHIVE_MAX_BYTES,
            )
        result = mindscape_vault_mod.flush_archives(
            MINDSCAPE_VAULT_URL,
            transport_token,
            state_db=DB_PATH,
            timeout=max(20.0, float(MINDSCAPE_VAULT_SYNC_TIMEOUT)),
            max_bytes=MINDSCAPE_VAULT_ARCHIVE_MAX_BYTES,
        )
    except mindscape_vault_mod.VaultError as exc:
        result = {"ok": False, "status": "vault_archive_error", "message": type(exc).__name__}
    _mindscape_vault_status["last_archive_status"] = str(result.get("status") or "unknown")
    if result.get("ok"):
        _mindscape_vault_status["last_archive_success"] = _time.time()
    return result


async def _mindscape_vault_archive_once(reason: str = "interval") -> dict:
    if not _mindscape_vault_configured():
        return {"ok": False, "status": "not_configured"}
    if reason != "manual" and _player_chat_priority_active():
        _mindscape_vault_status["last_archive_status"] = "deferred_for_chat"
        return {"ok": False, "status": "deferred_for_chat"}
    result = await _mindscape_vault_thread(
        "mindscape_vault_archive",
        _mindscape_vault_archive,
        timeout=120.0,
    )
    return result or {"ok": False, "status": "archive_timeout"}


def _mindscape_mirror_snapshot(snap: dict) -> dict:
    _mindscape_sync_status["attempts"] += 1
    _mindscape_sync_status["last_attempt"] = _time.time()
    mirror = mindscape_mod.mirror_snapshot(
        snap,
        MINDSCAPE_CLOUD_URL,
        token=MINDSCAPE_TOKEN,
        timeout=MINDSCAPE_SYNC_TIMEOUT,
    )
    _mindscape_sync_status["last_status"] = mirror.get("status", "unknown")
    _mindscape_sync_status["last_error"] = "" if mirror.get("ok") else mirror.get("message", "")
    if mirror.get("ok"):
        _mindscape_sync_status["successes"] += 1
        _mindscape_sync_status["last_success"] = _time.time()
    return mirror


async def _mindscape_sync_once(reason: str = "manual", check_models: bool = False) -> dict:
    if not _legacy_mindscape_sync_configured():
        _mindscape_sync_status["last_status"] = "not_configured"
        _mindscape_sync_status["last_error"] = ""
        return {"ok": False, "status": "not_configured"}
    if reason not in {"manual", "shutdown"} and _player_chat_priority_active():
        _mindscape_sync_status["last_status"] = "deferred_for_chat"
        _mindscape_sync_status["last_error"] = ""
        return {"ok": False, "status": "deferred_for_chat"}
    async with mind_lock:
        snap = await _bounded_thread(
            "mindscape_snapshot",
            _mindscape_snapshot,
            check_models,
            timeout=BACKGROUND_MINDSCAPE_TIMEOUT,
        )
    if not snap:
        return {"ok": False, "status": "snapshot_timeout"}
    _mindscape_sync_status["last_trigger_reason"] = reason
    mirror = await _bounded_thread(
        "mindscape_mirror",
        _mindscape_mirror_snapshot,
        snap,
        timeout=BACKGROUND_MINDSCAPE_TIMEOUT,
    )
    return mirror or {"ok": False, "status": "mirror_timeout"}


async def _mindscape_sync_after_chat(reason: str) -> None:
    """Run one coalesced event mirror after foreground chat becomes quiet."""
    global _mindscape_event_sync_task
    try:
        while _player_chat_priority_active():
            await asyncio.sleep(0.5)
        if _mindscape_vault_configured():
            await _mindscape_vault_sync_once(reason=reason, check_models=False)
        else:
            await _mindscape_sync_once(reason=reason, check_models=False)
    finally:
        if _mindscape_event_sync_task is asyncio.current_task():
            _mindscape_event_sync_task = None


def _mindscape_request_event_sync(reason: str, force: bool = False) -> bool:
    global _mindscape_event_sync_task
    vault_active = _mindscape_vault_configured()
    if not (vault_active or _legacy_mindscape_sync_configured()):
        return False
    now = _time.time()
    active_status = _mindscape_vault_status if vault_active else _mindscape_sync_status
    since = now - float(active_status.get("last_attempt") or 0)
    if not force and since < MINDSCAPE_EVENT_SYNC_MIN_INTERVAL:
        _mindscape_sync_status["event_skips"] += 1
        active_status["last_status"] = "event_sync_throttled"
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    _mindscape_sync_status["event_triggers"] += 1
    _mindscape_sync_status["last_trigger"] = now
    _mindscape_sync_status["last_trigger_reason"] = reason
    if _mindscape_event_sync_task is None or _mindscape_event_sync_task.done():
        _mindscape_event_sync_task = loop.create_task(
            _mindscape_sync_after_chat(reason),
        )
    else:
        _mindscape_sync_status["event_skips"] += 1
    return True


def _mindscape_restore_source(body: dict | None = None) -> dict:
    body = body or {}
    snap = body.get("snapshot") if isinstance(body, dict) else None
    if snap:
        preview = mindscape_mod.restore_preview(snap)
        if preview.get("ok"):
            preview["already_imported"] = bool(mindscape_mod.restore_seen(preview["fingerprint"]))
        return {"ok": preview["ok"], "source": "posted", "snapshot": snap, "preview": preview}
    if _mindscape_vault_configured():
        try:
            recovery_key, _key_source = mindscape_vault_mod.load_or_create_encryption_key()
            transport_token = _mindscape_vault_transport_token()
            if not transport_token:
                raise mindscape_vault_mod.VaultError("vault transport token is unavailable")
            fetched = mindscape_vault_mod.fetch_latest_snapshot(
                MINDSCAPE_VAULT_URL,
                transport_token,
                recovery_key,
                timeout=MINDSCAPE_VAULT_SYNC_TIMEOUT,
            )
        except mindscape_vault_mod.VaultError as exc:
            fetched = {"ok": False, "status": "vault_key_error", "message": type(exc).__name__}
        source_name = "vault_cloud"
    else:
        fetched = mindscape_mod.fetch_snapshot(
            MINDSCAPE_CLOUD_URL,
            token=MINDSCAPE_TOKEN,
            timeout=MINDSCAPE_SYNC_TIMEOUT,
        )
        source_name = "cloud"
    if not fetched.get("ok"):
        return {"ok": False, "source": source_name, "error": fetched}
    snap = fetched["snapshot"]
    preview = mindscape_mod.restore_preview(snap)
    if preview.get("ok"):
        preview["already_imported"] = bool(mindscape_mod.restore_seen(preview["fingerprint"]))
    return {"ok": True, "source": source_name, "snapshot": snap, "preview": preview}


def _mindscape_import_snapshot(snapshot: dict) -> dict:
    preview = mindscape_mod.restore_preview(snapshot)
    if not preview.get("ok"):
        return {"ok": False, "imported": {}, "preview": preview}
    prior = mindscape_mod.restore_seen(preview["fingerprint"])
    if prior:
        preview["already_imported"] = True
        return {"ok": True, "status": "already_imported", "imported": {
            "memories": 0, "journal": 0, "observations": 0,
            "chat_turns": 0, "intent": 0,
        }, "preview": preview, "prior": prior}
    imported = {
        "memories": 0,
        "journal": 0,
        "observations": 0,
        "chat_turns": 0,
        "intent": 0,
    }
    for m in (snapshot.get("memory") or {}).get("recent") or []:
        content = str(m.get("content", "")).strip()
        if not content:
            continue
        memory_store.remember_with_id(
            f"[Mindscape restore] {content}",
            kind=m.get("kind", "episodic"),
            salience=max(0.65, min(1.0, float(m.get("salience", 0.7) or 0.7))),
            source="mindscape_restore",
        )
        imported["memories"] += 1
    journal_data = snapshot.get("journal") or {}
    for q in journal_data.get("open_questions") or []:
        body = str(q.get("body", q if isinstance(q, str) else "")).strip()
        if body:
            journal_mod.ask(f"[Mindscape restore] {body}", mood=preview.get("mood", ""))
            imported["journal"] += 1
    for entry in journal_data.get("recent") or []:
        body = str(entry.get("body", "")).strip()
        if body:
            journal_mod.write(
                f"[Mindscape restore] {body}",
                kind=entry.get("kind", "note"),
                title=entry.get("title", ""),
                mood=entry.get("mood", preview.get("mood", "")),
                tags="mindscape_restore",
            )
            imported["journal"] += 1
    for obs in snapshot.get("observations") or []:
        content = str(obs.get("content", "")).strip()
        if content:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="mindscape_restore",
                room=obs.get("room", preview.get("location", "")),
                content=content,
                confidence=max(0.0, min(1.0, float(obs.get("confidence", 0.6) or 0.6))),
                privacy_class=obs.get("privacy_class", "local"),
                metadata={"restored_from_ts": snapshot.get("ts", 0), "original_source": obs.get("source", "")},
            ))
            imported["observations"] += 1
    for turn in snapshot.get("chat_turns") or []:
        user_text = str(turn.get("user_text", "")).strip()
        reply = str(turn.get("reply", "")).strip()
        if not user_text or not reply:
            continue
        cognition_mod.record_chat_turn(cognition_mod.ChatTurn(
            user_text=f"[Mindscape restore] {user_text}",
            reply=reply,
            room=turn.get("room", preview.get("location", "")),
            mood=turn.get("mood", preview.get("mood", "")),
            intent=turn.get("intent", "replying"),
            model_use=turn.get("model_use") if isinstance(turn.get("model_use"), dict) else {},
            memory_evidence=(
                turn.get("memory_evidence")
                if isinstance(turn.get("memory_evidence"), list) else []
            ),
            observation_id=None,
            privacy_class="personal",
        ))
        imported["chat_turns"] += 1
    intent = (snapshot.get("self") or {}).get("intent") or {}
    if intent.get("name"):
        cognition_mod.set_intent(cognition_mod.IntentState(
            name=intent.get("name", "waiting"),
            reason=f"Restored from Mindscape snapshot: {intent.get('reason', '')}",
            target=intent.get("target", preview.get("location", "")),
            confidence=0.7,
        ))
        imported["intent"] = 1
    memory_store.remember(
        f"Alpecca restored continuity from Mindscape snapshot at {snapshot.get('ts', 0)}.",
        kind="self_model",
        salience=0.8,
        source="mindscape_restore",
    )
    summary = (
        f"memories={imported['memories']} journal={imported['journal']} "
        f"observations={imported['observations']} "
        f"chat_turns={imported['chat_turns']} intent={imported['intent']}"
    )
    mindscape_mod.mark_restored(snapshot, source="mindscape_restore", summary_text=summary)
    preview["already_imported"] = False
    return {"ok": True, "status": "imported", "imported": imported, "preview": preview}


async def _run_routine(row: dict) -> dict:
    kind = str(row.get("kind") or "")
    name = str(row.get("name") or kind)
    if kind not in routines_mod.KINDS:
        return {
            "ok": False,
            "status": "error",
            "kind": kind,
            "result": {"error": f"unknown routine kind: {kind}"},
        }
    proactive_turn = _proactive_turn_context()
    evidence_key = f"{row.get('id', 'unknown')}:{routines_mod.run_key()}:{kind}"

    def budgeted_call(fn, *args, **kwargs):
        initiative = mind.reserve_initiative(
            event_kind="routine",
            evidence_key=evidence_key,
            scope_key=proactive_turn.scope_key,
            relevance=0.7,
            user_active=False,
            outreach=False,
        )
        if not initiative["allowed"]:
            return {
                "status": "deferred",
                "reason": "initiative_budget",
                "initiative": initiative,
            }
        value = fn(*args, **kwargs)
        if _worker_reported_cancellation(value):
            return {
                "status": "cancelled",
                "initiative": initiative,
                "value": value,
            }
        return {
            "status": "completed",
            "initiative": initiative,
            "value": value,
        }

    def embed_backfill_call(*, cancel_event=None):
        """Relay the coordinator lease into the one cancellable routine worker."""
        if cancel_event is not None and cancel_event.is_set():
            return {"cancelled": True}
        return budgeted_call(memory_store.backfill_embeddings, cancel_event=cancel_event)

    def morning_call():
        event = mind.compose_volunteer_event(
            "scheduled morning greeting",
            turn=proactive_turn,
        )
        if event.get("status") == "deferred":
            return {
                "status": "deferred",
                "reason": "initiative_budget",
                "initiative": event.get("initiative"),
            }
        return {
            "status": "completed",
            "initiative": event.get("initiative"),
            "value": event.get("text", ""),
        }

    if kind == "daily_recap":
        result = await _optional_bounded_thread(
            "routine", "routine_daily_recap", budgeted_call,
            mind.write_session_recap, timeout=20.0,
        )
    elif kind == "consolidate_observations":
        result = await _optional_bounded_thread(
            "routine", "routine_consolidate", budgeted_call,
            mind.consolidate_observations, 16, timeout=12.0,
        )
    elif kind == "embed_backfill":
        result = await _optional_bounded_thread(
            "routine", "routine_embed_backfill", embed_backfill_call,
            timeout=10.0, cooperative=True,
        )
    elif kind == "vacuum":
        result = await _optional_bounded_thread(
            "routine", "routine_vacuum", budgeted_call,
            mindpage_mod.vacuum, timeout=20.0,
        )
    elif kind == "morning_greeting":
        result = await _optional_bounded_thread(
            "routine",
            "routine_morning_greeting",
            morning_call,
            timeout=BACKGROUND_VOLUNTEER_TIMEOUT,
        )
    if _optional_work_noncompletion(result):
        return {
            "ok": True,
            "status": str(result.get("status") or "deferred"),
            "kind": kind,
            "result": result,
            "initiative": (
                result.get("initiative") if isinstance(result, dict) else None
            ),
        }
    initiative = None
    if isinstance(result, dict) and result.get("status") == "completed":
        initiative = result.get("initiative")
        result = result.get("value")
    if kind == "morning_greeting":
        delivery = await _deliver_proactive_once(str(result or ""), initiative)
        if delivery.get("delivered"):
            await asyncio.to_thread(
                mind.record_proactive_delivery,
                str(result or ""),
                turn=proactive_turn,
            )
        elif not delivery.get("queued"):
            return {
                "ok": True,
                "status": "deferred",
                "kind": kind,
                "reason": "delivery_unavailable",
                "initiative": initiative,
                "delivery": delivery,
            }
    cognition_mod.record_observation(cognition_mod.CognitionObservation(
        source="routine",
        room=getattr(mind, "_location", ""),
        content=f"Routine ran: {name} ({kind}).",
        confidence=0.85,
        privacy_class="local",
        metadata={"routine_id": row.get("id"), "kind": kind, "result": str(result)[:700]},
    ))
    return {
        "ok": not (isinstance(result, dict) and result.get("error")),
        "status": "ok",
        "kind": kind,
        "result": result,
        "initiative": initiative,
    }


async def _run_due_routines_once() -> None:
    """Resolve atomic routine claims without consuming deferred or failed work."""
    if not AutomationCfg.ROUTINES:
        return
    for row, claim in routines_mod.claim_due():
        try:
            result = await _run_routine(row)
        except Exception as exc:
            result = {
                "ok": False,
                "status": "error",
                "kind": str(row.get("kind") or ""),
                "result": {"error": type(exc).__name__},
            }
        if _optional_work_noncompletion(result):
            # A deferred coordinator lease or cooperative cancellation did not
            # execute the occurrence. Return it to the current-hour queue.
            routines_mod.release(claim)
            continue
        if bool(isinstance(result, dict) and result.get("ok")):
            if routines_mod.complete(claim):
                await _broadcast({
                    "type": "activity",
                    "text": f"routine '{row.get('name')}' ran: {result.get('status', 'ok')}",
                })
            continue
        # Failures are retryable with ledger-owned capped exponential backoff.
        # Only a terminal failure consumes the current schedule occurrence.
        failure = routines_mod.fail(
            claim,
            error=(result.get("result") if isinstance(result, dict) else "routine_error"),
        )
        if failure.get("terminal"):
            await _broadcast({
                "type": "activity",
                "text": f"routine '{row.get('name')}' reached its retry limit",
            })


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Launch the ambient mood-drift loop on startup and cancel it on shutdown.

    Every few seconds Alpecca takes in a fresh observation and lets it move its
    mood, so when you come back it has genuinely been somewhere -- maybe it grew
    tender while you ground through an error, or settled while you were away.
    We keep a reference to the task so it isn't silently garbage-collected.
    """
    _behavior_trial_recovery_ready.clear()
    _capability_lease_recovery_ready.clear()
    try:
        await asyncio.to_thread(_capability_lease_store.recover_active)
    except Exception:
        # Sensor/file grants remain unavailable until a later clean restart.
        # A storage failure must not make ordinary local chat unavailable.
        pass
    else:
        _capability_lease_recovery_ready.set()
    # This durable maintenance is idempotent and stays outside `mind_lock`.
    # It closes only already-due response windows; it starts no trial or send.
    await _expire_due_qualified_response_outcomes_once()
    if _behavior_trial_profile_ready.is_set():
        try:
            recovered_trials = await asyncio.to_thread(
                _run_behavior_trial_transition,
                behavior_trial_controller.recover_interrupted,
            )
        except Exception:
            # Recovery is retried on the next process start. It never starts or
            # executes a behavior trial and must not block local startup.
            pass
        else:
            _behavior_trial_recovery_ready.set()
            if recovered_trials:
                try:
                    cognition_mod.record_observation(cognition_mod.CognitionObservation(
                        source="behavior_trial_recovery",
                        content=(
                            f"Closed {len(recovered_trials)} interrupted behavior trial(s) "
                            "without starting or executing a trial."
                        ),
                        confidence=1.0,
                        privacy_class="local",
                        metadata={
                            "trial_count": len(recovered_trials),
                            "trial_ids": [int(row["id"]) for row in recovered_trials],
                        },
                    ))
                except Exception:
                    # Recovery already succeeded; failure to record its evidence
                    # must not reactivate or leave an override unclosed.
                    pass
            await _settle_closed_behavior_trials_once()
            await _reconcile_behavior_trial_candidate_once()

    try:
        recovered = await asyncio.to_thread(
            commitments_mod.recover_running_commitments,
            scope=CREATOR_COMMITMENT_SCOPE,
        )
        if recovered:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="commitment_recovery",
                content=(
                    f"Closed {len(recovered)} interrupted commitment execution(s) "
                    "without rerunning their tools."
                ),
                confidence=1.0,
                privacy_class="local",
                metadata={
                    "commitment_ids": [int(row["id"]) for row in recovered[:20]],
                    "terminal_state": commitments_mod.CANCELLED,
                },
            ))
    except Exception:
        # Startup recovery is retried on the next process start. It never runs
        # a tool and must not prevent the local companion from opening.
        pass

    try:
        await asyncio.to_thread(
            capabilities_mod.record_snapshot,
            source="server_start",
        )
    except Exception:
        # Capability reporting is evidence, not a startup dependency. The
        # public snapshot route still reports the code-owned state if the DB is
        # temporarily unavailable.
        pass

    def drift_tick():
        mind.see(screen_sight.latest)
        mind.perceive(_observe())
        # She may wander to whichever room of her home is calling her strongest
        # right now -- grounded movement, the same way her mood drifts.
        roamed = mind.maybe_roam()
        # Preserve the typed source through delivery. Only a chatter candidate
        # may request a qualified-response outcome exposure.
        candidate = mind.volunteer_candidate()
        # If she has nothing to say, the quiet may still be hers to use.
        reflect_now = (candidate is None) and mind.reflection_due()
        return roamed, candidate, reflect_now

    async def loop() -> None:
        last_living_tick = 0.0
        while True:
            await asyncio.sleep(DRIFT_INTERVAL)
            try:
                # Outcome maintenance is independent of speech eligibility and
                # deliberately runs outside `mind_lock`.
                await _expire_due_qualified_response_outcomes_once()
                # This is independent of speech eligibility and stays outside
                # `mind_lock`, so a due rollback cannot queue behind chat.
                await _expire_due_behavior_trials_once()
                # A settlement is possible only after the controller has
                # durably restored the baseline and outcome windows are closed.
                await _settle_closed_behavior_trials_once()
                _background_autonomy_status["tick_count"] = int(_background_autonomy_status.get("tick_count") or 0) + 1
                _background_autonomy_status["last_drift_at"] = _time.time()
                async with mind_lock:
                    drift = await _state_thread(
                        "drift_tick",
                        drift_tick,
                    )
                    if not drift:
                        continue
                    roamed, candidate, reflect_now = drift
                    now = _time.time()
                    living_due = (
                        candidate is None
                        and now - last_living_tick >= BACKGROUND_LIVING_INTERVAL
                    )
                    if living_due:
                        last_living_tick = now
                if roamed:
                    # Let any open home view follow her from room to room, and
                    # show it in the activity ticker so her wandering is visible.
                    await _broadcast({"type": "roamed", "location": roamed,
                                      "home": mind.home_state()})
                    await _broadcast({"type": "activity",
                                      "text": f"she drifted into the {roamed}"})
                chat_priority = _player_chat_priority_active()
                now = _time.time()
                if (not chat_priority and EMBED_BACKFILL
                        and now - float(_background_autonomy_status.get("last_backfill_at") or 0.0)
                        >= BACKGROUND_EMBED_BACKFILL_INTERVAL):
                    backfill = await _optional_bounded_thread(
                        "backfill",
                        "memory_backfill",
                        memory_store.backfill_embeddings,
                        timeout=8.0,
                        cooperative=True,
                    )
                    if not _optional_work_noncompletion(backfill):
                        _background_autonomy_status["last_backfill_at"] = now
                    if isinstance(backfill, dict) and not _optional_work_noncompletion(backfill):
                        _background_autonomy_status["last_backfill_run"] = backfill
                        if int(backfill.get("updated") or 0) > 0:
                            await _broadcast({
                                "type": "activity",
                                "text": (
                                    f"memory backfill refreshed {backfill.get('updated', 0)} "
                                    "memories with embeddings"
                                ),
                            })
                # Content-index maintenance is deliberately silent. It uses the
                # same optional-work slot as embedding backfill, never holds
                # `mind_lock`, and retries as soon as a deferred idle window ends.
                await _maintain_mindpage_content_index(now=now)
                await _maintain_mindpage_tiers(now=now)
                if chat_priority:
                    reflect_now = False
                    living_due = False
                    candidate = None
                if reflect_now:
                    # Off the lock: her Soul drives one self-directed act (reflect,
                    # self-improve, or recursive self-question) -- slow, entirely
                    # hers, and chat must never queue behind it. Its note (if any)
                    # goes to the activity ticker so you can watch her stir.
                    reflection_turn = _proactive_turn_context()
                    res = await _optional_bounded_thread(
                        "reflection",
                        "idle_self_direct",
                        mind.idle_self_direct,
                        initiative_scope=reflection_turn.scope_key,
                        timeout=BACKGROUND_REFLECT_TIMEOUT,
                    )
                    if res and res.get("note"):
                        await _broadcast({"type": "activity", "text": res["note"]})
                    # Now and then she entertains herself -- opens a game for fun,
                    # of her own accord (charter: supervised entertainment). Rare
                    # so she doesn't keep popping windows.
                    import random as _rnd
                    if res and not res.get("deferred") and _rnd.random() < 0.05:
                        played = await _bounded_thread(
                            "entertain",
                            mind.entertain,
                            timeout=BACKGROUND_DELIVERY_TIMEOUT,
                        )
                        if played and played.get("note"):
                            await _broadcast({"type": "activity", "text": played["note"]})
                if living_due:
                    living_turn = _proactive_turn_context()
                    living = await _bounded_thread(
                        "living_world_tick",
                        mind.living_world_tick,
                        "background",
                        _living_systems_context(False),
                        initiative_scope=living_turn.scope_key,
                        timeout=BACKGROUND_LIVING_TIMEOUT,
                    )
                    if living and not living.get("deferred"):
                        _remember_living_result(living, counted=True)
                    if living and (living.get("activated_system") or {}).get("warmup_requested"):
                        warm = await _warm_alpecca_voice(timeout=6.0)
                        living["activated_system"]["warmup"] = warm
                    if living and living.get("line"):
                        await _broadcast({
                            "type": "living_loop",
                            "text": living["line"],
                            "living_loop": living,
                            "cognition": mind.cognition_state(),
                        })
                if candidate is not None:
                    from alpecca import openclaw_bridge
                    from config import OpenClaw as OpenClawCfg
                    reachable = bool(ws_clients) or (
                        OpenClawCfg.ENABLED and OpenClawCfg.DEFAULT_TARGET)
                    if reachable:
                        # Compose outside the lock -- the LLM call can take
                        # seconds and chat shouldn't stall behind her musing.
                        proactive_turn = _proactive_turn_context()
                        event = await _bounded_thread(
                            "compose_volunteer",
                            mind.compose_volunteer_event,
                            candidate.reason,
                            turn=proactive_turn,
                            timeout=BACKGROUND_VOLUNTEER_TIMEOUT,
                        )
                        text = str((event or {}).get("text") or "")
                        if text:
                            delivery = await _deliver_proactive_once(
                                text,
                                (event or {}).get("initiative"),
                                proactive_turn=proactive_turn,
                                outcome_candidate=candidate,
                            )
                            if delivery.get("delivered"):
                                await asyncio.to_thread(
                                    mind.record_proactive_delivery,
                                    text,
                                    turn=proactive_turn,
                                )
                # Retry any outbound messages a transient channel hiccup dropped,
                # so her words actually reach the person. Cheap when the queue's
                # empty (no subprocess), and off-thread so chat never stalls.
                try:
                    from alpecca import openclaw_bridge as _ocb
                    if not ws_clients and _ocb.pending_count():
                        await _bounded_thread(
                            "openclaw_flush",
                            _ocb.flush,
                            timeout=BACKGROUND_DELIVERY_TIMEOUT,
                        )
                except Exception:
                    pass
            except Exception:
                import traceback
                _background_autonomy_status["last_error"] = traceback.format_exc()[-1000:]
                pass  # never let a bad tick kill the companion

    async def mindscape_loop() -> None:
        while True:
            if _mindscape_vault_configured() and MINDSCAPE_VAULT_AUTO_SYNC_INTERVAL > 0:
                interval = max(30.0, float(MINDSCAPE_VAULT_AUTO_SYNC_INTERVAL))
            elif _legacy_mindscape_sync_configured() and MINDSCAPE_AUTO_SYNC_INTERVAL > 0:
                interval = max(30.0, float(MINDSCAPE_AUTO_SYNC_INTERVAL))
            else:
                interval = 30.0
            await asyncio.sleep(interval)
            try:
                if _mindscape_vault_configured() and MINDSCAPE_VAULT_AUTO_SYNC_INTERVAL > 0:
                    mirror = await _mindscape_vault_sync_once(reason="interval", check_models=False)
                    if mindscape_vault_mod.archive_due(MINDSCAPE_VAULT_ARCHIVE_INTERVAL, db_path=DB_PATH):
                        await _mindscape_vault_archive_once(reason="interval")
                elif _legacy_mindscape_sync_configured() and MINDSCAPE_AUTO_SYNC_INTERVAL > 0:
                    mirror = await _mindscape_sync_once(reason="interval", check_models=False)
                else:
                    continue
                if mirror.get("status") == "deferred_for_chat":
                    continue
                await _broadcast({
                    "type": "activity",
                    "text": (
                        "Mindscape Vault continuity mirrored online."
                        if mirror.get("ok")
                        else f"Mindscape continuity sync failed: {mirror.get('status', 'failed')}"
                    ),
                })
            except Exception as exc:
                if _mindscape_vault_configured():
                    _mindscape_vault_status["last_attempt"] = _time.time()
                    _mindscape_vault_status["last_status"] = "auto_sync_error"
                    _mindscape_vault_status["last_error"] = type(exc).__name__
                else:
                    _mindscape_sync_status["last_attempt"] = _time.time()
                    _mindscape_sync_status["last_status"] = "auto_sync_error"
                    _mindscape_sync_status["last_error"] = f"{type(exc).__name__}: {exc}"

    async def continuity_journal_loop() -> None:
        while True:
            await asyncio.sleep(10.0)
            if _player_chat_priority_active():
                continue
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(_continuity_journal_flush), timeout=12.0
                )
            except Exception:
                # The durable local outbox remains pending for the next tick.
                pass

    async def automation_loop() -> None:
        routines_mod.init_db()
        watcher = watchers_mod.DirectoryWatcher(
            watchers_mod.parse_watch_dirs(AutomationCfg.WATCH_DIRS),
            max_files=AutomationCfg.WATCH_MAX_FILES,
        )
        last_watch = 0.0
        while True:
            await asyncio.sleep(max(10.0, float(AutomationCfg.ROUTINE_POLL_SECONDS or 60.0)))
            try:
                await _run_due_routines_once()
                now = _time.time()
                if (AutomationCfg.WATCH_DIRS
                        and now - last_watch >= max(10.0, float(AutomationCfg.WATCH_POLL_SECONDS or 60.0))):
                    last_watch = now
                    changes = watcher.poll()
                    if changes.get("changed"):
                        names = []
                        for key in ("added_names", "modified_names", "removed_names"):
                            names.extend(changes.get(key) or [])
                        content = (
                            "Watched folder changed: "
                            f"added={changes.get('added', 0)} modified={changes.get('modified', 0)} "
                            f"removed={changes.get('removed', 0)}; names={', '.join(names[:12])}"
                        )
                        cognition_mod.record_observation(cognition_mod.CognitionObservation(
                            source="watcher",
                            room=getattr(mind, "_location", ""),
                            content=content[:1000],
                            confidence=0.8,
                            privacy_class="local",
                            metadata={k: v for k, v in changes.items() if k != "changed"},
                        ))
                        await _broadcast({"type": "activity", "text": content[:240]})
            except Exception as exc:
                _background_autonomy_status["last_automation_error"] = f"{type(exc).__name__}: {exc}"

    task = asyncio.create_task(loop())
    mindscape_task = asyncio.create_task(mindscape_loop())
    continuity_journal_task = asyncio.create_task(continuity_journal_loop())
    automation_task = asyncio.create_task(automation_loop())
    from config import VOICE_WARMUP
    voice_warmup_task = (asyncio.create_task(_warm_alpecca_voice())
                         if VOICE_WARMUP else asyncio.create_task(asyncio.sleep(0)))
    try:
        yield
    finally:
        global _mindscape_event_sync_task
        task.cancel()
        mindscape_task.cancel()
        continuity_journal_task.cancel()
        automation_task.cancel()
        deferred_mindscape_task = _mindscape_event_sync_task
        _mindscape_event_sync_task = None
        if deferred_mindscape_task is not None:
            deferred_mindscape_task.cancel()
            await asyncio.gather(deferred_mindscape_task, return_exceptions=True)
        outcome_tasks = list(_initiative_outcome_tasks)
        for outcome_task in outcome_tasks:
            outcome_task.cancel()
        _initiative_outcome_tasks.clear()
        if outcome_tasks:
            await asyncio.gather(*outcome_tasks, return_exceptions=True)
        # Leave one grounded "where we left off" memory before she sleeps, so the
        # next session can pick up the thread instead of starting cold. Best-effort
        # and off the hot path -- a failure here must never block a clean shutdown.
        try:
            await _state_thread("session_recap", mind.write_session_recap)
            await asyncio.wait_for(
                asyncio.to_thread(_continuity_journal_flush), timeout=12.0
            )
        except Exception:
            pass
        try:
            if _mindscape_vault_configured():
                await _mindscape_vault_sync_once(reason="shutdown", check_models=False)
            else:
                await _mindscape_sync_once(reason="shutdown", check_models=False)
        except Exception:
            pass
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await mindscape_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await automation_task
        except (asyncio.CancelledError, Exception):
            pass
        if not voice_warmup_task.done():
            voice_warmup_task.cancel()
            try:
                await voice_warmup_task
            except (asyncio.CancelledError, Exception):
                pass
        voice_sensor.close()
        screen_sight.close()
        face_sense.close()


app = FastAPI(title="Alpecca", lifespan=lifespan)


# --- Authorization -----------------------------------------------------------
# Alpecca's public identity and server authorization are deliberately separate.
# The authorization secret is protected by Windows Credential Manager (or an
# explicit deployment secret), never placed in source, URLs, localStorage, or a
# browser-readable cookie.
from starlette.responses import JSONResponse as _JSON

_AUTH_SECRET = auth_mod.load_or_create_authorization_secret(HOME)
_DISCORD_BRIDGE_SECRET = auth_mod.load_or_create_bridge_authorization_secret(HOME)


class _SystemEgressClock:
    def now(self) -> float:
        return time.time()


_PERCEPTION_EGRESS_RUNTIME: dict[str, object] | None = None
_PERCEPTION_EGRESS_LOCK = threading.Lock()


def _configured_perception_egress_policy() -> egress_consent_mod.EgressPolicy:
    routes: list[egress_consent_mod.AllowedEgressRoute] = []
    if all(
        (
            VISION_CLOUD_MODEL,
            VISION_CLOUD_TRANSPORT_ROUTE,
            VISION_CLOUD_DEPLOYMENT,
            VISION_CLOUD_PROCESSING_LOCATION,
        )
    ):
        routes.append(
            egress_consent_mod.AllowedEgressRoute(
                route_id="vision-ollama-cloud",
                provider="ollama-cloud",
                deployment=VISION_CLOUD_DEPLOYMENT,
                model=VISION_CLOUD_MODEL,
                capability="private-image-description",
                purpose="describe-private-image",
                processing_location=VISION_CLOUD_PROCESSING_LOCATION,
                destination_class="managed-model-api",
                transport_route=VISION_CLOUD_TRANSPORT_ROUTE,
                ttl_seconds=60,
                max_uses=1,
                max_bytes_per_use=attachment_ingress_mod.DEFAULT_MAX_IMAGE_BYTES,
            )
        )
    if all(
        (
            ZEROGPU_VISION_TRANSPORT_ROUTE,
            ZEROGPU_VISION_DEPLOYMENT,
            ZEROGPU_VISION_MODEL,
            ZEROGPU_VISION_PROCESSING_LOCATION,
        )
    ):
        routes.append(
            egress_consent_mod.AllowedEgressRoute(
                route_id="vision-zerogpu",
                provider="zerogpu",
                deployment=ZEROGPU_VISION_DEPLOYMENT,
                model=ZEROGPU_VISION_MODEL,
                capability="private-image-description",
                purpose="describe-private-image",
                processing_location=ZEROGPU_VISION_PROCESSING_LOCATION,
                destination_class="hosted-space-gpu",
                transport_route=ZEROGPU_VISION_TRANSPORT_ROUTE,
                ttl_seconds=60,
                max_uses=1,
                max_bytes_per_use=attachment_ingress_mod.DEFAULT_MAX_IMAGE_BYTES,
            )
        )
    if not routes:
        raise RuntimeError("no exact private-perception egress route is configured")
    return egress_consent_mod.EgressPolicy(
        policy_id="private-perception-egress",
        version=1,
        routes=tuple(routes),
    )


def _perception_egress_runtime() -> dict[str, object]:
    global _PERCEPTION_EGRESS_RUNTIME
    with _PERCEPTION_EGRESS_LOCK:
        if _PERCEPTION_EGRESS_RUNTIME is None:
            authority = interactive_egress_mod.InteractiveCreatorAuthority(
                HOME / "perception_egress_requests.sqlite3"
            )
            seal_key = hashlib.sha256(
                _AUTH_SECRET + b"\x00perception-egress-ledger"
            ).digest()
            anchor_key = hashlib.sha256(
                _AUTH_SECRET + b"\x00perception-egress-anchor"
            ).digest()
            anchor = egress_consent_mod.SQLiteMonotonicAnchor(
                HOME / "perception_egress_anchor.sqlite3",
                anchor_key=anchor_key,
                anchor_key_version="auth-derived-v1",
            )
            ledger = egress_consent_mod.EgressConsentLedger(
                HOME / "perception_egress_ledger.sqlite3",
                seal_key=seal_key,
                seal_key_version="auth-derived-v1",
                authority=authority,
                policy=_configured_perception_egress_policy(),
                clock=_SystemEgressClock(),
                anchor=anchor,
            )
            _PERCEPTION_EGRESS_RUNTIME = {
                "authority": authority,
                "ledger": ledger,
                "gate": egress_consent_mod.PerceptionEgressGate(ledger),
            }
        return _PERCEPTION_EGRESS_RUNTIME
_DISCORD_ACTOR_STORE_LOCK = threading.Lock()
_DISCORD_ACTOR_STORE: (
    bridge_actor_identity_mod.BridgeActorIdentityStore | None
) = None
_NOTIFICATION_RUNTIME_LOCK = threading.Lock()
_NOTIFICATION_ACK_OPERATION_LOCK = threading.Lock()
_NOTIFICATION_RUNTIME: dict[str, object] | None = None
_NOTIFICATION_RUNTIME_MUTEX: notification_anchor_mod.CrossProcessMutex | None = None
_NOTIFICATION_TEST_OPERATION_MUTEX: (
    notification_anchor_mod.CrossProcessMutex | None
) = None

_NOTIFICATION_RUNTIME_MUTEX_NAME = "Local\\Alpecca.NotificationRuntimeInitialization"
_NOTIFICATION_TEST_OPERATION_MUTEX_NAME = (
    "Local\\Alpecca.NotificationConnectionTest"
)

_NOTIFICATION_OUTBOX_SEAL_TARGET = "Alpecca/NotificationOutboxSeal"
_NOTIFICATION_ANCHOR_KEY_TARGET = "Alpecca/NotificationAnchorSeal"
_NOTIFICATION_ANCHOR_STATE_TARGET = "Alpecca/NotificationAnchorState"
_NOTIFICATION_PUSH_STORE_KEY_TARGET = "Alpecca/NotificationPushStoreSeal"
_NOTIFICATION_PUSH_SUBSCRIPTIONS_TARGET = "Alpecca/NotificationPushSubscriptions"
_NOTIFICATION_PUSH_SUBSCRIPTIONS_ANCHOR_TARGET = (
    "Alpecca/NotificationPushSubscriptionsAnchor"
)
_NOTIFICATION_PUSH_ACK_ANCHOR_TARGET = "Alpecca/NotificationPushAckAnchor"
_NOTIFICATION_PUSH_VAPID_TARGET = "Alpecca/NotificationPushVapid"


class _DiscordActorStoreUnavailable(RuntimeError):
    """The lazy actor-identity store could not be constructed."""


def _discord_actor_store() -> bridge_actor_identity_mod.BridgeActorIdentityStore:
    """Load the dedicated actor seal and store only on first actor request."""
    global _DISCORD_ACTOR_STORE
    store = _DISCORD_ACTOR_STORE
    if store is not None:
        return store
    with _DISCORD_ACTOR_STORE_LOCK:
        store = _DISCORD_ACTOR_STORE
        if store is not None:
            return store
        try:
            seal_secret = auth_mod.load_or_create_bridge_actor_identity_seal_secret(
                HOME
            )
            store = bridge_actor_transport_mod.build_actor_store(HOME, seal_secret)
        except Exception as exc:
            raise _DiscordActorStoreUnavailable from exc
        _DISCORD_ACTOR_STORE = store
        return store


def _issue_discord_actor_envelope(
    request_body: bytes,
    bindings: bridge_actor_transport_mod.DiscordActorBindings,
) -> bridge_actor_identity_mod.BridgeActorEnvelope:
    return _discord_actor_store().issue_envelope(
        request_body=request_body,
        **bindings.as_store_kwargs(),
    )


def _verify_discord_actor_envelope(
    envelope: str,
    request_body: bytes,
    bindings: bridge_actor_transport_mod.DiscordActorBindings,
) -> bridge_actor_identity_mod.BridgeActorVerification:
    return _discord_actor_store().verify_and_consume(
        envelope,
        request_body=request_body,
        **bindings.as_store_kwargs(),
    )


class _NotificationRuntimeUnavailable(RuntimeError):
    """The private Phase 11 runtime could not be constructed."""


def _notification_credential(target: str, comment: str):
    return web_push_runtime_mod.WindowsCredentialRecord(target, comment=comment)


def _notification_runtime_mutex() -> notification_anchor_mod.CrossProcessMutex:
    global _NOTIFICATION_RUNTIME_MUTEX
    mutex = _NOTIFICATION_RUNTIME_MUTEX
    if mutex is not None:
        return mutex
    if os.name != "nt":
        raise _NotificationRuntimeUnavailable
    mutex = notification_anchor_mod.WindowsNamedMutex(
        _NOTIFICATION_RUNTIME_MUTEX_NAME
    )
    _NOTIFICATION_RUNTIME_MUTEX = mutex
    return mutex


def _notification_test_operation_mutex() -> notification_anchor_mod.CrossProcessMutex:
    global _NOTIFICATION_TEST_OPERATION_MUTEX
    mutex = _NOTIFICATION_TEST_OPERATION_MUTEX
    if mutex is not None:
        return mutex
    if os.name != "nt":
        raise _NotificationRuntimeUnavailable
    mutex = notification_anchor_mod.WindowsNamedMutex(
        _NOTIFICATION_TEST_OPERATION_MUTEX_NAME,
        timeout_ms=0,
    )
    _NOTIFICATION_TEST_OPERATION_MUTEX = mutex
    return mutex


def _notification_runtime() -> dict[str, object]:
    """Build the Windows-only app-push runtime lazily on a creator request."""
    global _NOTIFICATION_RUNTIME
    runtime = _NOTIFICATION_RUNTIME
    if runtime is not None:
        return runtime
    with _NOTIFICATION_RUNTIME_LOCK:
        runtime = _NOTIFICATION_RUNTIME
        if runtime is not None:
            return runtime
        try:
            if os.name != "nt" or importlib.util.find_spec("pywebpush") is None:
                raise _NotificationRuntimeUnavailable
            mutex = _notification_runtime_mutex()
            with mutex.locked(timeout_ms=30_000):
                runtime = _NOTIFICATION_RUNTIME
                if runtime is not None:
                    return runtime
                outbox_seal = web_push_runtime_mod.load_or_create_protected_secret(
                    _notification_credential(
                        _NOTIFICATION_OUTBOX_SEAL_TARGET,
                        "Alpecca notification outbox seal",
                    )
                )
                anchor_key = web_push_runtime_mod.load_or_create_protected_secret(
                    _notification_credential(
                        _NOTIFICATION_ANCHOR_KEY_TARGET,
                        "Alpecca notification anchor seal",
                    )
                )
                push_store_key = web_push_runtime_mod.load_or_create_protected_secret(
                    _notification_credential(
                        _NOTIFICATION_PUSH_STORE_KEY_TARGET,
                        "Alpecca private Web Push store seal",
                    )
                )
                anchor_backend = (
                    notification_anchor_mod.WindowsCredentialManagerBackend(
                        _NOTIFICATION_ANCHOR_STATE_TARGET
                    )
                )
                anchor = notification_anchor_mod.CredentialMonotonicAnchor(
                    anchor_backend,
                    anchor_key=anchor_key,
                )
                subscription_anchor = (
                    notification_anchor_mod.CredentialMonotonicAnchor(
                        notification_anchor_mod.WindowsCredentialManagerBackend(
                            _NOTIFICATION_PUSH_SUBSCRIPTIONS_ANCHOR_TARGET
                        ),
                        anchor_key=push_store_key,
                    )
                )
                ack_anchor = notification_anchor_mod.CredentialMonotonicAnchor(
                    notification_anchor_mod.WindowsCredentialManagerBackend(
                        _NOTIFICATION_PUSH_ACK_ANCHOR_TARGET
                    ),
                    anchor_key=push_store_key,
                )
                policy = notification_outbox_mod.OutboxPolicy(
                    policy_id="creator_app_push",
                    policy_version=1,
                    category_registry=frozenset({"connection_test"}),
                    adapter_registry=frozenset(
                        {web_push_adapter_mod.ADAPTER_NAME}
                    ),
                    category_quotas={"connection_test": 3},
                    channel_quotas={web_push_adapter_mod.ADAPTER_NAME: 3},
                    channel_costs={web_push_adapter_mod.ADAPTER_NAME: 0},
                    adapter_transport_idempotency={
                        web_push_adapter_mod.ADAPTER_NAME: False
                    },
                    max_attempts=2,
                    lease_seconds=30.0,
                    backoff_initial_seconds=60.0,
                    backoff_multiplier=2.0,
                    backoff_max_seconds=300.0,
                    quota_window_seconds=3600.0,
                    global_quota=3,
                    daily_cost_cap=0,
                    accounting_timezone="America/Los_Angeles",
                )
                outbox = notification_outbox_mod.NotificationOutbox(
                    HOME / "notification_outbox.sqlite3",
                    seal_key=outbox_seal,
                    policy=policy,
                    anchor=anchor,
                )
                store = web_push_runtime_mod.WebPushPrivateStore(
                    HOME / "notification_web_push.sqlite3",
                    subscription_record=_notification_credential(
                        _NOTIFICATION_PUSH_SUBSCRIPTIONS_TARGET,
                        "Alpecca private Web Push subscriptions",
                    ),
                    seal_key=push_store_key,
                    subscription_anchor=subscription_anchor,
                    ack_anchor=ack_anchor,
                )
                vapid = web_push_runtime_mod.load_or_create_vapid(
                    _notification_credential(
                        _NOTIFICATION_PUSH_VAPID_TARGET,
                        "Alpecca Web Push VAPID private key",
                    )
                )
                transport = web_push_runtime_mod.PyWebPushTransport(vapid)
                adapter = web_push_adapter_mod.WebPushAdapter(
                    outbox, store, transport
                )
                runtime = {
                    "outbox": outbox,
                    "store": store,
                    "vapid": vapid,
                    "adapter": adapter,
                }
                _NOTIFICATION_RUNTIME = runtime
        except Exception as exc:
            raise _NotificationRuntimeUnavailable from exc
        return runtime


_capability_lease_store = capability_leases_mod.CapabilityLeaseStore(
    DB_PATH,
    seal_key=_AUTH_SECRET,
)
# The controller is constructed before protected authorization initializes, so
# bind the already-loaded server secret as its approval seal before any request
# or lifespan recovery can use a behavior trial. This does not create or rotate
# a separate credential.
behavior_trial_controller.set_approval_seal_key(_AUTH_SECRET)
behavior_trial_candidate_store.set_seal_key(_AUTH_SECRET)
behavior_trial_review_decision_store.set_seal_key(_AUTH_SECRET)
behavior_trial_profile_store.set_seal_key(_AUTH_SECRET)
try:
    _loaded_behavior_profile = behavior_trial_profile_store.active_profile(
        behavior_trial_controller.default_chatter_chance
    )
    behavior_trial_controller.adopt_profile_chatter_chance(
        float(_loaded_behavior_profile["value"]),
        generation_token=_behavior_profile_generation(_loaded_behavior_profile),
    )
except Exception as exc:
    _behavior_trial_profile_error = type(exc).__name__
else:
    _behavior_trial_profile_error = ""
    _behavior_trial_profile_ready.set()
_CREATOR_PASSWORD = auth_mod.load_creator_password()
_TRUSTED_DEVICE_DAYS = max(
    1,
    min(365, int(os.environ.get("ALPECCA_TRUSTED_DEVICE_DAYS", "180"))),
)
_AUTHORITY = auth_mod.SessionAuthority(
    _AUTH_SECRET,
    session_ttl_s=_TRUSTED_DEVICE_DAYS * 24 * 60 * 60,
    creator_password=_CREATOR_PASSWORD,
    service_secrets={"discord-bridge": _DISCORD_BRIDGE_SECRET},
)
_TRUSTED_DEVICE_REGISTRY = trusted_devices_mod.TrustedDeviceRegistry(DB_PATH)
_RESTORE_APPROVAL_LEDGER = restore_approval_mod.RestoreApprovalLedger(DB_PATH)
_PAGEFILE_APPROVAL_LEDGER: pagefile_approval_mod.PagefileApprovalLedger | None = None
_PAGEFILE_APPROVAL_LEDGER_LOCK = threading.Lock()
_PUBLIC_AUTH_PATHS = frozenset({
    "/healthz",
    "/auth/status",
    "/auth/bootstrap",
    "/auth/bootstrap/exchange",
    "/auth/bootstrap/request",
    "/auth/password",
    "/auth/device/challenge",
    "/auth/device/exchange",
})
_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DISCORD_SERVICE_PATHS = frozenset({
    "/channel/discord",
    "/channel/discord/actor-envelope",
    "/channel/discord/autonomy",
})

def _access_html(
    next_path: str = "/",
    error: str = "",
    *,
    allow_password: bool = True,
) -> str:
    safe_next = html.escape(_safe_local_path(next_path), quote=True)
    error_html = (
        f'<div role="alert" style="color:#ffb8b8;font-size:13px;margin-bottom:12px">'
        f'{html.escape(error)}</div>'
        if error else ""
    )
    configured = _AUTHORITY.password_configured and allow_password
    form = f"""
  <form method="post" action="/auth/password" style="display:grid;gap:10px">
    <input type="hidden" name="next" value="{safe_next}">
    <label for="creator-password" style="text-align:left;color:#a9bad8;font-size:12px">Creator password</label>
    <input id="creator-password" name="password" type="password" required autocomplete="current-password"
      style="box-sizing:border-box;width:100%;padding:11px;border:1px solid #31415f;border-radius:6px;background:#0b1322;color:#eef6ff;font:inherit">
    <button type="submit" style="margin-top:4px;width:100%;padding:10px;border:0;border-radius:6px;background:#7fd9ff;color:#06121c;font-weight:650;cursor:pointer">Open Alpecca</button>
  </form>""" if configured else ""
    unavailable = "" if configured else (
        '<div style="color:#ffcf8f;font-size:13px">Remote creator sign-in requires '
        'an HTTPS address.</div>'
        if not allow_password else
        '<div style="color:#ffcf8f;font-size:13px">The creator password is not configured. '
        'Open Alpecca from the local launcher or configure the protected Windows credential.</div>'
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="same-origin"><title>Alpecca sign in</title></head>
<body style="margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#070b14;color:#cfe0ff;font-family:system-ui,sans-serif">
<main style="box-sizing:border-box;width:min(360px,calc(100vw - 32px));background:#0b1220;padding:28px 26px;border-radius:8px;border:1px solid #263653">
  <div style="font-size:22px;font-weight:700;margin-bottom:6px">Alpecca</div>
  <div style="color:#8aa0c6;font-size:13px;margin-bottom:18px">Validate this device once as CreatorJD. The password is checked locally and never placed in the URL or browser storage; afterward this browser is trusted.</div>
  {error_html}{form}{unavailable}
</main></body></html>"""

_CORS_ALLOWED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
}

CREATOR_COMMITMENT_SCOPE = "creator-personal"
_EXPLICIT_CORS_ORIGINS = frozenset(
    value.strip().rstrip("/")
    for value in os.environ.get("ALPECCA_CORS_ORIGINS", "").split(",")
    if value.strip()
)


def _runtime_public_origins() -> frozenset[str]:
    """Return explicitly configured origins plus the live preview origin.

    ``scripts/share.py`` may attach a quick tunnel to an already-running
    backend.  In that case changing the parent process environment cannot
    update this module's import-time allowlist.  The preview manager writes
    the URL only after cloudflared has issued it, so reading that small local
    state record keeps the allowlist current without accepting arbitrary
    ``Origin`` or forwarded-host values from a request.
    """
    origins = set(_EXPLICIT_CORS_ORIGINS)
    try:
        preview = json.loads((HOME / "preview.json").read_text(encoding="utf-8"))
        preview_url = _normalized_origin(str(preview.get("url", "")))
    except (OSError, TypeError, ValueError, AttributeError):
        preview_url = ""
    if preview_url:
        origins.add(preview_url)
    return frozenset(origins)


def _normalized_origin(origin: str) -> str:
    if not origin:
        return ""
    try:
        parsed = urlparse(origin)
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password or parsed.path not in {"", "/"}:
        return ""
    if parsed.params or parsed.query or parsed.fragment:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _allowed_cors_origin(origin: str) -> str:
    normalized = _normalized_origin(origin)
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    if host in _CORS_ALLOWED_HOSTS or normalized in _runtime_public_origins():
        return normalized
    return ""


def _with_cors(resp: Response, origin: str) -> Response:
    allowed = _allowed_cors_origin(origin)
    if not allowed:
        return resp
    resp.headers["Access-Control-Allow-Origin"] = allowed
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, X-Alpecca-Authorization, X-Alpecca-Identity, "
        f"{capability_leases_mod.TOKEN_HEADER}, "
        f"{capability_leases_mod.PURPOSE_HEADER}, "
        f"{capability_leases_mod.CONNECTION_HEADER}"
    )
    resp.headers["Access-Control-Expose-Headers"] = (
        "X-Alpecca-TTS-Engine, X-Alpecca-TTS-Status, X-Alpecca-TTS-Error, "
        "X-Alpecca-TTS-Exact-Text, X-Alpecca-Voice, X-Alpecca-Voice-Profile, "
        "X-Alpecca-Voice-Tone, X-Alpecca-Voice-Pitch, X-Alpecca-Voice-Speed, "
        "X-Alpecca-Voice-Volume, X-Alpecca-Voice-Primary, X-Alpecca-Voice-Tempo, "
        "X-Alpecca-Voice-Rate, X-Alpecca-Voice-Style, X-Alpecca-Voice-Warmth, "
        "X-Alpecca-Voice-Breath, X-Alpecca-Voice-Modulation-Strength, "
        "X-Alpecca-Voice-Engine-Profile, X-Alpecca-Voice-Reference, "
        "X-Alpecca-Voice-Personality, X-Alpecca-Voice-Identity-Lock, "
        "X-Alpecca-Voice-Preview, X-Alpecca-Spoken-Text, X-Alpecca-Speech-Cues"
    )
    vary = resp.headers.get("Vary")
    resp.headers["Vary"] = "Origin" if not vary else f"{vary}, Origin"
    return resp


def _header_text(value: str, limit: int = 240) -> str:
    """Return a short HTTP-header-safe text value."""
    text = str(value or "").replace("\r", " ").replace("\n", " ")[:limit]
    return text.encode("latin-1", "ignore").decode("latin-1")


def _record_auth_decision(
    event: str,
    decision: auth_mod.AuthDecision,
    *,
    path: str,
    method: str,
    remote_addr: str,
) -> None:
    """Persist a secret-free authorization decision without request values."""
    try:
        metadata = decision.as_audit_metadata()
        metadata.update({
            "event": str(event or "authorization")[:48],
            "path": str(path or "/")[:160],
            "method": str(method or "")[:12],
            "remote_scope": (
                "loopback" if auth_mod.is_loopback_address(remote_addr) else "remote"
            ),
        })
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="authorization_audit",
            content=(
                f"Authorization {metadata['event']} for {metadata['method']} "
                f"{metadata['path']}: {'allowed' if decision.allowed else 'denied'}."
            ),
            confidence=1.0,
            privacy_class="local",
            metadata=metadata,
        ))
    except Exception:
        pass


def _safe_local_path(value: str | None) -> str:
    candidate = str(value or "/").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return "/"
    # Bootstrap credentials never survive the redirect, and arbitrary query
    # values are not carried through this security boundary.
    return (parsed.path or "/")[:1024]


def issue_local_bootstrap_url(path: str = "/") -> str:
    """Mint a short-lived one-use URL for a launcher on this same machine."""
    code = _AUTHORITY.issue_bootstrap_code("127.0.0.1")
    next_path = _safe_local_path(path)
    return (
        f"http://127.0.0.1:{PORT}/auth/bootstrap"
        f"?code={quote(code, safe='')}&next={quote(next_path, safe='')}"
    )


def _cookie_origin_allowed(request: Request, origin: str) -> bool:
    normalized = _normalized_origin(origin)
    request_origin = _normalized_origin(
        f"{request.url.scheme}://{request.url.netloc}"
    )
    if normalized:
        if normalized == request_origin:
            return True
        return (
            normalized in _runtime_public_origins()
            and bool(_allowed_cors_origin(normalized))
        )

    # Some mobile browsers omit Origin on a normal same-origin form POST.
    # Referer is accepted only when its origin is the request origin or an
    # explicitly configured public tunnel origin; arbitrary cross-site forms
    # remain rejected.
    referer = _normalized_origin(request.headers.get("referer", ""))
    if not referer:
        return False
    if referer == request_origin:
        return True
    return referer in _runtime_public_origins() and bool(_allowed_cors_origin(referer))


def _validate_bound_device_session(
    decision: auth_mod.AuthDecision,
    request_origin: str,
) -> auth_mod.AuthDecision:
    """Fail closed when a native-device cookie is stale or changes origin."""
    if not decision.allowed or not decision.device_id:
        return decision
    if (
        decision.session_origin != request_origin
        or not _TRUSTED_DEVICE_REGISTRY.session_valid(
            decision.device_id,
            decision.issued_at,
        )
    ):
        return auth_mod.AuthDecision(
            False,
            "device_session",
            "revoked_or_origin_mismatch",
            principal=decision.principal,
        )
    return decision


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    origin = request.headers.get("origin", "")
    if request.method == "OPTIONS":
        if origin and not _allowed_cors_origin(origin):
            return _JSON({"detail": "origin not allowed"}, status_code=403)
        return _with_cors(Response(status_code=204), origin)

    if request.url.path in _PUBLIC_AUTH_PATHS:
        return _with_cors(await call_next(request), origin)

    client_host = request.client.host if request.client else ""
    bridge_header_values = request.headers.getlist(
        auth_mod.BRIDGE_AUTHORIZATION_HEADER
    )
    bridge_service_requested = (
        request.url.path in _DISCORD_SERVICE_PATHS
        or (request.url.path == "/tts" and bool(bridge_header_values))
    )
    if bridge_service_requested and len(bridge_header_values) != 1:
        decision = auth_mod.AuthDecision(
            False,
            "service_bearer",
            "duplicate" if bridge_header_values else "missing",
        )
    elif bridge_service_requested:
        decision = _AUTHORITY.validate_bridge_service(
            request.headers,
            service="discord-bridge",
        )
    else:
        decision = _AUTHORITY.authorize_request(
            headers=request.headers,
            cookies=request.cookies,
            query=request.query_params,
        )
        decision = _validate_bound_device_session(
            decision,
            _normalized_origin(f"{request.url.scheme}://{request.url.netloc}"),
        )
    if not decision.allowed:
        _record_auth_decision(
            "request",
            decision,
            path=request.url.path,
            method=request.method,
            remote_addr=client_host,
        )
        if (
            request.method == "GET"
            and "text/html" in request.headers.get("accept", "")
            and auth_mod.is_loopback_address(client_host)
        ):
            # The laptop itself is an explicitly trusted device. Redirect into
            # the existing one-use POST bootstrap exchange so this middleware
            # never mints cookies and Jason never pastes a password or token.
            trusted = auth_mod.AuthDecision(
                True,
                "local_trusted_device",
                "loopback_browser_enrolled",
                principal="creator",
                remote_scope="loopback",
            )
            _record_auth_decision(
                "local_device_trust",
                trusted,
                path=request.url.path,
                method=request.method,
                remote_addr=client_host,
            )
            return _with_cors(RedirectResponse(
                issue_local_bootstrap_url(request.url.path),
                status_code=303,
                headers={"Cache-Control": "no-store"},
            ), origin)
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return _with_cors(
                HTMLResponse(
                    _access_html(
                        request.url.path,
                        allow_password=request.url.scheme == "https",
                    ),
                    status_code=401,
                    headers={"Cache-Control": "no-store"},
                ),
                origin,
            )
        return _with_cors(
            _JSON(
                {"detail": "authorization required"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            ),
            origin,
        )

    if (
        decision.mechanism == "session_cookie"
        and request.method not in _SAFE_HTTP_METHODS
        and not _cookie_origin_allowed(request, origin)
    ):
        denied = auth_mod.AuthDecision(
            False,
            "session_cookie",
            "origin_required",
            principal=decision.principal,
        )
        _record_auth_decision(
            "csrf_origin",
            denied,
            path=request.url.path,
            method=request.method,
            remote_addr=client_host,
        )
        return _with_cors(
            _JSON(
                {"detail": "same-origin request required"},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            ),
            origin,
        )

    request.state.authorization = decision
    result = await call_next(request)
    if request.url.path in _DISCORD_SERVICE_PATHS:
        result.headers["Cache-Control"] = "no-store"
    return _with_cors(result, origin)


@app.get("/auth/status")
def auth_status() -> dict:
    return {
        "authorization": "required",
        "bootstrap": "loopback_only",
        "creator_password": {
            "configured": _AUTHORITY.password_configured,
            "stored_in_browser": False,
        },
        "trusted_device": {
            "days": _TRUSTED_DEVICE_DAYS,
            "cookie_http_only": True,
            "cookie_same_site": "strict",
            "remote_requires_https": True,
            "native_key_enrollment": True,
            "active_native_devices": _TRUSTED_DEVICE_REGISTRY.active_count(),
        },
        "public_identity_authorizes": False,
        "session_cookie": {
            "http_only": True,
            "same_site": "strict",
        },
    }


async def _device_json(request: Request) -> dict:
    raw = await _read_bounded_body(request, max_bytes=8192)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid device request") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid device request")
    return payload


def _device_request_origin(request: Request) -> str:
    client_host = request.client.host if request.client else ""
    if request.url.scheme != "https" and not auth_mod.is_loopback_address(client_host):
        raise HTTPException(status_code=403, detail="https required")
    request_origin = _normalized_origin(f"{request.url.scheme}://{request.url.netloc}")
    supplied_origin = _normalized_origin(request.headers.get("origin", ""))
    if not request_origin or supplied_origin != request_origin:
        raise HTTPException(status_code=403, detail="same-origin device request required")
    return request_origin


@app.post("/auth/device/enroll")
async def enroll_trusted_device(request: Request) -> Response:
    """Register one Android Keystore public key after creator authorization."""
    decision = getattr(request.state, "authorization", None)
    if not isinstance(decision, auth_mod.AuthDecision) or not decision.allowed or decision.principal != "creator":
        raise HTTPException(status_code=403, detail="creator authorization required")
    _device_request_origin(request)
    payload = await _device_json(request)
    try:
        enrolled = await _bounded_thread(
            "trusted-device-enroll",
            lambda: _TRUSTED_DEVICE_REGISTRY.enroll(
                str(payload.get("public_key", "")),
                label=str(payload.get("label", "CreatorJD phone")),
            ),
        )
    except trusted_devices_mod.DeviceAuthError as exc:
        raise HTTPException(status_code=400, detail=exc.code) from exc
    if enrolled is None:
        raise HTTPException(status_code=503, detail="device enrollment timed out")
    audit = auth_mod.AuthDecision(True, "device_key", "enrolled", principal="creator")
    _record_auth_decision(
        "device_enroll", audit, path=request.url.path, method=request.method,
        remote_addr=request.client.host if request.client else "",
    )
    return _JSON({"ok": True, **enrolled}, headers={"Cache-Control": "no-store"})


@app.post("/auth/device/challenge")
async def trusted_device_challenge(request: Request) -> Response:
    """Issue a short-lived challenge bound to this exact HTTPS origin."""
    origin = _device_request_origin(request)
    payload = await _device_json(request)
    try:
        challenge = await _bounded_thread(
            "trusted-device-challenge",
            _TRUSTED_DEVICE_REGISTRY.issue_challenge,
            str(payload.get("device_id", "")),
            origin,
        )
    except trusted_devices_mod.DeviceAuthError as exc:
        raise HTTPException(status_code=404, detail="device unavailable") from exc
    if challenge is None:
        raise HTTPException(status_code=503, detail="device challenge timed out")
    return _JSON(challenge, headers={"Cache-Control": "no-store"})


@app.post("/auth/device/exchange")
async def trusted_device_exchange(request: Request) -> Response:
    """Verify one device signature and mint a new origin-scoped HttpOnly cookie."""
    origin = _device_request_origin(request)
    payload = await _device_json(request)
    client_host = request.client.host if request.client else ""
    try:
        device_id = await _bounded_thread(
            "trusted-device-exchange",
            _TRUSTED_DEVICE_REGISTRY.exchange,
            str(payload.get("challenge_id", "")),
            str(payload.get("signature", "")),
            origin,
        )
    except trusted_devices_mod.DeviceAuthError as exc:
        denied = auth_mod.AuthDecision(False, "device_key", exc.code)
        _record_auth_decision(
            "device_exchange", denied, path=request.url.path, method=request.method,
            remote_addr=client_host,
        )
        raise HTTPException(status_code=401, detail="device verification failed") from exc
    if device_id is None:
        raise HTTPException(status_code=503, detail="device verification timed out")
    cookie = _AUTHORITY.issue_session_cookie(
        secure=request.url.scheme == "https",
        device_id=device_id,
        origin=origin,
    )
    accepted = auth_mod.AuthDecision(True, "device_key", "accepted", principal="creator")
    _record_auth_decision(
        "device_exchange", accepted, path=request.url.path, method=request.method,
        remote_addr=client_host,
    )
    response = _JSON(
        {"ok": True, "device_id": device_id},
        headers={"Cache-Control": "no-store"},
    )
    response.set_cookie(cookie.name, cookie.value, **cookie.set_cookie_kwargs())
    return response


@app.delete("/auth/device/{device_id}")
async def revoke_trusted_device(device_id: str, request: Request) -> Response:
    """Creator-only revocation for a lost or replaced phone."""
    _device_request_origin(request)
    decision = getattr(request.state, "authorization", None)
    if not isinstance(decision, auth_mod.AuthDecision) or decision.principal != "creator":
        raise HTTPException(status_code=403, detail="creator authorization required")
    revoked = await _bounded_thread(
        "trusted-device-revoke",
        _TRUSTED_DEVICE_REGISTRY.revoke,
        device_id,
    )
    if revoked is None:
        raise HTTPException(status_code=503, detail="device revocation timed out")
    response = _JSON(
        {"ok": revoked},
        status_code=200 if revoked else 404,
        headers={"Cache-Control": "no-store"},
    )
    if revoked and decision.device_id == device_id:
        response.delete_cookie(
            auth_mod.SESSION_COOKIE_NAME,
            path="/",
            secure=request.url.scheme == "https",
            httponly=True,
            samesite="strict",
        )
    return response


@app.get("/healthz")
def healthz() -> dict:
    """Stable, intentionally sparse identity for local process probes."""
    return {"service": "alpecca", "version": 1}


@app.get("/auth/bootstrap")
def auth_bootstrap_landing(request: Request) -> Response:
    """Turn a launcher navigation into an explicit POST-only exchange."""
    code = html.escape(request.query_params.get("code", ""), quote=True)
    next_path = html.escape(
        _safe_local_path(request.query_params.get("next")),
        quote=True,
    )
    page = f"""<!doctype html><meta charset="utf-8">
<meta name="referrer" content="no-referrer"><title>Opening Alpecca</title>
<form id="bootstrap" method="post" action="/auth/bootstrap/exchange?code={code}&amp;next={next_path}"></form>
<script>document.getElementById('bootstrap').submit()</script>
<noscript><button form="bootstrap" type="submit">Open Alpecca</button></noscript>"""
    return HTMLResponse(
        page,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/auth/bootstrap/exchange")
def auth_bootstrap_exchange(request: Request) -> Response:
    client_host = request.client.host if request.client else ""
    decision, cookie = _AUTHORITY.exchange_bootstrap_code(
        request.query_params.get("code", ""),
        client_host,
        secure=request.url.scheme == "https",
    )
    _record_auth_decision(
        "bootstrap_exchange",
        decision,
        path=request.url.path,
        method=request.method,
        remote_addr=client_host,
    )
    if not decision.allowed or cookie is None:
        return _JSON(
            {"detail": "invalid or expired local bootstrap"},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )
    response = RedirectResponse(
        _safe_local_path(request.query_params.get("next")),
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )
    response.set_cookie(cookie.name, cookie.value, **cookie.set_cookie_kwargs())
    return response


@app.post("/auth/bootstrap/request")
def request_auth_bootstrap(request: Request) -> dict:
    client_host = request.client.host if request.client else ""
    if not auth_mod.is_loopback_address(client_host):
        raise HTTPException(status_code=403, detail="loopback required")
    return {
        "url": issue_local_bootstrap_url(
            _safe_local_path(request.query_params.get("next"))
        )
    }


@app.get("/auth/password")
def auth_password_landing(request: Request) -> Response:
    """Serve the remote creator password form for direct mobile opens."""
    client_host = request.client.host if request.client else ""
    allow_password = request.url.scheme == "https" or auth_mod.is_loopback_address(client_host)
    return HTMLResponse(
        _access_html(
            _safe_local_path(request.query_params.get("next") or "/house-hq"),
            allow_password=allow_password,
        ),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/auth/password")
async def auth_password_exchange(request: Request) -> Response:
    """Exchange the protected creator password for an HttpOnly session."""
    client_host = request.client.host if request.client else ""
    if (
        not auth_mod.is_loopback_address(client_host)
        and request.url.scheme != "https"
    ):
        decision = auth_mod.AuthDecision(
            False, "password", "https_required", remote_scope="remote"
        )
        _record_auth_decision(
            "password_exchange",
            decision,
            path=request.url.path,
            method=request.method,
            remote_addr=client_host,
        )
        return _JSON(
            {"detail": "remote creator sign-in requires HTTPS"},
            status_code=426,
            headers={"Cache-Control": "no-store", "Upgrade": "TLS/1.2"},
        )
    origin = request.headers.get("origin", "")
    if origin and not _cookie_origin_allowed(request, origin):
        decision = auth_mod.AuthDecision(
            False, "password", "origin_required", remote_scope="unknown"
        )
        _record_auth_decision(
            "password_exchange",
            decision,
            path=request.url.path,
            method=request.method,
            remote_addr=client_host,
        )
        return _JSON(
            {"detail": "same-origin password sign-in required"},
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )
    try:
        raw = await request.body()
    except Exception:
        raw = b""
    if len(raw) > 4096:
        return _JSON(
            {"detail": "password form is too large"},
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )
    try:
        form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    except (UnicodeError, ValueError):
        form = {}
    password = str((form.get("password") or [""])[0])
    next_path = _safe_local_path(str((form.get("next") or ["/"])[0]))
    decision, cookie = _AUTHORITY.exchange_password(
        password,
        client_host,
        secure=request.url.scheme == "https",
    )
    _record_auth_decision(
        "password_exchange",
        decision,
        path=request.url.path,
        method=request.method,
        remote_addr=client_host,
    )
    if not decision.allowed or cookie is None:
        status_code = 429 if decision.reason == "rate_limited" else 401
        headers = {"Cache-Control": "no-store"}
        if status_code == 429:
            headers["Retry-After"] = str(auth_mod.PASSWORD_WINDOW_SECONDS)
        return HTMLResponse(
            _access_html(
                next_path,
                "Too many attempts; wait one minute."
                if status_code == 429
                else "That creator password was not accepted.",
            ),
            status_code=status_code,
            headers=headers,
        )
    response = RedirectResponse(
        next_path,
        status_code=303,
        headers={"Cache-Control": "no-store"},
    )
    response.set_cookie(cookie.name, cookie.value, **cookie.set_cookie_kwargs())
    return response


@app.get("/security/capabilities")
def security_capabilities() -> dict:
    return capabilities_mod.public_snapshot()


@app.get("/")
def index() -> RedirectResponse:
    """The Void Prototype is Alpecca's single primary embodied surface."""
    return RedirectResponse("/house-hq", status_code=307)


@app.get("/classic")
def classic() -> HTMLResponse:
    """The original full-featured chat page (voice push-to-talk, image attach,
    avatar state machine). Kept as a focused compatibility surface alongside
    the unified Void Prototype."""
    return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/studio")
def studio_page() -> HTMLResponse:
    """Her studio -- a window into where she designs and rigs her character.
    Read-only: you watch and can ask her to work, but never edit her design."""
    return HTMLResponse((WEB_DIR / "studio.html").read_text(encoding="utf-8"))


@app.get("/home")
def home_page() -> RedirectResponse:
    """Compatibility route for bookmarks made before the Void consolidation."""
    return RedirectResponse("/house-hq", status_code=307)


# --- /app: her private "get her on every device" page --------------------------
# One page that hands Jason every way to carry her along: the Windows launcher,
# install-as-app on Android/iPhone (with a credential-free QR that opens device
# enrollment), a Discord invite, and the share/tunnel recipes.
# Nothing here weakens the lock -- the same trusted-device middleware covers
# these routes like every other page, so /app is exactly as private as she is.

# The desktop launcher another workspace authors. We only READ these paths at
# request time (never create them), so /app degrades gracefully -- offering the
# zip until the exe exists, and a clean 404 until the source folder exists.
LAUNCHER_DIR = ROOT_DIR / "apps" / "launcher"
LAUNCHER_SRC_DIR = LAUNCHER_DIR / "src"
LAUNCHER_EXE = LAUNCHER_DIR / "dist" / "AlpeccaLauncher.exe"
ANDROID_LAUNCHER_APK = ROOT_DIR / "output" / "alpecca-launcher" / "AlpeccaLauncher.apk"
# The same git-ignored secret the Discord bridge reads (scripts/run_discord_bridge.py).
DISCORD_SECRET_FILE = ROOT_DIR / "data" / "secrets" / "alpecca_discord.env"


def _app_lan_ip() -> str:
    """Best-effort LAN IP -- the address a phone on the same WiFi would use to
    reach her (the scripts/share.py lan_ip() trick: connecting a UDP socket
    sends no packets, it just makes the OS pick the outbound route's address)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _discord_bot_token() -> str:
    """Her Discord bot token, if she has one: environment first, then the
    git-ignored secret file. Read fresh per call so dropping the file in place
    lights the Discord card up without a restart. Never returned to a client --
    only its *presence* (and the app id derived below) ever leaves this module."""
    tok = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if tok:
        return tok
    try:
        for line in DISCORD_SECRET_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.partition("=")[2].strip()
    except Exception:
        pass
    return ""


def _discord_client_id() -> str:
    """The numeric application id Discord's invite screen needs. A bot token's
    first '.'-segment is just that id, base64-encoded -- so normally we derive
    it from the token she already has and there is nothing to configure. The
    ALPECCA_DISCORD_CLIENT_ID knob (config.py) overrides the derivation for the
    day the token shape ever changes."""
    if DISCORD_CLIENT_ID:
        return DISCORD_CLIENT_ID
    tok = _discord_bot_token()
    seg = tok.split(".", 1)[0] if "." in tok else ""
    if not seg:
        return ""
    try:
        pad = "=" * (-len(seg) % 4)   # b64 wants length % 4 == 0; tokens drop the padding
        decoded = base64.urlsafe_b64decode(seg + pad).decode("utf-8", "ignore").strip()
    except Exception:
        return ""
    return decoded if decoded.isdigit() else ""


@app.get("/app")
def app_page() -> HTMLResponse:
    """The everywhere page: every way to install/carry Alpecca, in one place."""
    return HTMLResponse((WEB_DIR / "app.html").read_text(encoding="utf-8"))


@app.get("/app/meta")
def app_meta() -> dict:
    """What the /app page needs to lay itself out honestly: whether the real
    Windows exe is built (else it offers the zip), her LAN address for the
    phone QRs, and whether Discord is configured enough to invite her."""
    return {
        "exe_built": LAUNCHER_EXE.is_file(),
        "android_apk_built": ANDROID_LAUNCHER_APK.is_file(),
        "lan_ip": _app_lan_ip(),
        "port": PORT,
        "discord_ready": bool(_discord_bot_token() or DISCORD_CLIENT_ID),
    }


@app.get("/app/discord/invite")
def app_discord_invite():
    """Bounce straight to Discord's own authorize screen for HER bot. Discord
    renders the consent UI and the server picker -- we only supply the app id
    and a modest permission set (3263552: read/send/embed/attach/history/
    mention + voice connect/speak -- what the bridge actually uses)."""
    client_id = _discord_client_id()
    if not client_id:
        return _JSON({"error": "discord bot not configured"}, status_code=404)
    return RedirectResponse(
        "https://discord.com/oauth2/authorize"
        f"?client_id={client_id}&scope=bot&permissions=3263552",
        status_code=302,
    )


@app.get("/app/download/launcher.zip")
def app_download_launcher_zip() -> Response:
    """Bundle the launcher SOURCE as a zip, built in memory at request time.
    Reading the folder live (instead of shipping a stale artifact) means the
    download is always exactly what's in apps/launcher/src right now."""
    if not LAUNCHER_SRC_DIR.is_dir():
        raise HTTPException(status_code=404, detail="launcher source not present yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(LAUNCHER_SRC_DIR.rglob("*")):
            # Source only: running the launcher locally litters __pycache__
            # bytecode next to it, and that noise has no business in the zip.
            if "__pycache__" in f.parts or f.suffix == ".pyc":
                continue
            if f.is_file():
                zf.write(f, "alpecca-launcher/" + f.relative_to(LAUNCHER_SRC_DIR).as_posix())
        # The launcher folder's README rides along so the unzipped folder
        # explains itself -- unless src/ already carries one of its own.
        if "alpecca-launcher/README.md" not in zf.namelist():
            for readme in ("README.md", "README.txt", "README"):
                cand = LAUNCHER_DIR / readme
                if cand.is_file():
                    zf.write(cand, f"alpecca-launcher/{readme}")
                    break
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="alpecca-launcher.zip"'},
    )


@app.get("/app/download/launcher.exe")
def app_download_launcher_exe() -> FileResponse:
    """The one-file Windows launcher, once someone has actually built it
    (apps/launcher/dist/AlpeccaLauncher.exe). Until then: honest 404, and the
    /app page offers the zip instead."""
    if not LAUNCHER_EXE.is_file():
        raise HTTPException(status_code=404, detail="launcher exe not built yet")
    return FileResponse(
        LAUNCHER_EXE,
        media_type="application/vnd.microsoft.portable-executable",
        filename="AlpeccaLauncher.exe",
    )


@app.get("/mindscape")
def mindscape_page() -> HTMLResponse:
    """Mobile/cloud continuity shell for Alpecca."""
    return HTMLResponse((WEB_DIR / "mindscape.html").read_text(encoding="utf-8"))


@app.get("/mindscape/state")
def mindscape_state() -> dict:
    """Compact status for the mobile Mindscape header."""
    snap = _mindscape_snapshot(check_models=False)
    d = mindscape_mod.summary(snap)
    d["sync"] = _mindscape_sync_status_view()
    return d


@app.get("/mindpage/stats")
def mindpage_stats() -> dict:
    """Observable working-memory/page pressure for Alpecca."""
    return mindpage_mod.stats(
        history=getattr(mind, "_history", []),
        ledger=getattr(mind, "_last_mindpage", None),
    )


@app.get("/affect/incidents")
def affect_incidents(req: Request, limit: int = 30) -> JSONResponse:
    """Creator-only evidence and recovery state for affective incident learning."""
    _require_creator_request(req)
    return JSONResponse(
        {
            "schema": incident_learning_mod.SCHEMA,
            "current": mind._active_incident_signal.as_dict(),
            "incidents": incident_learning_mod.recent(limit=limit),
            "literal_human_trauma_claim": False,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/affect/incidents")
async def affect_incident_record(req: Request) -> JSONResponse:
    """Record creator-verified evidence; model output cannot call this route."""
    _require_creator_request(req)
    try:
        body = await req.json()
        if not isinstance(body, dict):
            raise ValueError
        async with mind_lock:
            incident = mind.note_incident(
                source=str(body.get("source") or "creator_verified"),
                cue=str(body.get("cue") or ""),
                summary=str(body.get("summary") or ""),
                severity=float(body.get("severity", 0.0)),
                controllability=float(body.get("controllability", 0.5)),
                prediction_error=float(body.get("prediction_error", 0.0)),
            )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid incident evidence") from exc
    return JSONResponse(incident, headers={"Cache-Control": "no-store"})


@app.post("/affect/incidents/{incident_id}/outcome")
async def affect_incident_outcome(incident_id: int, req: Request) -> JSONResponse:
    """Record a verified safe retry or recurrence for recovery learning."""
    _require_creator_request(req)
    try:
        body = await req.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="body must be JSON") from exc
    if not isinstance(body, dict) or not isinstance(body.get("safe"), bool):
        raise HTTPException(status_code=400, detail="safe must be a boolean")
    async with mind_lock:
        incident = mind.note_incident_outcome(incident_id, safe=body["safe"])
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return JSONResponse(incident, headers={"Cache-Control": "no-store"})


@app.get("/app/download/alpecca-android.apk")
def app_download_android_launcher() -> FileResponse:
    """Serve the reviewed personal Android launcher from the protected app page."""
    if not ANDROID_LAUNCHER_APK.is_file():
        raise HTTPException(status_code=404, detail="Android launcher APK not built yet")
    return FileResponse(
        ANDROID_LAUNCHER_APK,
        media_type="application/vnd.android.package-archive",
        filename="AlpeccaLauncher.apk",
    )


@app.get("/knowledge/brain-map")
def knowledge_brain_map(req: Request) -> JSONResponse:
    """Creator-only, read-only map of explicitly taught knowledge."""
    _require_creator_request(req)
    return JSONResponse(
        knowledge_blocks_mod.brain_map_snapshot(scope="creator", db_path=DB_PATH),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/preferences/snapshot")
def preferences_snapshot(req: Request) -> JSONResponse:
    """Creator-only, read-only grounded preference/favorites snapshot."""
    _require_creator_request(req)
    return JSONResponse(
        preferences_mod.snapshot(db_path=DB_PATH),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/overload/read-the-room")
def overload_read_the_room(req: Request) -> JSONResponse:
    """Return cited workload evidence, never an invented emotional state."""
    _require_creator_request(req)
    ledger = mind.mindpage_state()
    raw_context_fill = ledger.get("context_fill") if isinstance(ledger, Mapping) else None
    context_cue = (
        overload_mod.context_pressure_cue(raw_context_fill)
        if isinstance(raw_context_fill, (int, float)) and not isinstance(raw_context_fill, bool)
        else None
    )
    assessment = overload_mod.assess_overload(
        # There is no real turn-rate meter yet, so this deliberately remains
        # unknown rather than fabricating a calm message-volume reading.
        concurrent_actors=overload_mod.concurrent_actor_cue(len(ws_clients)),
        context_pressure=context_cue,
        host_pressure=overload_mod.host_pressure_cue_from_measurement(
            _host_resource_sampler.snapshot(force=False)
        ),
    )
    return JSONResponse(assessment, headers={"Cache-Control": "no-store"})


@app.get("/mindscape/snapshot")
def mindscape_snapshot() -> dict:
    """Full continuity snapshot for fallback/mobile/cloud shells."""
    snap = _mindscape_snapshot(check_models=True)
    snap["sync"] = _mindscape_sync_status_view()
    return snap


@app.get("/mindscape/sync/status")
def mindscape_sync_status() -> dict:
    """Whether automatic Mindscape continuity mirroring is active."""
    return _mindscape_sync_status_view()


@app.get("/mindscape/setup")
def mindscape_setup() -> dict:
    """Concrete setup checklist for hosted Mindscape continuity."""
    legacy = mindscape_mod.cloud_setup_plan(
        ROOT_DIR / "deploy" / "mindscape-worker",
        cloud_url=MINDSCAPE_CLOUD_URL,
        token_configured=bool(MINDSCAPE_TOKEN),
    )
    vault_dir = ROOT_DIR / "deploy" / "mindscape-vault-worker"
    vault_template_ready = all((vault_dir / name).exists() for name in ("worker.js", "wrangler.toml", "README.md"))
    return {
        **legacy,
        "vault": {
            "enabled": bool(MINDSCAPE_VAULT_ENABLED),
            "configured": _mindscape_vault_configured(),
            "worker_dir": str(vault_dir),
            "template_ready": vault_template_ready,
            "steps": [
                {"id": "create_r2", "done": bool(MINDSCAPE_VAULT_URL), "label": "Create the encrypted Mindscape Vault R2 bucket.",
                 "command": "npx wrangler r2 bucket create alpecca-mindscape-vault"},
                {"id": "set_vault_secret", "done": bool(_mindscape_vault_transport_token()),
                 "label": "Set the separate Mindscape Vault transport token from Credential Manager.",
                 "command": "npx wrangler secret put MINDSCAPE_VAULT_TOKEN"},
                {"id": "deploy_vault", "done": bool(MINDSCAPE_VAULT_URL),
                 "label": "Deploy the Vault Worker and configure its local base URL.",
                 "command": "npx wrangler deploy"},
            ],
        },
    }


@app.post("/mindscape/setup/review")
async def mindscape_setup_review() -> dict:
    """Record Mindscape setup gaps as a bounded self-improvement proposal."""
    setup = mindscape_mod.cloud_setup_plan(
        ROOT_DIR / "deploy" / "mindscape-worker",
        cloud_url=MINDSCAPE_CLOUD_URL,
        token_configured=bool(MINDSCAPE_TOKEN),
    )
    async with mind_lock:
        review = mind.review_mindscape_setup(setup)
    return {"setup": setup, "review": review}


@app.post("/mindscape/sync")
async def mindscape_sync() -> dict:
    """Mirror a continuity sync when a cloud endpoint is configured.

    Without ALPECCA_MINDSCAPE_URL this remains local-first and returns the
    snapshot. With a URL, it POSTs the snapshot to that endpoint so a hosted
    Mindscape can continue from the latest known state if this device goes down.
    """
    if _mindscape_vault_configured():
        mirror = await _mindscape_vault_sync_once(reason="manual", check_models=True)
        snap = _mindscape_snapshot(check_models=False)
        cloud_url = MINDSCAPE_VAULT_URL
    else:
        snap = _mindscape_snapshot(check_models=True)
        _mindscape_sync_status["last_trigger"] = _time.time()
        _mindscape_sync_status["last_trigger_reason"] = "manual"
        mirror = _mindscape_mirror_snapshot(snap)
        cloud_url = MINDSCAPE_CLOUD_URL
    return {
        "ok": bool(MINDSCAPE_VAULT_ENABLED if _mindscape_vault_configured() else MINDSCAPE_ENABLED) and (
            mirror.get("ok") or not cloud_url
        ),
        "cloud_configured": bool(cloud_url),
        "cloud_url": cloud_url,
        "mirror": mirror,
        "sync": _mindscape_sync_status_view(),
        "snapshot": snap,
    }


@app.get("/mindscape/vault/status")
def mindscape_vault_status() -> dict:
    """Content-free state of the encrypted cloud recovery outbox."""
    return _mindscape_vault_status_view()


@app.post("/mindscape/vault/sync")
async def mindscape_vault_sync() -> dict:
    """Queue and mirror an encrypted continuity snapshot now."""
    result = await _mindscape_vault_sync_once(reason="manual", check_models=True)
    return {"ok": bool(result.get("ok")), "mirror": result, "status": _mindscape_vault_status_view()}


@app.post("/mindscape/vault/archive")
async def mindscape_vault_archive() -> dict:
    """Create and upload one creator-requested encrypted SQLite recovery record."""
    result = await _mindscape_vault_archive_once(reason="manual")
    return {"ok": bool(result.get("ok")), "archive": result, "status": _mindscape_vault_status_view()}


@app.post("/mindscape/restore/preview")
async def mindscape_restore_preview(req: Request) -> dict:
    """Preview what would be merged from cloud or a posted Mindscape snapshot."""
    _require_creator_request(req)
    try:
        body = await req.json()
    except Exception:
        body = {}
    source = await _bounded_thread(
        "mindscape-restore-preview",
        _mindscape_restore_source,
        body,
        timeout=max(5.0, float(MINDSCAPE_VAULT_SYNC_TIMEOUT) + 2.0),
    )
    if source is None:
        raise HTTPException(status_code=503, detail="restore preview timed out")
    if not source.get("ok"):
        return {"ok": False, "source": source.get("source", "cloud"), "error": source.get("error")}
    approval_request = await _bounded_thread(
        "mindscape-restore-preview-ledger",
        _RESTORE_APPROVAL_LEDGER.issue_preview,
        source["preview"]["fingerprint"],
        source["source"],
    )
    if approval_request is None:
        raise HTTPException(status_code=503, detail="restore preview ledger timed out")
    return {
        "ok": True,
        "source": source["source"],
        "preview": source["preview"],
        "approval_request": approval_request,
    }


@app.post("/mindscape/restore/approve")
async def mindscape_restore_approve(req: Request) -> dict:
    """Explicitly authorize one previewed snapshot digest for one import."""
    _require_creator_request(req)
    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        approval = await _bounded_thread(
            "mindscape-restore-approve",
            _RESTORE_APPROVAL_LEDGER.approve,
            str(body.get("preview_id", "")),
            str(body.get("fingerprint", "")),
            approved=body.get("approved") is True,
        )
    except restore_approval_mod.RestoreApprovalError as exc:
        raise HTTPException(status_code=403, detail=exc.code) from exc
    if approval is None:
        raise HTTPException(status_code=503, detail="restore approval timed out")
    accepted = auth_mod.AuthDecision(
        True,
        "restore_approval",
        "digest_approved",
        principal="creator",
    )
    _record_auth_decision(
        "mindscape_restore_approve",
        accepted,
        path=req.url.path,
        method=req.method,
        remote_addr=req.client.host if req.client else "",
    )
    return {"ok": True, "approval": approval}


@app.post("/mindscape/restore/import")
async def mindscape_restore_import(req: Request) -> dict:
    """Merge continuity records from Mindscape without overwriting local state."""
    _require_creator_request(req)
    try:
        body = await req.json()
    except Exception:
        body = {}
    approval_token = str(body.get("approval_token", ""))
    if not approval_token:
        raise HTTPException(status_code=403, detail="restore approval required")
    source = await _bounded_thread(
        "mindscape-restore-import-fetch",
        _mindscape_restore_source,
        body,
        timeout=max(5.0, float(MINDSCAPE_VAULT_SYNC_TIMEOUT) + 2.0),
    )
    if source is None:
        raise HTTPException(status_code=503, detail="restore import fetch timed out")
    if not source.get("ok"):
        return {"ok": False, "source": source.get("source", "cloud"), "error": source.get("error")}
    try:
        preview_id = await _bounded_thread(
            "mindscape-restore-consume-approval",
            _RESTORE_APPROVAL_LEDGER.consume,
            approval_token,
            source["preview"]["fingerprint"],
            source["source"],
        )
    except restore_approval_mod.RestoreApprovalError as exc:
        raise HTTPException(status_code=403, detail=exc.code) from exc
    if preview_id is None:
        raise HTTPException(status_code=503, detail="restore approval check timed out")
    async with mind_lock:
        result = await asyncio.to_thread(_mindscape_import_snapshot, source["snapshot"])
    _mindscape_request_event_sync("restore_import", force=True)
    return {
        "ok": result["ok"],
        "source": source["source"],
        "approval": {"preview_id": preview_id, "consumed": True},
        **result,
    }


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
    d = mind.desires_state()
    proposal_state = mind.proposal_state()
    d["proposals"] = proposal_state["proposals"]
    d["evaluations"] = proposal_state.get("evaluations", [])
    d["safety_policy"] = proposal_state["safety_policy"]
    d["commitments"] = commitments_mod.list_commitments(
        scope=CREATOR_COMMITMENT_SCOPE,
        limit=25,
    )
    d["executable_tools"] = sorted(commitment_executor_mod.ALLOWED_TOOLS)
    return d


def _require_creator_request(req: Request) -> auth_mod.AuthDecision:
    decision = getattr(req.state, "authorization", None)
    if not isinstance(decision, auth_mod.AuthDecision) or not decision.allowed:
        raise HTTPException(
            status_code=401,
            detail="authorization required",
            headers={"Cache-Control": "no-store"},
        )
    if decision.principal != "creator":
        raise HTTPException(
            status_code=403,
            detail="creator authorization required",
            headers={"Cache-Control": "no-store"},
        )
    return decision


def _perception_egress_components() -> tuple[
    interactive_egress_mod.InteractiveCreatorAuthority,
    egress_consent_mod.PerceptionEgressGate,
]:
    runtime = _perception_egress_runtime()
    authority = runtime.get("authority")
    gate = runtime.get("gate")
    if not isinstance(authority, interactive_egress_mod.InteractiveCreatorAuthority):
        raise RuntimeError("private-perception authority unavailable")
    if not isinstance(gate, egress_consent_mod.PerceptionEgressGate):
        raise RuntimeError("private-perception gate unavailable")
    return authority, gate


def _ingest_egress_image(value: object, operation_id: str) -> attachment_ingress_mod.ImageIngress:
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="image required")
    scope = f"private-egress:{operation_id}"
    try:
        return attachment_ingress_mod.ingest_image(
            value,
            scope=scope,
            authorized_scopes={scope},
            source="creator:private-perception-egress",
        )
    except attachment_ingress_mod.ImageIngressRejected as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "attachment_rejected", "reason": exc.reason},
            headers={"Cache-Control": "no-store"},
        ) from exc


@app.get("/perception/egress/consents")
def perception_egress_consents(req: Request) -> JSONResponse:
    """List content-free pending creator decisions and exact configured routes."""
    _require_creator_request(req)
    try:
        authority, gate = _perception_egress_components()
    except Exception as exc:
        return JSONResponse(
            {"available": False, "reason": str(exc), "requests": [], "routes": []},
            headers={"Cache-Control": "no-store"},
        )
    routes = [route.material() for route in gate.ledger.policy.routes]
    return JSONResponse(
        {
            "available": True,
            "requests": authority.list_requests(),
            "routes": routes,
            "payload_retained": False,
            "uses_per_approval": 1,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/perception/egress/stage")
async def perception_egress_stage(req: Request) -> JSONResponse:
    """Stage one exact image decision without retaining pixels or making egress."""
    _require_creator_request(req)
    body = await _read_bounded_json_object(req, max_bytes=3 * 1024 * 1024)
    route_id = body.get("route_id")
    if not isinstance(route_id, str) or not route_id:
        raise HTTPException(status_code=400, detail="route_id required")
    operation_id = "op_" + secrets.token_urlsafe(24)
    inspected = _ingest_egress_image(body.get("image"), operation_id)
    try:
        authority, gate = _perception_egress_components()
        before = {item["request_id"] for item in authority.list_requests()}
        gate.authorize_attempt(
            operation_id=operation_id,
            route_id=route_id,
            payload=inspected.image_bytes,
        )
    except egress_consent_mod.EgressConsentDenied:
        pending = [
            item
            for item in authority.list_requests()
            if item["request_id"] not in before
            and item["route_id"] == route_id
            and item["byte_count"] == len(inspected.image_bytes)
        ]
        if not pending:
            raise HTTPException(status_code=503, detail="consent request unavailable")
        return JSONResponse(
            {
                "staged": True,
                "operation_id": operation_id,
                "request": pending[0],
                "image": inspected.as_dict(),
                "payload_retained": False,
            },
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail="unexpected pre-authorized operation")


@app.post("/perception/egress/consents/{request_id}")
async def perception_egress_decide(
    request_id: str, req: Request
) -> JSONResponse:
    """Resolve one pending exact request; only the authenticated creator may call."""
    _require_creator_request(req)
    body = await _read_bounded_json_object(req, max_bytes=1024)
    if set(body) != {"allowed"} or not isinstance(body.get("allowed"), bool):
        raise HTTPException(status_code=400, detail="allowed boolean required")
    try:
        authority, _gate = _perception_egress_components()
        resolved = authority.resolve(request_id, allowed=body["allowed"] is True)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if resolved is None:
        raise HTTPException(status_code=409, detail="request is absent or no longer pending")
    return JSONResponse(
        {"resolved": True, "request": resolved},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/perception/egress/execute")
async def perception_egress_execute(req: Request) -> JSONResponse:
    """Consume one approval for the same operation and exact image bytes."""
    _require_creator_request(req)
    body = await _read_bounded_json_object(req, max_bytes=3 * 1024 * 1024)
    request_id = body.get("request_id")
    operation_id = body.get("operation_id")
    route_id = body.get("route_id")
    if not all(isinstance(value, str) and value for value in (request_id, operation_id, route_id)):
        raise HTTPException(status_code=400, detail="request_id, operation_id, and route_id required")
    inspected = _ingest_egress_image(body.get("image"), operation_id)
    try:
        authority, gate = _perception_egress_components()
        staged = authority.get(request_id)
        if staged is None or staged.get("state") != "approved":
            raise HTTPException(status_code=403, detail="fresh creator approval required")
        if staged.get("route_id") != route_id:
            raise HTTPException(status_code=409, detail="approved route mismatch")
        result = await asyncio.to_thread(
            vision.describe_image_via_consent,
            inspected.image_bytes,
            gate=gate,
            route_id=route_id,
            operation_id=operation_id,
            provider=str(staged["provider"]),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(
            status_code=409,
            detail="exact approval mismatch or provider attempt failed",
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        {
            "described": True,
            "description": result.text,
            "vision_processing": {
                "backend": result.backend,
                "processing_location": result.processing_location,
                "cloud_egress": result.cloud_egress,
            },
            "image": inspected.as_dict(),
            "payload_retained": False,
        },
        headers={"Cache-Control": "no-store"},
    )


def _notification_json(
    payload: Mapping[str, object], *, status_code: int = 200
) -> JSONResponse:
    return JSONResponse(
        dict(payload),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _notification_runtime_component(
    runtime: Mapping[str, object], name: str, expected_type: type
):
    value = runtime.get(name)
    if not isinstance(value, expected_type):
        raise _NotificationRuntimeUnavailable
    return value


@app.get("/notifications/push/status")
def notification_push_status(req: Request) -> JSONResponse:
    """Return creator-only, destination-free Web Push readiness."""
    _require_creator_request(req)
    try:
        runtime = _notification_runtime()
        store = _notification_runtime_component(
            runtime, "store", web_push_runtime_mod.WebPushPrivateStore
        )
        outbox = _notification_runtime_component(
            runtime, "outbox", notification_outbox_mod.NotificationOutbox
        )
        vapid = _notification_runtime_component(
            runtime, "vapid", web_push_runtime_mod.VapidMaterial
        )
        private_status = store.public_status()
        ledger_status = outbox.public_status()
    except Exception:
        return _notification_json(
            {
                "available": False,
                "configured": False,
                "reason": "notification runtime unavailable",
            }
        )
    return _notification_json(
        {
            "available": True,
            "configured": True,
            "ready": True,
            "application_server_key": vapid.public_key,
            "subscription_count": private_status["subscription_count"],
            "subscription_cap": private_status["subscription_cap"],
            "template_scope": private_status["template_scope"],
            "outbox": ledger_status,
            "acknowledgement": "explicit_notification_click",
            "autonomous_triggers": False,
        }
    )


@app.post("/notifications/push/subscription")
async def notification_push_subscribe(req: Request) -> JSONResponse:
    """Enroll one creator browser subscription after explicit browser consent."""
    _require_creator_request(req)
    body = await _read_bounded_json_object(req, max_bytes=4096)
    if frozenset(body) != {"subscription"} or type(body["subscription"]) is not dict:
        raise HTTPException(
            status_code=400,
            detail="subscription body has wrong shape",
            headers={"Cache-Control": "no-store"},
        )
    supplied = body["subscription"]
    allowed = frozenset({"endpoint", "keys", "expirationTime"})
    if not {"endpoint", "keys"}.issubset(supplied) or not frozenset(supplied).issubset(allowed):
        raise HTTPException(
            status_code=400,
            detail="subscription has wrong shape",
            headers={"Cache-Control": "no-store"},
        )
    expiration = supplied.get("expirationTime")
    if expiration is not None and (
        isinstance(expiration, bool)
        or not isinstance(expiration, (int, float))
        or not math.isfinite(float(expiration))
        or float(expiration) <= 0
    ):
        raise HTTPException(
            status_code=400,
            detail="subscription expiration is invalid",
            headers={"Cache-Control": "no-store"},
        )
    try:
        runtime = _notification_runtime()
        store = _notification_runtime_component(
            runtime, "store", web_push_runtime_mod.WebPushPrivateStore
        )
        store.register_subscription(
            {"endpoint": supplied.get("endpoint"), "keys": supplied.get("keys")}
        )
    except (web_push_adapter_mod.WebPushAdapterError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="notification runtime unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    return _notification_json({"subscribed": True})


@app.delete("/notifications/push/subscription")
async def notification_push_unsubscribe(req: Request) -> JSONResponse:
    """Revoke only the exact creator browser endpoint supplied by PushManager."""
    _require_creator_request(req)
    body = await _read_bounded_json_object(req, max_bytes=2300)
    if frozenset(body) != {"endpoint"}:
        raise HTTPException(
            status_code=400,
            detail="endpoint body has wrong shape",
            headers={"Cache-Control": "no-store"},
        )
    try:
        runtime = _notification_runtime()
        store = _notification_runtime_component(
            runtime, "store", web_push_runtime_mod.WebPushPrivateStore
        )
        removed = store.revoke_endpoint(body["endpoint"])
    except (web_push_adapter_mod.WebPushAdapterError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="notification runtime unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    return _notification_json({"subscribed": False, "removed": bool(removed)})


@app.post("/notifications/push/test")
async def notification_push_test(req: Request) -> JSONResponse:
    """Send one fixed creator-requested connection test through the outbox."""
    _require_creator_request(req)
    body = await _read_bounded_json_object(req, max_bytes=64)
    if body:
        raise HTTPException(
            status_code=400,
            detail="connection test accepts no options",
            headers={"Cache-Control": "no-store"},
        )
    try:
        runtime = _notification_runtime()
        store = _notification_runtime_component(
            runtime, "store", web_push_runtime_mod.WebPushPrivateStore
        )
        outbox = _notification_runtime_component(
            runtime, "outbox", notification_outbox_mod.NotificationOutbox
        )
        adapter = _notification_runtime_component(
            runtime, "adapter", web_push_adapter_mod.WebPushAdapter
        )

        def perform_connection_test() -> dict[str, object]:
            if not store.subscriptions():
                return {
                    "queued": False,
                    "reason": "no creator browser subscription",
                }
            ledger = outbox.public_status()
            states = ledger["states"]
            unresolved = {
                state: int(states[state])
                for state in (
                    notification_outbox_mod.LEASED,
                    notification_outbox_mod.INDETERMINATE,
                    notification_outbox_mod.SENT,
                )
                if int(states[state]) > 0
            }
            if unresolved:
                return {
                    "queued": False,
                    "reason": "an earlier connection test is unresolved",
                    "states": unresolved,
                }
            if int(states[notification_outbox_mod.QUEUED]) > 0:
                delivery = adapter.deliver_one()
                return {
                    "queued": False,
                    "reason": "retried the existing connection test",
                    "delivery": delivery,
                }
            event = web_push_runtime_mod.enqueue_connection_test(outbox, store)
            delivery = adapter.deliver_one()
            return {
                "queued": True,
                "event_id": event["event_id"],
                "delivery": delivery,
            }

        def enqueue_and_deliver() -> dict[str, object]:
            mutex = _notification_test_operation_mutex()
            try:
                with mutex.locked(timeout_ms=0):
                    return perform_connection_test()
            except notification_anchor_mod.CrossProcessMutexTimeout:
                return {"busy": True}

        result = await _bounded_thread(
            "notification_push_test",
            enqueue_and_deliver,
            timeout=25.0,
        )
    except notification_outbox_mod.NotificationOutboxError as exc:
        raise HTTPException(
            status_code=409,
            detail="notification outbox rejected the connection test",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="notification delivery unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if result is None:
        return _notification_json(
            {"queued": False, "in_progress": True}, status_code=202
        )
    if result.get("busy"):
        return _notification_json(
            {"queued": False, "in_progress": True}, status_code=409
        )
    if result.get("reason") == "no creator browser subscription":
        return _notification_json(result, status_code=409)
    if result.get("states"):
        return _notification_json(result, status_code=409)
    return _notification_json(result)


@app.post("/notifications/push/ack")
async def notification_push_acknowledge(req: Request) -> JSONResponse:
    """Consume one click receipt before acknowledging durable sent evidence."""
    _require_creator_request(req)
    body = await _read_bounded_json_object(req, max_bytes=768)
    if frozenset(body) != {"event_id", "receipt"}:
        raise HTTPException(
            status_code=400,
            detail="acknowledgement body has wrong shape",
            headers={"Cache-Control": "no-store"},
        )
    try:
        runtime = _notification_runtime()
        adapter = _notification_runtime_component(
            runtime, "adapter", web_push_adapter_mod.WebPushAdapter
        )
        def acknowledge_once() -> dict[str, object]:
            if not _NOTIFICATION_ACK_OPERATION_LOCK.acquire(blocking=False):
                return {"busy": True}
            try:
                return adapter.acknowledge(
                    event_id=body["event_id"],
                    receipt=body["receipt"],
                )
            finally:
                _NOTIFICATION_ACK_OPERATION_LOCK.release()

        status = await _bounded_thread(
            "notification_push_ack",
            acknowledge_once,
            timeout=5.0,
        )
    except web_push_adapter_mod.WebPushAdapterError as exc:
        raise HTTPException(
            status_code=403,
            detail="acknowledgement receipt rejected",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except notification_outbox_mod.OutboxStateError as exc:
        raise HTTPException(
            status_code=409,
            detail="notification is not ready for acknowledgement",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="notification acknowledgement unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if status is None:
        return _notification_json(
            {"acknowledged": False, "in_progress": True}, status_code=202
        )
    if status.get("busy"):
        return _notification_json(
            {"acknowledged": False, "in_progress": True}, status_code=409
        )
    return _notification_json(
        {"acknowledged": status["state"] == notification_outbox_mod.ACKNOWLEDGED}
    )


def _require_discord_bridge_request(req: Request) -> auth_mod.AuthDecision:
    decision = getattr(req.state, "authorization", None)
    if not isinstance(decision, auth_mod.AuthDecision) or not decision.allowed:
        raise HTTPException(
            status_code=401,
            detail="Discord bridge authorization required",
            headers={"Cache-Control": "no-store"},
        )
    if (
        decision.mechanism != "service_bearer"
        or decision.principal != "service:discord-bridge"
    ):
        raise HTTPException(
            status_code=403,
            detail="Discord bridge service required",
            headers={"Cache-Control": "no-store"},
        )
    return decision


def _raise_discord_actor_denied() -> NoReturn:
    raise HTTPException(
        status_code=403,
        detail={"code": "discord_actor_denied"},
        headers={"Cache-Control": "no-store"},
    )


def _raise_discord_actor_store_unavailable() -> NoReturn:
    raise HTTPException(
        status_code=503,
        detail={"code": "discord_actor_identity_unavailable"},
        headers={"Cache-Control": "no-store"},
    )


_DISCORD_ACTOR_UNAVAILABLE_ERRORS = (
    _DiscordActorStoreUnavailable,
    bridge_actor_identity_mod.BridgeActorIntegrityError,
    bridge_actor_identity_mod.BridgeActorClockError,
    sqlite3.DatabaseError,
    OSError,
)


async def _verified_discord_actor_request(
    req: Request,
) -> tuple[
    dict[str, object],
    bridge_actor_identity_mod.VerifiedGuestActor,
    bridge_actor_transport_mod.DiscordActorBindings,
]:
    """Authenticate exact request bytes before any Discord turn side effect."""
    _require_discord_bridge_request(req)
    try:
        bindings = bridge_actor_transport_mod.parse_binding_headers(req.headers)
        envelope = bridge_actor_transport_mod.parse_envelope_header(req.headers)
    except bridge_actor_transport_mod.DiscordActorHeaderError:
        _raise_discord_actor_denied()

    raw_body = await _read_bounded_body(
        req,
        max_bytes=bridge_actor_transport_mod.MAX_DISCORD_BODY_BYTES,
    )
    payload = _parse_json_object(raw_body)
    try:
        verification = await asyncio.to_thread(
            _verify_discord_actor_envelope,
            envelope,
            raw_body,
            bindings,
        )
    except _DISCORD_ACTOR_UNAVAILABLE_ERRORS:
        _raise_discord_actor_store_unavailable()
    except bridge_actor_identity_mod.BridgeActorIdentityError:
        _raise_discord_actor_denied()
    actor = verification.actor
    if not verification.accepted or actor is None:
        _raise_discord_actor_denied()
    return payload, actor, bindings


def _capability_lease_http_status(reason: str) -> int:
    if reason == "lease_expired":
        return 410
    if reason == "byte_cap_exceeded":
        return 413
    if reason in {
        "active_lease_exists", "lease_stopped", "use_cap_reached",
    }:
        return 409
    if reason in {
        "purpose_not_allowed", "resource_binding_required",
        "resource_binding_not_allowed", "malformed_request",
    }:
        return 400
    return 403


def _raise_capability_lease_denied(reason: str) -> None:
    raise HTTPException(
        status_code=_capability_lease_http_status(str(reason or "lease_denied")),
        detail={
            "code": "capability_lease_denied",
            "reason": str(reason or "lease_denied")[:80],
        },
        headers={"Cache-Control": "no-store"},
    )


def _require_capability_lease_recovery() -> None:
    if not _capability_lease_recovery_ready.is_set():
        raise HTTPException(
            status_code=503,
            detail={"code": "capability_lease_recovery_unavailable"},
            headers={"Cache-Control": "no-store"},
        )


def _capability_connection_surface(connection_id: str) -> str:
    active = _active_ws_portal
    if active is None or not isinstance(connection_id, str) or not connection_id:
        return ""
    socket, epoch = active
    if not (
        _constant_time_text_equal(epoch, connection_id)
        and _ws_portal_epochs.get(socket) == epoch
    ):
        return ""
    surface = _websocket_route_surface(socket)
    return surface if surface in {"house-hq", "websocket"} else ""


def _constant_time_text_equal(left: str, right: str) -> bool:
    """Constant-time compare for opaque server-issued connection ids."""
    import hmac
    try:
        return hmac.compare_digest(str(left), str(right))
    except TypeError:
        return False


def _source_ref_lease_binding(root_id: str, relative_path: str) -> str:
    return json.dumps(
        {"rel": relative_path, "root": root_id},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _capability_lease_request_headers(
    req: Request,
    *,
    purpose: str,
    required_surface: str = "",
) -> tuple[str, str, str]:
    token = req.headers.get(capability_leases_mod.TOKEN_HEADER, "").strip()
    claimed_purpose = req.headers.get(
        capability_leases_mod.PURPOSE_HEADER, ""
    ).strip()
    connection_id = req.headers.get(
        capability_leases_mod.CONNECTION_HEADER, ""
    ).strip()
    if not token or not claimed_purpose or not connection_id:
        _raise_capability_lease_denied("lease_required")
    if claimed_purpose != purpose:
        _raise_capability_lease_denied("purpose_mismatch")
    surface = _capability_connection_surface(connection_id)
    if not surface or (required_surface and surface != required_surface):
        try:
            _capability_lease_store.stop_connection(
                connection_id,
                reason="connection_inactive",
            )
        except Exception:
            pass
        _raise_capability_lease_denied("connection_not_active")
    return token, connection_id, surface


async def _capability_lease_store_call(method, /, *args, **kwargs):
    _require_capability_lease_recovery()
    try:
        return await asyncio.to_thread(method, *args, **kwargs)
    except capability_leases_mod.CapabilityLeaseDenied as exc:
        detail = {
            "code": "capability_lease_denied",
            "reason": str(exc.reason or "lease_denied")[:80],
        }
        receipt_id = getattr(exc, "receipt_id", None)
        if isinstance(receipt_id, int) and receipt_id > 0:
            detail["receipt_id"] = receipt_id
        raise HTTPException(
            status_code=_capability_lease_http_status(exc.reason),
            detail=detail,
            headers={"Cache-Control": "no-store"},
        )
    except capability_leases_mod.CapabilityLeaseIntegrityError:
        _capability_lease_recovery_ready.clear()
        raise HTTPException(
            status_code=503,
            detail={"code": "capability_lease_integrity_unavailable"},
            headers={"Cache-Control": "no-store"},
        )
    except capability_leases_mod.CapabilityLeaseError:
        _raise_capability_lease_denied("malformed_request")
    except Exception:
        _capability_lease_recovery_ready.clear()
        raise HTTPException(
            status_code=503,
            detail={"code": "capability_lease_store_unavailable"},
            headers={"Cache-Control": "no-store"},
        )


async def _consume_request_capability_lease(
    req: Request,
    *,
    purpose: str,
    bytes_used: int,
    byte_accounting: str = "measured",
    resource_binding: str | None = None,
    required_surface: str = "",
) -> dict[str, object]:
    token, connection_id, surface = _capability_lease_request_headers(
        req,
        purpose=purpose,
        required_surface=required_surface,
    )
    return await _capability_lease_store_call(
        _capability_lease_store.consume,
        token,
        connection_id=connection_id,
        principal="creator",
        privacy_scope="creator-personal",
        surface=surface,
        purpose=purpose,
        bytes_used=bytes_used,
        byte_accounting=byte_accounting,
        resource_binding=resource_binding,
    )


async def _validate_request_capability_lease(
    req: Request,
    *,
    purpose: str,
    required_surface: str = "",
) -> dict[str, object]:
    token, connection_id, surface = _capability_lease_request_headers(
        req,
        purpose=purpose,
        required_surface=required_surface,
    )
    return await _capability_lease_store_call(
        _capability_lease_store.validate_active,
        token,
        connection_id=connection_id,
        principal="creator",
        privacy_scope="creator-personal",
        surface=surface,
        purpose=purpose,
    )


async def _consume_ws_capability_lease(
    message: Mapping[str, object],
    *,
    portal_epoch: str,
    purpose: str,
    bytes_used: int,
) -> dict[str, object]:
    token = message.get("capability_lease")
    claimed_purpose = message.get("capability_purpose")
    claimed_connection = message.get("capability_connection")
    if (
        not isinstance(token, str)
        or not token.strip()
        or claimed_purpose != purpose
        or claimed_connection != portal_epoch
    ):
        _raise_capability_lease_denied("lease_required")
    surface = _capability_connection_surface(portal_epoch)
    if not surface:
        _raise_capability_lease_denied("connection_not_active")
    return await _capability_lease_store_call(
        _capability_lease_store.consume,
        token.strip(),
        connection_id=portal_epoch,
        principal="creator",
        privacy_scope="creator-personal",
        surface=surface,
        purpose=purpose,
        bytes_used=bytes_used,
        byte_accounting="measured",
    )


async def _validate_ws_capability_lease(
    message: Mapping[str, object],
    *,
    portal_epoch: str,
    purpose: str,
) -> dict[str, object]:
    token = message.get("capability_lease")
    claimed_purpose = message.get("capability_purpose")
    claimed_connection = message.get("capability_connection")
    if (
        not isinstance(token, str)
        or not token.strip()
        or claimed_purpose != purpose
        or claimed_connection != portal_epoch
    ):
        _raise_capability_lease_denied("lease_required")
    surface = _capability_connection_surface(portal_epoch)
    if not surface:
        _raise_capability_lease_denied("connection_not_active")
    return await _capability_lease_store_call(
        _capability_lease_store.validate_active,
        token.strip(),
        connection_id=portal_epoch,
        principal="creator",
        privacy_scope="creator-personal",
        surface=surface,
        purpose=purpose,
    )


@app.post("/security/capability-leases")
async def issue_capability_lease(req: Request, response: Response) -> dict:
    """Issue one short-lived grant bound to the current House connection."""
    decision = _require_creator_request(req)
    _require_capability_lease_recovery()
    response.headers["Cache-Control"] = "no-store"
    body = await _read_bounded_json_object(req, max_bytes=4096)
    purpose = body.get("purpose")
    connection_id = body.get("connection_id")
    if not isinstance(purpose, str) or not isinstance(connection_id, str):
        _raise_capability_lease_denied("malformed_request")
    purpose = purpose.strip()
    connection_id = connection_id.strip()
    surface = _capability_connection_surface(connection_id)
    if not surface:
        _raise_capability_lease_denied("connection_not_active")
    try:
        capability_leases_mod.policy_for(purpose)
    except capability_leases_mod.CapabilityLeaseDenied as exc:
        _raise_capability_lease_denied(exc.reason)
    if purpose in {"file_source_ref", "screen_share"} and surface != "house-hq":
        _raise_capability_lease_denied("surface_mismatch")

    resource_binding = None
    source_ref = body.get("source_ref")
    if purpose == "file_source_ref":
        root_id, relative_path = _parse_source_ref(source_ref)
        resource_binding = _source_ref_lease_binding(root_id, relative_path)
    elif source_ref is not None:
        _raise_capability_lease_denied("resource_binding_not_allowed")

    return await _capability_lease_store_call(
        _capability_lease_store.issue,
        connection_id=connection_id,
        principal=decision.principal,
        privacy_scope="creator-personal",
        surface=surface,
        purpose=purpose,
        auth_mechanism=decision.mechanism,
        auth_expires_at=decision.expires_at,
        resource_binding=resource_binding,
    )


@app.post("/security/capability-leases/{lease_id}/stop")
async def stop_capability_lease(
    lease_id: str,
    req: Request,
    response: Response,
) -> dict:
    """Explicitly stop a grant; repeated creator stops are harmless."""
    _require_creator_request(req)
    response.headers["Cache-Control"] = "no-store"
    body = await _read_bounded_json_object(req, max_bytes=1024)
    connection_id = body.get("connection_id")
    if not isinstance(connection_id, str) or not connection_id.strip():
        _raise_capability_lease_denied("malformed_request")
    public, stopped = await _capability_lease_store_call(
        _capability_lease_store.stop,
        lease_id,
        connection_id=connection_id.strip(),
        reason="client_stop",
    )
    return {"ok": True, "stopped": stopped, "lease": public}


@app.get("/security/capability-leases")
async def capability_lease_status(
    req: Request,
    response: Response,
    receipt_limit: int = 50,
) -> dict:
    """Return verified content-free lease policy and receipt evidence."""
    _require_creator_request(req)
    response.headers["Cache-Control"] = "no-store"
    if not 1 <= receipt_limit <= 100:
        raise HTTPException(status_code=422, detail="receipt_limit must be 1..100")
    return await _capability_lease_store_call(
        _capability_lease_store.status,
        receipt_limit=receipt_limit,
    )


def _behavior_trial_public_summary(record: Mapping[str, object]) -> dict:
    """Expose only the bounded trial facts needed by the creator-facing API."""
    spec = record.get("spec")
    if not isinstance(spec, Mapping):
        spec = {}
    return {
        "id": int(record["id"]),
        "scope": str(record["scope"]),
        "proposal_id": int(record["proposal_id"]),
        "state": str(record["state"]),
        "parameter": str(spec.get("parameter") or ""),
        "metric": str(spec.get("metric") or ""),
        "spec_sha256": str(record["spec_sha256"]),
    }


def _behavior_trial_profile_contract(record: Mapping[str, object]) -> dict:
    """Expose only the reviewed scalar values needed for an informed decision."""
    spec = record.get("spec")
    if not isinstance(spec, Mapping):
        raise ValueError("behavior trial specification is unavailable")
    return {
        "preimage_value": float(spec["old_value"]),
        "trial_value": float(spec["trial_value"]),
        "exposure_seconds": float(spec["exposure_seconds"]),
        "min_samples": int(spec["min_samples"]),
    }


def _behavior_trial_settlement_public_summary(settlement: Mapping[str, object]) -> dict:
    """Curate one frozen C7 settlement without raw records or proof material."""
    evidence = settlement.get("evidence")
    review = settlement.get("review")
    if not isinstance(evidence, Mapping) or not isinstance(review, Mapping):
        raise ValueError("settlement is missing its immutable evidence")
    evaluation = review.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise ValueError("settlement is missing its fixed evaluation")
    return {
        "contract_version": int(settlement["contract_version"]),
        "settled_at": float(settlement["settled_at"]),
        "status": str(settlement["status"]),
        "recommendation": str(settlement["recommendation"]),
        "outcome": str(settlement.get("outcome") or "inconclusive"),
        "creator_retention_eligible": bool(
            settlement.get("creator_retention_eligible") is True
        ),
        "creator_retention_reason": str(
            settlement.get("creator_retention_reason") or "insufficient_evidence"
        ),
        "evidence": {
            "metric": str(evidence["metric"]),
            "definition_version": int(evidence["definition_version"]),
            "trial_id": int(evidence["trial_id"]),
            "dispatching": int(evidence["dispatching"]),
            "pending": int(evidence["pending"]),
            "qualified_responses": int(evidence["qualified_responses"]),
            "unanswered": int(evidence["unanswered"]),
            "cancelled": int(evidence["cancelled"]),
            "completed": int(evidence["completed"]),
            "rate": evidence["rate"],
        },
        "evaluation": {
            "metric": str(evaluation["metric"]),
            "definition_version": int(evaluation["definition_version"]),
            "trial_id": int(evaluation["trial_id"]),
            "spec_sha256": str(evaluation["spec_sha256"]),
            "baseline": float(evaluation["baseline"]),
            "min_samples": int(evaluation["min_samples"]),
            "required_samples": int(
                evaluation.get("required_samples", evaluation["min_samples"])
            ),
            "effect_threshold": float(evaluation.get("effect_threshold", 0.0)),
            "qualified_responses": int(evaluation["qualified_responses"]),
            "unanswered": int(evaluation["unanswered"]),
            "completed": int(evaluation["completed"]),
            "dispatching": int(evaluation["dispatching"]),
            "pending": int(evaluation["pending"]),
            "cancelled": int(evaluation["cancelled"]),
            "rate": evaluation["rate"],
            "delta_from_baseline": evaluation["delta_from_baseline"],
            "readiness": str(evaluation["readiness"]),
            "comparison": evaluation["comparison"],
            "creator_retention_eligible": bool(
                evaluation.get("creator_retention_eligible") is True
            ),
        },
    }


def _behavior_trial_candidate_public_summary() -> dict | None:
    """Expose only a sealed candidate's lifecycle state to the creator UI."""
    candidate = behavior_trial_candidate_store.public_status()
    if candidate is None:
        return None
    summary = {
        "proposal_id": int(candidate["proposal_id"]),
        "state": str(candidate["state"]),
    }
    if summary["state"] != "registered":
        return summary
    trial_id = int(candidate["registered_trial_id"])
    if _behavior_trial_profile_ready.is_set():
        decided = behavior_trial_profile_store.get(trial_id)
        if decided is not None:
            # The sealed profile decision is the archival boundary for this
            # registered candidate. It remains in history but no longer blocks
            # the next bounded cycle.
            return None
    details = behavior_trial_candidate_store.registration_details(
        summary["proposal_id"],
        default_chatter_chance=behavior_trial_controller.default_chatter_chance,
    )
    current = behavior_trial_controller.get(trial_id)
    if current is None or not behavior_trial_candidate_store.matches_trial(
        current, details["spec"]
    ):
        raise behavior_trial_candidates_mod.CandidateIntegrityError(
            "registered candidate does not match its behavior trial"
        )
    rollback = current.get("rollback")
    if current.get("state") == "rolled_back" and isinstance(rollback, Mapping):
        if rollback.get("reason") != TRIAL_EXPIRATION_REASON:
            # Aborts, interrupted recovery, and integrity closures are terminal
            # but intentionally have no retain/revert settlement. Keep their
            # rows as history without stranding the next review-only candidate.
            return None
    summary["trial"] = _behavior_trial_public_summary(current)
    return summary


def _issue_behavior_trial_candidate_from_baseline() -> dict:
    """Turn settled low-response evidence into one reviewable candidate only."""
    try:
        existing = _behavior_trial_candidate_public_summary()
    except Exception:
        return {"issued": False, "reason": "candidate_unavailable"}
    if existing is not None and existing.get("state") == "registered":
        # C8 intentionally has no post-review decision path yet. Do not stack a
        # new candidate while the previously registered trial is still the one
        # waiting for approval, start, closure, or later creator review.
        return {"issued": False, "reason": "registration_pending"}
    if not _behavior_trial_profile_ready.is_set():
        return {"issued": False, "reason": "profile_unavailable"}
    try:
        profile = behavior_trial_profile_store.active_profile(
            behavior_trial_controller.default_chatter_chance
        )
        baseline = qualified_response_ledger.baseline_summary(
            since=profile.get("updated_at")
        )
    except Exception:
        return {"issued": False, "reason": "baseline_unavailable"}
    result = behavior_trial_candidate_store.issue_from_baseline(
        baseline,
        preimage_value=behavior_trial_controller.default_chatter_chance,
    )
    if result.get("issued") and not result.get("reused"):
        candidate = result.get("candidate") or {}
        proposal = result.get("proposal") or {}
        try:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="behavior_trial_candidate",
                content=(
                    "Recorded one bounded behavior-trial candidate from settled "
                    "proactive response evidence."
                ),
                confidence=1.0,
                privacy_class="local",
                metadata={
                    "proposal_id": int(proposal.get("id") or 0),
                    "candidate_id": int(candidate.get("id") or 0),
                    "scope": behavior_trial_candidates_mod.CREATOR_PERSONAL_SCOPE,
                    "parameter": behavior_trial_candidates_mod.PROFILE_PARAMETER,
                    "metric": behavior_trial_candidates_mod.PROFILE_METRIC,
                    "registered": False,
                    "started": False,
                },
            ))
        except Exception:
            # The candidate is already durable. Auxiliary observation failures
            # must not create another candidate or change behavior.
            pass
    return result


async def _reconcile_behavior_trial_candidate_once() -> dict:
    """Idempotently advance a fresh profile epoch when evidence becomes ready."""
    if (
        not _behavior_trial_recovery_ready.is_set()
        or not _behavior_trial_profile_ready.is_set()
    ):
        return {"issued": False, "reason": "recovery_pending"}
    try:
        result = await asyncio.to_thread(
            _issue_behavior_trial_candidate_from_baseline
        )
    except Exception:
        return {"issued": False, "reason": "candidate_unavailable"}
    return result if isinstance(result, dict) else {
        "issued": False,
        "reason": "candidate_unavailable",
    }


def _behavior_trial_proposal_id(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise ValueError("invalid behavior trial proposal")
    return int(value)


def _behavior_trial_id(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise ValueError("invalid behavior trial")
    return int(value)


async def _require_bodyless_behavior_trial_request(req: Request, *, action: str) -> None:
    """Reject browser-supplied trial data for one literal creator action."""
    if req.query_params:
        raise HTTPException(
            status_code=400,
            detail=f"{action} does not accept query parameters",
            headers={"Cache-Control": "no-store"},
        )
    if req.headers.get("transfer-encoding"):
        raise HTTPException(
            status_code=400,
            detail=f"{action} does not accept a request body",
            headers={"Cache-Control": "no-store"},
        )
    content_length = req.headers.get("content-length")
    if content_length not in {None, "", "0"} or await req.body():
        raise HTTPException(
            status_code=400,
            detail=f"{action} does not accept a request body",
            headers={"Cache-Control": "no-store"},
        )


def _behavior_trial_recovery_response() -> JSONResponse:
    return JSONResponse(
        {"detail": "behavior trial recovery is not ready"},
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/behavior-trials/status")
def behavior_trial_status(req: Request) -> JSONResponse:
    """Return the recovered controller's bounded, creator-only status snapshot."""
    _require_creator_request(req)
    if not _behavior_trial_recovery_ready.is_set():
        return _behavior_trial_recovery_response()
    snapshot = dict(behavior_trial_controller.status_snapshot())
    snapshot["outcome_evidence"] = qualified_response_ledger.summary()
    snapshot["profile_ready"] = _behavior_trial_profile_ready.is_set()
    snapshot["profile_error"] = _behavior_trial_profile_error
    if _behavior_trial_profile_ready.is_set():
        try:
            profile = behavior_trial_profile_store.active_profile(
                behavior_trial_controller.default_chatter_chance
            )
            snapshot["active_profile"] = profile
            snapshot["cycle_baseline"] = qualified_response_ledger.baseline_summary(
                since=profile.get("updated_at")
            )
            snapshot["profile_decisions"] = behavior_trial_profile_store.list(limit=5)
            snapshot["profile_decisions_available"] = True
        except Exception:
            snapshot["active_profile"] = None
            snapshot["cycle_baseline"] = None
            snapshot["profile_decisions"] = []
            snapshot["profile_decisions_available"] = False
    else:
        snapshot["active_profile"] = None
        snapshot["cycle_baseline"] = None
        snapshot["profile_decisions"] = []
        snapshot["profile_decisions_available"] = False
    try:
        stored_settlements = behavior_trial_settlement_mod.list_settlements(
            DB_PATH,
            limit=5,
        )
        review_settlements = []
        for stored in stored_settlements:
            public = dict(stored)
            try:
                trial_id = int(public["trial_id"])
                trial = behavior_trial_controller.get(trial_id)
                if trial is not None:
                    public["profile"] = _behavior_trial_profile_contract(trial)
            except Exception:
                public["profile"] = None
            review_settlements.append(public)
        snapshot["review_settlements"] = review_settlements
        snapshot["review_settlements_available"] = True
    except Exception:
        # Settlement storage is optional observational context for this status
        # surface. Do not fabricate an empty successful review history.
        snapshot["review_settlements"] = []
        snapshot["review_settlements_available"] = False
    try:
        snapshot["registration_candidate"] = _behavior_trial_candidate_public_summary()
        snapshot["registration_candidate_available"] = True
    except Exception:
        # A candidate is optional review context. Do not claim an empty, valid
        # candidate state when its sealed source or storage cannot be read.
        snapshot["registration_candidate"] = None
        snapshot["registration_candidate_available"] = False
    try:
        snapshot["review_decisions"] = behavior_trial_review_decision_store.list(limit=5)
        snapshot["review_decisions_available"] = True
    except Exception:
        # Frozen review evidence remains available even when the optional C9
        # receipt reader cannot verify its own storage.
        snapshot["review_decisions"] = []
        snapshot["review_decisions_available"] = False
    return JSONResponse(
        snapshot,
        headers={"Cache-Control": "no-store"},
    )


@app.post("/behavior-trials/proposals/{proposal_id}/register")
async def behavior_trial_creator_register(
    proposal_id: str,
    req: Request,
) -> JSONResponse:
    """Register one sealed server-issued candidate without approving or starting it."""
    decision = _require_creator_request(req)
    if not _behavior_trial_recovery_ready.is_set():
        return _behavior_trial_recovery_response()
    content_length = req.headers.get("content-length")
    if content_length not in {None, "", "0"}:
        raise HTTPException(
            status_code=400,
            detail="behavior trial registration does not accept a request body",
            headers={"Cache-Control": "no-store"},
        )
    if await req.body():
        raise HTTPException(
            status_code=400,
            detail="behavior trial registration does not accept a request body",
            headers={"Cache-Control": "no-store"},
        )
    try:
        proposal_key = _behavior_trial_proposal_id(proposal_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="invalid behavior trial proposal",
            headers={"Cache-Control": "no-store"},
        ) from exc
    try:
        details = behavior_trial_candidate_store.registration_details(
            proposal_key,
            default_chatter_chance=behavior_trial_controller.default_chatter_chance,
        )
    except behavior_trial_candidates_mod.CandidateNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="behavior trial candidate not found",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except behavior_trial_candidates_mod.BehaviorTrialCandidateError as exc:
        raise HTTPException(
            status_code=409,
            detail="behavior trial candidate cannot be registered",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial candidate storage unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc

    candidate = details["candidate"]
    spec = details["spec"]
    existing_trial_id = candidate.get("registered_trial_id")
    if isinstance(existing_trial_id, int) and not isinstance(existing_trial_id, bool):
        try:
            existing = behavior_trial_controller.get(existing_trial_id)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="behavior trial storage unavailable",
                headers={"Cache-Control": "no-store"},
            ) from exc
        if existing is None or not behavior_trial_candidate_store.matches_trial(existing, spec):
            raise HTTPException(
                status_code=409,
                detail="behavior trial candidate cannot be registered",
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            {
                "registered": True,
                "already_registered": True,
                "trial": _behavior_trial_public_summary(existing),
            },
            headers={"Cache-Control": "no-store"},
        )

    try:
        registered = behavior_trial_controller.register(spec)
    except ValueError as exc:
        # The controller still owns the allowlist and immutable trial ledger.
        # A registration failure cannot fall back to approval or a runtime write.
        raise HTTPException(
            status_code=409,
            detail="behavior trial candidate cannot be registered",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial registration unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if not behavior_trial_candidate_store.matches_trial(registered, spec):
        raise HTTPException(
            status_code=409,
            detail="behavior trial candidate cannot be registered",
            headers={"Cache-Control": "no-store"},
        )
    registered_at = _time.time()
    try:
        newly_registered = behavior_trial_candidate_store.mark_registered(
            proposal_key,
            trial_id=int(registered["id"]),
            principal=decision.principal,
            mechanism=decision.mechanism,
            registered_at=registered_at,
        )
    except behavior_trial_candidates_mod.BehaviorTrialCandidateError as exc:
        raise HTTPException(
            status_code=409,
            detail="behavior trial candidate cannot be registered",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial registration unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc

    summary = _behavior_trial_public_summary(registered)
    if newly_registered:
        try:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="behavior_trial_registration",
                content=(
                    f"Creator registered Alpecca behavior trial {summary['id']} for "
                    "bounded review."
                ),
                confidence=1.0,
                privacy_class="local",
                metadata={
                    "trial_id": summary["id"],
                    "proposal_id": summary["proposal_id"],
                    "scope": summary["scope"],
                    "parameter": summary["parameter"],
                    "metric": summary["metric"],
                    "authorization": decision.mechanism,
                    "registered_at": registered_at,
                    "approved": False,
                    "started": False,
                },
            ))
        except Exception:
            # Registration is already durable. An auxiliary observation must
            # not retry, approve, or start the newly registered trial.
            pass
    return JSONResponse(
        {
            "registered": True,
            "already_registered": not newly_registered,
            "trial": summary,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/behavior-trials/{trial_id}/approve")
def behavior_trial_creator_approve(trial_id: int, req: Request) -> JSONResponse:
    """Record one creator-triggered approval for an already validated trial.

    The protected server authorization decision supplies every approval fact;
    this endpoint accepts no browser-provided proof, timestamp, or mechanism.
    It intentionally does not start the approved trial.
    """
    decision = _require_creator_request(req)
    if not _behavior_trial_recovery_ready.is_set():
        return _behavior_trial_recovery_response()
    try:
        current = behavior_trial_controller.get(trial_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="invalid behavior trial",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial storage unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if current is None:
        raise HTTPException(
            status_code=404,
            detail="behavior trial not found",
            headers={"Cache-Control": "no-store"},
        )
    if current.get("state") not in {"registered", "approved"}:
        raise HTTPException(
            status_code=409,
            detail="only a registered or approved behavior trial can be creator-approved",
            headers={"Cache-Control": "no-store"},
        )
    approved_at = _time.time()
    try:
        updated = behavior_trial_controller.approve_creator(
            trial_id,
            principal=decision.principal,
            authorization_mechanism=decision.mechanism,
            authorization_issued_at=decision.issued_at,
            authorization_expires_at=decision.expires_at,
            approved_at=approved_at,
        )
    except ValueError as exc:
        # The controller validates exact spec/binding/state invariants. Its
        # failure must never start the trial or fall back to a generic approval.
        raise HTTPException(
            status_code=409,
            detail="behavior trial cannot be creator-approved",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial approval unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    summary = _behavior_trial_public_summary(updated)
    try:
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="behavior_trial_creator_approval",
            content=(
                f"Creator approved Alpecca behavior trial {summary['id']} for "
                "bounded evaluation."
            ),
            confidence=1.0,
            privacy_class="local",
            metadata={
                "trial_id": summary["id"],
                "scope": summary["scope"],
                "parameter": summary["parameter"],
                "metric": summary["metric"],
                "authorization": decision.mechanism,
                "approved_at": approved_at,
                "started": False,
            },
        ))
    except Exception:
        # Approval is already durable; an auxiliary audit failure must not
        # retry, widen, or start the trial.
        pass
    return JSONResponse(
        {"approved": True, "trial": summary},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/behavior-trials/{trial_id}/start")
def behavior_trial_creator_start(trial_id: int, req: Request) -> JSONResponse:
    """Start one already approved, creator-bound behavior trial.

    This requires a fresh protected creator request and a recovered controller.
    The route takes no browser-supplied runtime values or timestamps. A retry
    of the same running trial is idempotent and re-verifies its binding; no
    other state is eligible. It cannot approve, complete, or register a trial.
    """
    decision = _require_creator_request(req)
    if not _behavior_trial_recovery_ready.is_set():
        return _behavior_trial_recovery_response()
    try:
        current = behavior_trial_controller.get(trial_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="invalid behavior trial",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial storage unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if current is None:
        raise HTTPException(
            status_code=404,
            detail="behavior trial not found",
            headers={"Cache-Control": "no-store"},
        )
    current_state = current.get("state")
    if current_state not in {"approved", "running"}:
        raise HTTPException(
            status_code=409,
            detail="only an approved behavior trial or its running retry can be started",
            headers={"Cache-Control": "no-store"},
        )
    already_running = current_state == "running"
    try:
        updated = _run_behavior_trial_transition(
            behavior_trial_controller.start,
            trial_id,
        )
    except ValueError as exc:
        # The controller verifies the approval binding, exact preimage, and
        # runtime readback. A rejected start cannot fall back to a mutation.
        raise HTTPException(
            status_code=409,
            detail="behavior trial cannot be started",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial start unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    summary = _behavior_trial_public_summary(updated)
    try:
        started_at = float(updated["started_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial start result unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if not already_running:
        try:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="behavior_trial_creator_start",
                content=(
                    f"Creator started Alpecca behavior trial {summary['id']} for "
                    "bounded evaluation."
                ),
                confidence=1.0,
                privacy_class="local",
                metadata={
                    "trial_id": summary["id"],
                    "scope": summary["scope"],
                    "parameter": summary["parameter"],
                    "metric": summary["metric"],
                    "authorization": decision.mechanism,
                    "started_at": started_at,
                    "started": True,
                },
            ))
        except Exception:
            # Start is already durable; an auxiliary audit failure must not
            # retry, complete, or roll back the behavior trial.
            pass
    return JSONResponse(
        {
            "running": True,
            "already_running": already_running,
            "trial": summary,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/behavior-trials/{trial_id}/abort")
async def behavior_trial_creator_abort(trial_id: str, req: Request) -> JSONResponse:
    """Restore the profile and close one started trial as inconclusive."""
    authorization = _require_creator_request(req)
    if not _behavior_trial_recovery_ready.is_set():
        return _behavior_trial_recovery_response()
    await _require_bodyless_behavior_trial_request(
        req,
        action="behavior trial abort",
    )
    try:
        trial_key = _behavior_trial_id(trial_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="invalid behavior trial",
            headers={"Cache-Control": "no-store"},
        ) from exc
    try:
        closed = _run_behavior_trial_transition(
            behavior_trial_controller.abort,
            trial_key,
            "creator requested an early stop",
            actor="creator",
        )
        already_aborted = closed.get("already_aborted") is True
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(
            status_code=409,
            detail="behavior trial cannot be aborted from its current state",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial abort storage unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    rollback = closed.get("rollback")
    if not isinstance(rollback, Mapping) or rollback.get("reason") != TRIAL_ABORT_REASON:
        raise HTTPException(
            status_code=409,
            detail="behavior trial was already closed by another outcome",
            headers={"Cache-Control": "no-store"},
        )
    if not already_aborted:
        try:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="behavior_trial_creator_abort",
                content=f"Creator stopped Alpecca behavior trial {trial_key} early.",
                confidence=1.0,
                privacy_class="local",
                metadata={
                    "trial_id": trial_key,
                    "scope": "creator-personal",
                    "decision": "abort_inconclusive",
                    "authorization": authorization.mechanism,
                    "restored_value": float(rollback["restored_value"]),
                    "runtime_change": not already_aborted,
                },
            ))
        except Exception:
            pass
    return JSONResponse(
        {
            "aborted": True,
            "already_aborted": already_aborted,
            "trial_id": trial_key,
            "state": str(closed.get("state") or "rolled_back"),
            "outcome": "inconclusive",
            "restored_value": float(rollback["restored_value"]),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/behavior-trials/{trial_id}/review")
def behavior_trial_creator_review(trial_id: int, req: Request) -> JSONResponse:
    """Read one immutable C7 settlement; never evaluate live evidence on demand."""
    _require_creator_request(req)
    if not _behavior_trial_recovery_ready.is_set():
        return _behavior_trial_recovery_response()
    try:
        current = behavior_trial_controller.get(trial_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="invalid behavior trial",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial storage unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if current is None:
        raise HTTPException(
            status_code=404,
            detail="behavior trial not found",
            headers={"Cache-Control": "no-store"},
        )
    if current.get("state") != "rolled_back":
        raise HTTPException(
            status_code=409,
            detail="behavior trial has not reached a reviewable closure",
            headers={"Cache-Control": "no-store"},
        )
    try:
        settlement = behavior_trial_settlement_mod.get_settlement(trial_id, DB_PATH)
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial settlement unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial settlement unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if settlement is None:
        raise HTTPException(
            status_code=409,
            detail="behavior trial has not settled for creator review",
            headers={"Cache-Control": "no-store"},
        )
    try:
        if (
            settlement.get("trial_id") != trial_id
            or settlement.get("spec_sha256") != current.get("spec_sha256")
            or settlement.get("scope") != current.get("scope")
        ):
            raise ValueError("settlement does not match the immutable trial")
        review = _behavior_trial_settlement_public_summary(settlement)
        review["profile"] = _behavior_trial_profile_contract(current)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial settlement is invalid",
            headers={"Cache-Control": "no-store"},
        ) from exc
    decision_record = None
    decision_available = True
    try:
        stored_decision = behavior_trial_review_decision_store.get(trial_id)
        if stored_decision is not None:
            if not isinstance(stored_decision, Mapping):
                raise ValueError("review decision is not a mapping")
            decision_record = {
                "trial_id": int(stored_decision["trial_id"]),
                "decision": str(stored_decision["decision"]),
                "decided_at": float(stored_decision["decided_at"]),
                "settlement_status": str(stored_decision["settlement_status"]),
            }
            if (
                decision_record["trial_id"] != trial_id
                or decision_record["decision"]
                != behavior_trial_review_decisions_mod.RETAIN_BASELINE
                or decision_record["settlement_status"] != review["status"]
            ):
                raise ValueError("review decision does not match frozen settlement")
    except Exception:
        # C9 acknowledgement storage is supplemental review metadata. A read
        # failure must not fabricate an absent decision or hide the C7 snapshot.
        decision_record = None
        decision_available = False
    return JSONResponse(
        {
            "trial": _behavior_trial_public_summary(current),
            "review": review,
            "decision": decision_record,
            "decision_available": decision_available,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/behavior-trials/{trial_id}/review/retain-baseline")
async def behavior_trial_creator_retain_baseline(
    trial_id: str,
    req: Request,
) -> JSONResponse:
    """Compatibility alias for the bounded revert-to-baseline decision."""
    return await behavior_trial_creator_profile_decision(
        trial_id,
        behavior_trial_profile_mod.REVERT_TO_BASELINE,
        req,
    )

    # Kept below for one release as inert migration context for older C9 data.
    # New requests never execute this acknowledgement-only path.
    decision = _require_creator_request(req)
    if not _behavior_trial_recovery_ready.is_set():
        return _behavior_trial_recovery_response()
    await _require_bodyless_behavior_trial_request(
        req,
        action="behavior trial review acknowledgement",
    )
    try:
        trial_key = _behavior_trial_id(trial_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="invalid behavior trial",
            headers={"Cache-Control": "no-store"},
        ) from exc
    try:
        current = behavior_trial_controller.get(trial_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="invalid behavior trial",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial storage unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if current is None:
        raise HTTPException(
            status_code=404,
            detail="behavior trial not found",
            headers={"Cache-Control": "no-store"},
        )
    if current.get("state") != "rolled_back":
        raise HTTPException(
            status_code=409,
            detail="behavior trial has not reached a reviewable closure",
            headers={"Cache-Control": "no-store"},
        )
    try:
        settlement = behavior_trial_settlement_mod.get_settlement(trial_key, DB_PATH)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial settlement unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if settlement is None:
        raise HTTPException(
            status_code=409,
            detail="behavior trial has not settled for creator review",
            headers={"Cache-Control": "no-store"},
        )
    try:
        settlement_status = str(settlement["status"])
        if (
            settlement.get("trial_id") != trial_key
            or settlement.get("spec_sha256") != current.get("spec_sha256")
            or settlement.get("scope") != current.get("scope")
            or settlement_status not in {
                "ready_for_creator_review",
                "inconclusive_insufficient_samples",
            }
        ):
            raise ValueError("settlement does not match a reviewable trial")
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail="behavior trial review cannot be recorded",
            headers={"Cache-Control": "no-store"},
        ) from exc
    decided_at = _time.time()
    try:
        receipt, created = behavior_trial_review_decision_store.acknowledge(
            trial_key,
            principal=decision.principal,
            authorization_mechanism=decision.mechanism,
            authorization_issued_at=decision.issued_at,
            authorization_expires_at=decision.expires_at,
            decided_at=decided_at,
        )
        if not isinstance(receipt, Mapping) or not isinstance(created, bool):
            raise ValueError("review decision storage returned an invalid receipt")
        public_receipt = {
            "trial_id": int(receipt["trial_id"]),
            "decision": str(receipt["decision"]),
            "decided_at": float(receipt["decided_at"]),
            "settlement_status": str(receipt["settlement_status"]),
        }
        if (
            public_receipt["trial_id"] != trial_key
            or public_receipt["decision"]
            != behavior_trial_review_decisions_mod.RETAIN_BASELINE
            or public_receipt["settlement_status"] != settlement_status
        ):
            raise ValueError("review decision receipt does not match settlement")
    except behavior_trial_review_decisions_mod.BehaviorTrialReviewDecisionError as exc:
        raise HTTPException(
            status_code=409,
            detail="behavior trial review cannot be recorded",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial review storage unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    summary = _behavior_trial_public_summary(current)
    if created:
        try:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="behavior_trial_creator_review_decision",
                content=(
                    f"Creator recorded baseline retention after frozen review of "
                    f"Alpecca behavior trial {summary['id']}."
                ),
                confidence=1.0,
                privacy_class="local",
                metadata={
                    "trial_id": summary["id"],
                    "scope": summary["scope"],
                    "parameter": summary["parameter"],
                    "metric": summary["metric"],
                    "settlement_status": settlement_status,
                    "decision": behavior_trial_review_decisions_mod.RETAIN_BASELINE,
                    "authorization": decision.mechanism,
                    "runtime_change": False,
                },
            ))
        except Exception:
            # The acknowledgement is already durable. An auxiliary audit failure
            # must not retry or create any behavior change.
            pass
    return JSONResponse(
        {
            "recorded": True,
            "already_recorded": not created,
            "decision": public_receipt,
            "trial": summary,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/behavior-trials/{trial_id}/review/decision/{decision_name}")
async def behavior_trial_creator_profile_decision(
    trial_id: str,
    decision_name: str,
    req: Request,
) -> JSONResponse:
    """Commit one creator-reviewed value, then open a fresh evidence epoch."""
    authorization = _require_creator_request(req)
    if not _behavior_trial_recovery_ready.is_set():
        return _behavior_trial_recovery_response()
    if not _behavior_trial_profile_ready.is_set():
        raise HTTPException(
            status_code=503,
            detail="behavior trial profile is unavailable",
            headers={"Cache-Control": "no-store"},
        )
    await _require_bodyless_behavior_trial_request(
        req,
        action="behavior trial profile decision",
    )
    try:
        trial_key = _behavior_trial_id(trial_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="invalid behavior trial",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if decision_name not in {
        behavior_trial_profile_mod.RETAIN_TRIAL_VALUE,
        behavior_trial_profile_mod.REVERT_TO_BASELINE,
    }:
        raise HTTPException(
            status_code=400,
            detail="invalid behavior trial profile decision",
            headers={"Cache-Control": "no-store"},
        )
    def commit_profile_decision():
        previous = float(behavior_trial_controller.default_chatter_chance)
        stored_receipt, was_created = behavior_trial_profile_store.decide(
            trial_key,
            decision=decision_name,
            expected_current_value=previous,
            principal=authorization.principal,
            authorization_mechanism=authorization.mechanism,
            authorization_issued_at=authorization.issued_at,
            authorization_expires_at=authorization.expires_at,
        )
        profile = behavior_trial_profile_store.active_profile(previous)
        behavior_trial_controller.adopt_profile_chatter_chance(
            float(profile["value"]),
            generation_token=_behavior_profile_generation(profile),
        )
        return stored_receipt, was_created, profile, previous

    try:
        receipt, created, active_profile, previous_profile_value = (
            _run_behavior_trial_transition(commit_profile_decision)
        )
    except behavior_trial_profile_mod.ProfileDecisionNotEligible as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except behavior_trial_profile_mod.BehaviorTrialProfileError as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial profile decision failed integrity checks",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="behavior trial profile storage unavailable",
            headers={"Cache-Control": "no-store"},
        ) from exc
    if created:
        try:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="behavior_trial_profile_decision",
                content=(
                    f"Creator completed Alpecca behavior trial {trial_key} with "
                    f"the decision {decision_name}."
                ),
                confidence=1.0,
                privacy_class="local",
                metadata={
                    "trial_id": trial_key,
                    "scope": behavior_trial_profile_mod.CREATOR_PERSONAL_SCOPE,
                    "parameter": behavior_trial_profile_mod.PROFILE_PARAMETER,
                    "decision": decision_name,
                    "applied_value": float(receipt["applied_value"]),
                    "authorization": authorization.mechanism,
                    "runtime_change": (
                        float(receipt["applied_value"]) != previous_profile_value
                    ),
                    "source_write": False,
                    "system_change": False,
                },
            ))
        except Exception:
            pass
    try:
        next_cycle = _issue_behavior_trial_candidate_from_baseline()
    except Exception:
        next_cycle = {"issued": False, "reason": "candidate_unavailable"}
    return JSONResponse(
        {
            "recorded": True,
            "already_recorded": not created,
            "decision": receipt,
            "active_profile": active_profile,
            "next_cycle": {
                "issued": bool(next_cycle.get("issued")),
                "reused": bool(next_cycle.get("reused")),
                "reason": str(next_cycle.get("reason") or ""),
            },
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/commitments")
def commitment_list(req: Request, state: str | None = None, limit: int = 50) -> dict:
    """List CreatorJD's durable action commitments and their receipts."""
    _require_creator_request(req)
    try:
        rows = commitments_mod.list_commitments(
            scope=CREATOR_COMMITMENT_SCOPE,
            state=state,
            limit=max(1, min(100, int(limit))),
        )
    except commitments_mod.CommitmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "commitments": rows,
        "executable_tools": sorted(commitment_executor_mod.ALLOWED_TOOLS),
    }


@app.post("/commitments")
async def commitment_create(req: Request) -> dict:
    """Create one allowlisted, payload-backed Workshop commitment.

    Stage 4 deliberately exposes only the read-only self-status operation. The
    server owns its wording and payload; arbitrary prose cannot become code.
    """
    decision = _require_creator_request(req)
    try:
        body = await req.json()
    except Exception:
        body = {}
    tool = str(body.get("tool") or commitment_executor_mod.SELF_STATUS_TOOL)
    args = body.get("args") or {}
    try:
        payload = commitment_executor_mod.build_payload(tool, args)
        existing = commitments_mod.list_commitments(
            scope=CREATOR_COMMITMENT_SCOPE,
            limit=50,
        )
        for item in existing:
            if (
                item.get("state") not in commitments_mod.TERMINAL_STATES
                and item.get("payload") == payload
            ):
                return {"created": False, "commitment": item}
        created = commitments_mod.create_commitment(
            "Check my current scoped self status",
            scope=CREATOR_COMMITMENT_SCOPE,
            evidence={
                "source": "creator_workshop",
                "principal": decision.principal,
                "authorization": decision.mechanism,
            },
            payload=payload,
        )
    except commitments_mod.CommitmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except commitment_executor_mod.CommitmentExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"created": True, "commitment": created}


@app.post("/commitments/{commitment_id}/approve")
def commitment_approve(commitment_id: int, req: Request) -> dict:
    """Apply CreatorJD's explicit approval without running the action."""
    decision = _require_creator_request(req)
    current = commitments_mod.get_commitment(
        commitment_id,
        scope=CREATOR_COMMITMENT_SCOPE,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="commitment not found")
    if current.get("state") == commitments_mod.APPROVED:
        return {"approved": False, "commitment": current}
    if current.get("state") != commitments_mod.PROPOSED:
        raise HTTPException(status_code=409, detail="only a proposed commitment can be approved")
    try:
        updated = commitments_mod.transition_commitment(
            commitment_id,
            commitments_mod.APPROVED,
            scope=CREATOR_COMMITMENT_SCOPE,
            evidence={
                "source": "creator_workshop",
                "principal": decision.principal,
                "authorization": decision.mechanism,
            },
        )
    except commitments_mod.IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"approved": True, "commitment": updated}


@app.post("/commitments/{commitment_id}/execute")
async def commitment_execute(commitment_id: int, req: Request) -> dict:
    """Run one approved, payload-backed commitment from a fresh Workshop turn."""
    _require_creator_request(req)
    turn = turn_context_mod.TurnContext.create(
        _server_conversation_id("creator", "workshop"),
        principal="creator",
        surface="workshop",
        privacy_scope=CREATOR_COMMITMENT_SCOPE,
        portal_epoch=f"workshop-{uuid.uuid4().hex[:12]}",
        timeout_s=30,
    )
    try:
        result = await asyncio.to_thread(
            commitment_executor_mod.execute_approved_commitment,
            commitment_id,
            toolkit=mind.toolkit,
            turn=turn,
        )
    except commitments_mod.CommitmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except commitments_mod.IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (commitments_mod.CommitmentError, commitment_executor_mod.CommitmentExecutionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    cognition_mod.record_observation(cognition_mod.CognitionObservation(
        source="commitment_execution",
        room="workshop",
        content=(
            f"Commitment {commitment_id} finished with "
            f"{result['execution']['status']}."
        ),
        confidence=1.0,
        privacy_class="local",
        metadata={
            "commitment_id": int(commitment_id),
            "tool": result["execution"]["tool"],
            "status": result["execution"]["status"],
            "turn_id": turn.turn_id,
        },
    ))
    return result


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
    return {"recent": _mem.recent(limit=40), "count": _mem.count(),
            "counts": _mem.kind_counts()}


@app.get("/memories/search")
def memory_search(q: str = "", limit: int = 8) -> dict:
    """Search Alpecca's Library with the same scored recall path chat uses."""
    from alpecca import memory as _mem
    query = (q or "").strip()
    top_k = max(1, min(20, int(limit or 8)))
    if not query:
        return {"query": "", "results": [], "count": _mem.count(),
                "counts": _mem.kind_counts()}
    raw_results = _mem.recall(query, top_k=top_k)
    results = [{
        "id": m.get("id"),
        "ts": m.get("ts"),
        "kind": m.get("kind", "episodic"),
        "content": m.get("content", ""),
        "salience": m.get("salience", 0),
        "recall_score": m.get("recall_score", 0),
        "recall_similarity": m.get("recall_similarity", 0),
        "recall_recency": m.get("recall_recency", 0),
        "recall_method": m.get("recall_method", "keyword"),
    } for m in raw_results]
    return {
        "query": query,
        "results": results,
        "count": _mem.count(),
        "counts": _mem.kind_counts(),
    }


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
    figure_value = b.get("figure")
    figure_bytes = None
    if isinstance(figure_value, str) and figure_value:
        figure_scope = f"rigforge:{uuid.uuid4().hex}"
        try:
            figure_bytes = attachment_ingress_mod.ingest_image(
                figure_value,
                scope=figure_scope,
                authorized_scopes={figure_scope},
                source="rigforge:certified-figure",
                max_bytes=attachment_ingress_mod.ATTACHMENT_IMAGE_MAX_BYTES,
            ).image_bytes
        except attachment_ingress_mod.ImageIngressRejected:
            figure_bytes = None
    if figure_bytes:
        (base / "figures" / f"{name}.png").write_bytes(figure_bytes)
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


@app.get("/source-workspace")
def source_workspace(req: Request) -> JSONResponse:
    """Creator-only metadata view of approved Alpecca repository areas."""
    _require_creator_request(req)
    from alpecca import source_workspace as _source_workspace

    return JSONResponse(
        _source_workspace.overview(),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/source-workspace/list")
def source_workspace_list(
    req: Request,
    root: str,
    rel: str = "",
    limit: int = 200,
) -> JSONResponse:
    """List names and metadata only; never return source contents or paths."""
    _require_creator_request(req)
    from alpecca import source_workspace as _source_workspace

    payload = _source_workspace.list_entries(
        root,
        rel,
        limit=max(1, min(200, int(limit))),
    )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/source-workspace/search")
def source_workspace_search(
    req: Request,
    q: str,
    limit: int = 80,
) -> JSONResponse:
    """Search only approved source names; selected text still uses file ingress."""
    _require_creator_request(req)
    from alpecca import source_workspace as _source_workspace

    payload = _source_workspace.search(q, limit=max(1, min(100, int(limit))))
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


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
    _require_creator_request(req)
    await _validate_request_capability_lease(
        req,
        purpose="screen_share",
        required_surface="house-hq",
    )
    data = await _read_bounded_body(
        req, max_bytes=attachment_ingress_mod.DEFAULT_MAX_IMAGE_BYTES
    )
    if not data:
        raise HTTPException(status_code=400, detail="empty frame")
    content_type = req.headers.get("content-type", "").split(";", 1)[0].strip() or None
    scope = f"sight:{uuid.uuid4().hex}"
    try:
        inspected_image = attachment_ingress_mod.inspect_image_bytes(
            data,
            scope=scope,
            authorized_scopes={scope},
            source="house-hq:screen-share",
            declared_mime_type=content_type,
        )
    except attachment_ingress_mod.ImageIngressRejected as exc:
        _raise_image_rejection(exc)
    lease_use = await _consume_request_capability_lease(
        req,
        purpose="screen_share",
        bytes_used=len(inspected_image.image_bytes),
        required_surface="house-hq",
    )
    if not await _record_capability_use(
        "screen_sight", action="capture", principal="creator", source="api"
    ):
        _raise_capability_audit_unavailable()
    from alpecca import vision as _vision
    desc = await asyncio.to_thread(
        _vision.describe_image,
        inspected_image.image_bytes,
        _vision._SCREEN_PROMPT,
        ambient=True,
    )
    if desc:
        screen_sight.latest = desc
        async with mind_lock:
            mind.see(desc)
    if lease_use.get("state") != "active":
        async with mind_lock:
            mind.set_screen_sharing(False)
    return {
        "ok": bool(desc),
        "description": desc or "",
        "perception": {
            **inspected_image.as_dict(),
            "status": "described" if desc else "vision-unavailable",
        },
    }


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


@app.get("/system/status")
def system_status() -> dict:
    """One truthful runtime health readout for the app and remote preview.

    This checks the actual Ollama daemon/model availability, voice engine
    readiness, optional deep tier, and live senses so Alpecca can explain why
    she is in full, degraded, or offline mode.
    """
    return _runtime_status(check_models=True)


_PAGEFILE_LIVE_EVIDENCE_SCHEMA = "alpecca.phase7.pagefile-live-evidence.v1"
_PAGEFILE_REQUEST_RESPONSE_SCHEMA = (
    "alpecca.phase7.pagefile-request-response.v1"
)
_PAGEFILE_APPROVAL_RESPONSE_SCHEMA = (
    "alpecca.phase7.pagefile-approve-response.v1"
)
_PAGEFILE_APPROVAL_BODY_MAX_BYTES = 4 * 1024
_PAGEFILE_APPROVAL_BODY_KEYS = frozenset(
    {"request_token", "plan", "approved"}
)
_PAGEFILE_PROPOSAL_STATES = frozenset(
    {"proposed", "blocked", "not_recommended", "unknown"}
)


def _unavailable_pagefile_telemetry() -> dict[str, object]:
    """Return a fixed, identifier-free fallback for collector failures."""
    return {
        "schema": pagefile_telemetry_mod.SCHEMA,
        "state": "unavailable",
        "platform": "unknown",
        "evidence": {
            "powershell": {
                "available": False,
                "state": "unavailable",
                "reason": "collector_unavailable",
            },
            "wmi": {
                "available": False,
                "state": "unavailable",
                "management": "unavailable",
                "configuration": "unavailable",
                "usage": "unavailable",
                "reason": "collector_unavailable",
            },
        },
        "configured": {
            "state": "unknown",
            "mode": "unknown",
            "initial_mib": None,
            "maximum_mib": None,
            "entry_count": None,
        },
        "usage": {
            "state": "unknown",
            "allocated_mib": None,
            "used_mib": None,
            "free_mib": None,
            "peak_used_mib": None,
            "entry_count": None,
        },
    }


def _pagefile_planner_observation(
    telemetry: Mapping[str, object],
) -> dict[str, object]:
    """Project measured configuration into the planner's narrow contract."""
    configured = telemetry.get("configured")
    if not isinstance(configured, Mapping):
        return {"state": "invalid", "maximum_mib": None}

    state = configured.get("state")
    mode = configured.get("mode")
    maximum = configured.get("maximum_mib")
    if state == "unknown":
        return {"state": "unknown", "maximum_mib": None}
    if state != "known":
        return {"state": "invalid", "maximum_mib": None}
    if mode == "system_managed":
        return {"state": "unknown", "maximum_mib": None}
    if mode == "custom" and type(maximum) is int and maximum > 0:
        return {"state": "known", "maximum_mib": maximum}
    if mode == "none" and type(maximum) is int and maximum == 0:
        return {"state": "known", "maximum_mib": 0}
    return {"state": "invalid", "maximum_mib": None}


def _pagefile_blocked_controls() -> dict[str, object]:
    """Describe implemented approval controls without granting execution."""
    return {
        "approval": {
            "durable": True,
            "digest_bound": True,
            "one_use": True,
            "request_available": True,
            "approve_available": True,
            "consume_available": False,
            "raw_tokens_persisted": False,
        },
        "execution": {
            "available": False,
            "authorized": False,
            "mutation_available": False,
            "elevation_available": False,
        },
        "gates": {
            "documented_safe_8192_measurement": False,
            "fresh_live_pagefile_commit_disk_readback": False,
            "uac_elevation": False,
            "separate_minimal_elevated_helper": False,
            "single_bounded_write": False,
            "post_write_readback": False,
        },
    }


def _pagefile_approval_ledger() -> pagefile_approval_mod.PagefileApprovalLedger:
    """Initialize the SQLite ledger only from a route's worker thread."""
    global _PAGEFILE_APPROVAL_LEDGER
    with _PAGEFILE_APPROVAL_LEDGER_LOCK:
        if _PAGEFILE_APPROVAL_LEDGER is None:
            _PAGEFILE_APPROVAL_LEDGER = (
                pagefile_approval_mod.PagefileApprovalLedger(DB_PATH)
            )
        return _PAGEFILE_APPROVAL_LEDGER


def _create_pagefile_approval_request(
    plan: object,
) -> dict[str, object]:
    return _pagefile_approval_ledger().create_request(plan)


def _approve_pagefile_approval_request(
    request_token: object,
    plan: object,
) -> dict[str, object]:
    return _pagefile_approval_ledger().approve_request(
        request_token,
        plan,
        principal="CreatorJD",
        approved=True,
    )


def _collect_pagefile_live_evidence() -> dict[str, object]:
    """Collect bounded pagefile and planner evidence in a worker thread."""
    try:
        telemetry = pagefile_telemetry_mod.collect_pagefile_telemetry()
    except Exception:
        telemetry = _unavailable_pagefile_telemetry()
    if (
        type(telemetry) is not dict
        or telemetry.get("schema") != pagefile_telemetry_mod.SCHEMA
    ):
        telemetry = _unavailable_pagefile_telemetry()

    try:
        host_snapshot = _host_resource_sampler.snapshot(force=True)
    except Exception:
        host_snapshot = {"state": "unknown"}
    proposal = system_pressure_mod.propose_pagefile_plan(
        host_snapshot,
        _pagefile_planner_observation(telemetry),
    )
    return {
        "schema": _PAGEFILE_LIVE_EVIDENCE_SCHEMA,
        "state": "blocked",
        "telemetry": telemetry,
        "proposal": proposal,
        **_pagefile_blocked_controls(),
    }


def _pagefile_json(
    payload: Mapping[str, object], *, status_code: int = 200
) -> JSONResponse:
    return JSONResponse(
        dict(payload),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _raise_pagefile_approval_error(
    exc: pagefile_approval_mod.PagefileApprovalError,
) -> NoReturn:
    conflict_codes = {
        "active_request_exists",
        "plan_already_consumed",
        "plan_mismatch",
        "request_expired",
        "request_replayed",
    }
    client_codes = {
        "explicit_approval_required",
        "plan_cap_exceeded",
        "plan_invalid",
        "request_invalid",
    }
    status_code = 409 if exc.code in conflict_codes else 400
    if exc.code not in conflict_codes | client_codes:
        status_code = 503
    raise HTTPException(
        status_code=status_code,
        detail={"code": exc.code},
        headers={"Cache-Control": "no-store"},
    ) from exc


def _pagefile_plan_from_json(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise HTTPException(
            status_code=400,
            detail={"code": "pagefile_plan_invalid"},
            headers={"Cache-Control": "no-store"},
        )
    plan = dict(value)
    requirements = plan.get("future_requirements")
    if type(requirements) is list:
        plan["future_requirements"] = tuple(requirements)
    return plan


@app.get("/system/pagefile")
async def pagefile_read(req: Request) -> JSONResponse:
    """Return creator-only, read-only pagefile and proposal evidence."""
    _require_creator_request(req)
    evidence = await asyncio.to_thread(_collect_pagefile_live_evidence)
    return _pagefile_json(evidence)


@app.post("/system/pagefile/request")
async def pagefile_request(req: Request) -> JSONResponse:
    """Create one digest-bound request from a fresh server-owned proposal."""
    _require_creator_request(req)
    evidence = await asyncio.to_thread(_collect_pagefile_live_evidence)
    proposal = evidence.get("proposal")
    proposal_state = (
        proposal.get("state") if isinstance(proposal, Mapping) else "unknown"
    )
    if (
        not isinstance(proposal_state, str)
        or proposal_state not in _PAGEFILE_PROPOSAL_STATES
    ):
        proposal_state = "unknown"
    plan = proposal.get("plan") if isinstance(proposal, Mapping) else None
    if proposal_state != "proposed" or type(plan) is not dict:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "pagefile_plan_not_proposed",
                "proposal_state": proposal_state,
            },
            headers={"Cache-Control": "no-store"},
        )
    try:
        request_record = await asyncio.to_thread(
            _create_pagefile_approval_request,
            plan,
        )
    except pagefile_approval_mod.PagefileApprovalError as exc:
        _raise_pagefile_approval_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "pagefile_ledger_unavailable"},
            headers={"Cache-Control": "no-store"},
        ) from exc
    return _pagefile_json({
        "schema": _PAGEFILE_REQUEST_RESPONSE_SCHEMA,
        "state": "pending",
        "phase_state": "blocked",
        "plan": plan,
        "request": request_record,
        "execution": _pagefile_blocked_controls()["execution"],
    })


@app.post("/system/pagefile/approve")
async def pagefile_approve(req: Request) -> JSONResponse:
    """Approve one exact request without consuming or executing it."""
    _require_creator_request(req)
    body = await _read_bounded_json_object(
        req,
        max_bytes=_PAGEFILE_APPROVAL_BODY_MAX_BYTES,
    )
    if frozenset(body) != _PAGEFILE_APPROVAL_BODY_KEYS:
        raise HTTPException(
            status_code=400,
            detail={"code": "pagefile_approval_body_invalid"},
            headers={"Cache-Control": "no-store"},
        )
    if body.get("approved") is not True:
        raise HTTPException(
            status_code=400,
            detail={"code": "explicit_approval_required"},
            headers={"Cache-Control": "no-store"},
        )
    plan = _pagefile_plan_from_json(body.get("plan"))
    try:
        approval = await asyncio.to_thread(
            _approve_pagefile_approval_request,
            body.get("request_token"),
            plan,
        )
    except pagefile_approval_mod.PagefileApprovalError as exc:
        _raise_pagefile_approval_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "pagefile_ledger_unavailable"},
            headers={"Cache-Control": "no-store"},
        ) from exc
    return _pagefile_json({
        "schema": _PAGEFILE_APPROVAL_RESPONSE_SCHEMA,
        "state": "approved",
        "phase_state": "blocked",
        "approval": approval,
        "execution": _pagefile_blocked_controls()["execution"],
        "gates": _pagefile_blocked_controls()["gates"],
    })


@app.get("/brain/graph")
def brain_graph() -> dict:
    """Return the live, evidence-backed architecture plugin graph.

    The graph is read-only. Plugin JSON may select only allowlisted probes and
    cannot import code, execute commands, or mutate Alpecca's runtime.
    """
    from alpecca import soul as soul_mod
    from alpecca import vrm as vrm_mod

    runtime = _runtime_status(check_models=True)
    mindpage = mindpage_mod.stats()
    soul_vector = mind.soul_perspective_evidence()
    discord_running = False
    try:
        with socket.create_connection(("127.0.0.1", 8779), timeout=0.04):
            discord_running = True
    except OSError:
        pass
    facts = {
        "runtime": runtime,
        "model": mind.llm.model_for("reason"),
        "memory_count": memory_store.count(),
        "soul_agent_count": len(soul_mod.SUBAGENT_SPECS),
        "soul_perspective_vector": soul_vector,
        "senses": _sense_status(),
        "discord_configured": bool(_discord_bot_token() or DISCORD_CLIENT_ID),
        "discord_running": discord_running,
        "mindpage_enabled": bool(mindpage.get("enabled")),
        "memory_pressure": mindpage.get("pressure_score"),
        "mindscape_configured": bool(MINDSCAPE_VAULT_ENABLED and MINDSCAPE_VAULT_URL),
        "vrm_available": bool(vrm_mod.manifest().get("vrm_mode")),
        "creator_password_configured": _AUTHORITY.password_configured,
        # FastAPI executes this synchronous route in its worker thread.
        "pagefile_evidence": _collect_pagefile_live_evidence(),
    }
    return brain_graph_mod.build_snapshot(facts)


@app.get("/system/resources")
def system_resources() -> dict:
    """Return the read-only host snapshot from the shared sampler cache."""
    return _host_resource_sampler.snapshot()


@app.get("/system/doctor")
def system_doctor(req: Request) -> dict:
    """Structured doctor report for the app, House HQ, and Mindscape layers."""
    runtime = _runtime_status(check_models=True)
    house_dist = HOUSE_HQ_DIR / "dist" / "index.html"
    public_url = PUBLIC_URL or (f"https://{CLOUDFLARE_HOSTNAME}" if CLOUDFLARE_HOSTNAME else str(req.base_url).rstrip("/"))
    report = runtime_status_mod.build_doctor_report(
        runtime=runtime,
        mindscape=_mindscape_sync_status_view(),
        house_hq_built=house_dist.exists(),
        public_url=public_url,
    )
    report["mindscape_setup"] = mindscape_mod.cloud_setup_plan(
        ROOT_DIR / "deploy" / "mindscape-worker",
        cloud_url=MINDSCAPE_CLOUD_URL,
        token_configured=bool(MINDSCAPE_TOKEN),
    )
    return report


def _doctor_report_for_base(public_url: str, check_models: bool = True) -> dict:
    runtime = _runtime_status(check_models=check_models)
    house_dist = HOUSE_HQ_DIR / "dist" / "index.html"
    report = runtime_status_mod.build_doctor_report(
        runtime=runtime,
        mindscape=_mindscape_sync_status_view(),
        house_hq_built=house_dist.exists(),
        public_url=public_url,
    )
    report["mindscape_setup"] = mindscape_mod.cloud_setup_plan(
        ROOT_DIR / "deploy" / "mindscape-worker",
        cloud_url=MINDSCAPE_CLOUD_URL,
        token_configured=bool(MINDSCAPE_TOKEN),
    )
    return report


@app.post("/cognition/self-review")
async def cognition_self_review(req: Request) -> dict:
    """Review runtime health and convert real gaps into bounded improvements."""
    report = _doctor_report_for_base(str(req.base_url).rstrip("/"), check_models=True)
    async with mind_lock:
        review = mind.review_runtime_gaps(report)
    return {"doctor": report, "review": review, **mind.proposal_state()}


@app.post("/cognition/behavior-review")
async def cognition_behavior_review() -> dict:
    """Review one behavior lesson and attach evidence to the improvement queue."""
    async with mind_lock:
        review = mind.review_behavior_improvement()
    try:
        candidate_result = await asyncio.to_thread(
            _issue_behavior_trial_candidate_from_baseline,
        )
    except Exception:
        # The ordinary review remains useful even if optional candidate storage
        # is unavailable. It never implies that a behavior change occurred.
        candidate_result = {"issued": False, "reason": "candidate_unavailable"}
    return {
        "review": review,
        "behavior_trial_candidate": _behavior_trial_candidate_public_summary()
        if candidate_result.get("issued")
        else None,
        "behavior_trial_candidate_result": {
            "issued": bool(candidate_result.get("issued")),
            "reused": bool(candidate_result.get("reused")),
            "reason": str(candidate_result.get("reason") or ""),
        },
        **mind.proposal_state(),
    }


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
async def observatory_screen_start(req: Request) -> dict:
    """You started sharing your screen with her. She settles into the Observatory
    to watch it with you (where she'll hold the live screen as a window) and stays
    there until you stop. If she had to walk there, broadcast it so any open home
    view follows her."""
    _require_creator_request(req)
    await _validate_request_capability_lease(
        req,
        purpose="screen_share",
        required_surface="house-hq",
    )
    async with mind_lock:
        moved = mind.set_screen_sharing(True)
        home = mind.home_state() if moved else None
    if moved:
        await _broadcast({"type": "roamed", "location": moved, "home": home})
    return {"ok": True, "location": "observatory"}


@app.post("/observatory/screen/stop")
async def observatory_screen_stop(req: Request) -> dict:
    """You stopped sharing. She's free to roam her home again."""
    _require_creator_request(req)
    connection_id = req.headers.get(
        capability_leases_mod.CONNECTION_HEADER, ""
    ).strip()
    if not connection_id:
        active = _active_ws_portal
        if active is not None and _websocket_route_surface(active[0]) == "house-hq":
            connection_id = active[1]
    lease_stopped = False
    lease = None
    if _capability_connection_surface(connection_id) == "house-hq":
        lease, lease_stopped = await _capability_lease_store_call(
            _capability_lease_store.stop_purpose,
            connection_id,
            purpose="screen_share",
            reason="screen_share_stopped",
        )
    async with mind_lock:
        mind.set_screen_sharing(False)
    return {
        "ok": True,
        "lease_stopped": lease_stopped,
        **({"lease": lease} if lease is not None else {}),
    }


@app.get("/state")
def state() -> dict:
    """Current mood + her self-chosen look -- the UI renders both, never sets them."""
    senses = _sense_status()
    runtime = _runtime_status(check_models=False)
    return {"state": mind.state.as_dict(), "mood": mind.state.mood_label(),
            "appearance": mind.current_appearance().as_dict(),
            "llm_online": mind.llm.online,
            "core_memory": {
                "learn_only": CORE_MEMORY_LEARN_ONLY,
                "policy": "explicit-teach-only",
            },
            # Which model serves which tier -- heavy reasoning vs. cheap fast work,
            # plus her optional "deep" tier (cloud augmentation for her hardest
            # self-acts only; "local" means no cloud, her brain stays fully local).
            "models": {"reason": mind.llm.model_for("reason"),
                       "fast": mind.llm.model_for("fast"),
                       "deep": (DEEP_BACKEND if mind.llm.deep_online() else "local")},
            # Which senses are actually live right now -- truthful capability
            # report, so the UI (and the person) can see what she can sense.
            "senses": senses,
            "runtime": runtime,
            "cognition": mind.cognition_state(
                senses=senses,
                capabilities=runtime_status_mod.cognition_capabilities(runtime),
            )}


@app.get("/cognition/state")
def cognition_state() -> dict:
    """Unified view of Alpecca's observable cognitive loop."""
    runtime = _runtime_status(check_models=False)
    d = mind.cognition_state(
        senses=_sense_status(),
        capabilities=runtime_status_mod.cognition_capabilities(runtime),
    )
    d["runtime"] = runtime
    return d


@app.get("/cognition/autonomy-state")
def cognition_autonomy_state() -> dict:
    """Observable status for Alpecca's promptless backend autonomy loop."""
    return _background_autonomy_snapshot()


@app.get("/cognition/recursive-engagement")
def cognition_recursive_engagement() -> dict:
    """Evidence-based scorecard for Alpecca's promptless self-feedback loop."""
    return cognition_mod.recursive_engagement_scorecard()


@app.post("/cognition/consolidate")
async def cognition_consolidate() -> dict:
    """Ask Alpecca to carry important observations into memory now."""
    async with mind_lock:
        return mind.consolidate_observations(limit=24)


@app.get("/routines")
def routines_list() -> dict:
    """List empty-by-default scheduled maintenance routines."""
    return {
        "enabled": bool(AutomationCfg.ROUTINES),
        "kinds": sorted(routines_mod.KINDS),
        "routines": routines_mod.list_all(),
    }


@app.post("/routines")
async def routines_create(req: Request) -> dict:
    """Create a safe local routine. Nothing exists until the owner adds it."""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    try:
        row = routines_mod.add(
            name=str(body.get("name") or ""),
            hour=int(body.get("hour")),
            weekday=int(body.get("weekday", -1)),
            kind=str(body.get("kind") or ""),
            enabled=bool(body.get("enabled", True)),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"routine": row, "routines": routines_mod.list_all()}


@app.post("/routines/{routine_id}")
async def routines_update(routine_id: int, req: Request) -> dict:
    """Enable or disable a routine without deleting its history."""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    if "enabled" not in body:
        raise HTTPException(status_code=400, detail="enabled is required")
    try:
        row = routines_mod.set_enabled(routine_id, bool(body.get("enabled")))
    except KeyError:
        raise HTTPException(status_code=404, detail="routine not found")
    return {"routine": row, "routines": routines_mod.list_all()}


@app.post("/routines/{routine_id}/delete")
async def routines_delete(routine_id: int) -> dict:
    """Remove a routine entirely. Toggling keeps history; deleting forgets it."""
    if not routines_mod.remove(routine_id):
        raise HTTPException(status_code=404, detail="routine not found")
    return {"deleted": int(routine_id), "routines": routines_mod.list_all()}


@app.post("/cognition/chat/review")
async def cognition_chat_review(req: Request) -> dict:
    """Review recent chat turns for grounding risks and propose fixes if needed."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        limit = int(body.get("limit", 8))
    except Exception:
        limit = 8
    async with mind_lock:
        return mind.review_chat_grounding(limit=max(1, min(25, limit)))


@app.post("/cognition/observe")
async def cognition_observe(req: Request) -> dict:
    """Record a grounded observation from any Alpecca surface.

    This is the shared intake for House HQ, the classic app, Mindscape, or a
    future mobile shell. It records what Alpecca was given as observed evidence;
    callers may ask for immediate consolidation, but it still passes through the
    same bounded memory salience rules as the rest of cognition.
    """
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    content = str(body.get("content") or body.get("text") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    source = str(body.get("source") or "app").strip()[:48]
    room = str(body.get("room") or body.get("location") or "").strip()[:80]
    privacy = str(body.get("privacy_class") or body.get("privacy") or "local").strip()[:40]
    try:
        confidence = float(body.get("confidence", 0.75))
    except Exception:
        confidence = 0.75
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    if body.get("novelty") is not None:
        try:
            metadata = {**metadata, "novelty": float(body.get("novelty"))}
        except Exception:
            pass
    async with mind_lock:
        if source in {"house-presence", "house-hq", "app-presence"} and room:
            live_room, legacy_room = mind._house_context_room(f"player is in {room}")
            if legacy_room and legacy_room != getattr(mind, "_location", ""):
                mind._location = legacy_room
                state_store.save_location(legacy_room)
            metadata = {
                **metadata,
                "live_surface_room": live_room or room,
                "legacy_room": legacy_room,
            }
        obs_id = cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source=source,
            room=room,
            content=content,
            confidence=confidence,
            privacy_class=privacy,
            metadata=metadata,
        ))
        intent = cognition_mod.set_intent(cognition_mod.IntentState(
            "observing",
            f"Alpecca recorded an observation from {source}.",
            target=room or source,
            confidence=confidence,
        ))
        consolidated = mind.consolidate_observations(limit=8) if body.get("remember_now") else None
    return {
        "ok": True,
        "observation_id": obs_id,
        "intent": intent,
        "consolidated": consolidated,
    }


@app.post("/cognition/rooms/{room_id}/review")
async def cognition_room_review(room_id: str, req: Request) -> dict:
    """Ask Alpecca to review a room as grounded cognition, not loose chat."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    body["room_id"] = room_id
    async with mind_lock:
        return mind.review_room(body)


@app.post("/cognition/world-tick")
async def cognition_world_tick(req: Request) -> dict:
    """Run one bounded autonomous world/role learning step now."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    reason = str(body.get("reason") or "manual").strip()[:80] or "manual"
    quiet = body.get("quiet") is True
    initiative_scope = _proactive_turn_context().scope_key if quiet else ""
    call_args = (reason, _living_systems_context(False))
    if quiet:
        result = await _bounded_thread(
            "cognition_world_tick",
            mind.living_world_tick,
            *call_args,
            initiative_scope=initiative_scope,
            timeout=BACKGROUND_LIVING_TIMEOUT,
        )
    else:
        # Manual ticks are explicit user actions, not optional background work.
        # Await their worker instead of returning a false timeout while it keeps
        # mutating state off-thread.
        result = await asyncio.to_thread(
            mind.living_world_tick,
            *call_args,
            initiative_scope="",
        )
    if result is None:
        raise HTTPException(status_code=503, detail="living loop timed out")
    if result.get("deferred"):
        return result
    if (result.get("activated_system") or {}).get("warmup_requested"):
        result["activated_system"]["warmup"] = await _warm_alpecca_voice(timeout=8.0)
    _remember_living_result(result, counted=True)
    await _broadcast({
        "type": "living_loop",
        "text": result.get("line", ""),
        "living_loop": result,
        "cognition": mind.cognition_state(),
    })
    _mindscape_request_event_sync("living_world_tick")
    return result


@app.get("/cognition/proposals")
def cognition_proposals() -> dict:
    """Reviewable improvement/action proposals Alpecca has noticed."""
    return mind.proposal_state()


@app.post("/cognition/proposals/compact")
def cognition_proposals_compact() -> dict:
    """Close older duplicate open proposals as superseded, preserving history."""
    result = cognition_mod.compact_duplicate_open_proposals()
    return {"compact": result, **mind.proposal_state()}


@app.get("/cognition/proposals/handoff")
def cognition_proposals_handoff(limit: int = 8) -> dict:
    """Markdown packet for carrying Alpecca's bounded improvements to Codex/Claude/ChatGPT."""
    return cognition_mod.improvement_handoff_markdown(limit=limit)


@app.post("/cognition/proposals")
async def cognition_proposal_create(req: Request) -> dict:
    """Add a new bounded improvement/action proposal."""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    try:
        async with mind_lock:
            created = mind.create_proposal(body)
        return {"proposal": created, **mind.proposal_state()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/cognition/proposals/{proposal_id}")
async def cognition_proposal_update(proposal_id: int, req: Request) -> dict:
    """Move a proposal through noticed/planned/testing/accepted/rejected."""
    _require_creator_request(req)
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    status = (body.get("status") or "").strip()
    result = (body.get("result") or "").strip()
    approved = bool(body.get("approved_by_user"))
    execute = bool(body.get("execute"))
    if execute:
        _require_creator_request(req)
        raise HTTPException(
            status_code=409,
            detail=(
                "legacy proposal execution is retired; create, approve, and "
                "execute a payload-backed commitment"
            ),
        )
    try:
        async with mind_lock:
            updated = mind.update_proposal(proposal_id, status, result, approved)
            return updated
    except KeyError:
        raise HTTPException(status_code=404, detail="proposal not found")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/cognition/proposals/{proposal_id}/evaluations")
def cognition_proposal_evaluations(proposal_id: int) -> dict:
    """Evidence and test results attached to a proposal."""
    if cognition_mod.get_action_proposal(proposal_id) is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return {"evaluations": mind.proposal_evaluations(proposal_id)}


@app.post("/cognition/proposals/{proposal_id}/evaluations")
async def cognition_proposal_evaluation_add(proposal_id: int, req: Request) -> dict:
    """Record a concrete test/evidence item for an improvement proposal."""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    try:
        async with mind_lock:
            recorded = mind.record_proposal_evaluation(proposal_id, body)
        return {"evaluation": recorded, "evaluations": mind.proposal_evaluations(proposal_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="proposal not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    normalized = str(path or "").replace("\\", "/").lstrip("/")
    if normalized == "archive" or normalized.startswith("archive/"):
        raise HTTPException(status_code=404, detail="not found")
    safe = (WEB_DIR / normalized).resolve()
    try:
        safe.relative_to(WEB_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    if not safe.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(safe)


def _safe_house_file(root: Path, path: str) -> Path:
    safe = (root / path).resolve()
    try:
        safe.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    if not safe.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return safe


@app.get("/house-hq")
def house_hq_page() -> FileResponse:
    """Serve the unified Void Prototype and its native systems center."""
    return FileResponse(_safe_house_file(HOUSE_HQ_DIST, "index.html"))


@app.get("/house-hq/{path:path}")
def house_hq_asset(path: str) -> FileResponse:
    target = path or "index.html"
    if not (HOUSE_HQ_DIST / target).resolve().is_file():
        target = "index.html"
    return FileResponse(_safe_house_file(HOUSE_HQ_DIST, target))


@app.get("/assets/{path:path}")
def house_hq_public_asset(path: str) -> FileResponse:
    """The embedded Vite game uses /assets/... for its optimized sprites and bundle."""
    dist_asset = HOUSE_HQ_DIST / "assets" / path
    if dist_asset.resolve().is_file():
        return FileResponse(_safe_house_file(HOUSE_HQ_DIST / "assets", path))
    return FileResponse(_safe_house_file(HOUSE_HQ_PUBLIC / "assets", path))


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
    """Whether her VRM body exists, which file to load, the clip vocabulary the
    pose endpoint may ask the renderer to play, and whether a cloud studio is
    configured to sync her body from."""
    from alpecca import vrm
    m = vrm.manifest()
    m["studio"] = vrm.studio_configured()
    return m


@app.post("/vrm/sync")
async def vrm_sync() -> dict:
    """Pull her newest .vrm from the configured VRoid Companion Studio
    (ALPECCA_STUDIO_URL/TOKEN). Off-thread -- a slow tunnel download must not
    stall her chat loop. Always returns {ok, file|error}."""
    from alpecca import vrm
    return await asyncio.to_thread(vrm.sync_from_studio)


@app.get("/vrm/model/{name}")
def vrm_model(name: str) -> FileResponse:
    """Serve her `.vrm` from data/avatar/vrm/, traversal-blocked. A VRM is one
    binary glTF with textures embedded, so this is the only asset fetch."""
    from alpecca import vrm
    p = vrm.asset_path(name)
    if p is None:
        raise HTTPException(status_code=404, detail="no such asset")
    return FileResponse(
        p,
        media_type="model/gltf-binary",
        headers={"Cache-Control": "no-cache, max-age=0, must-revalidate"},
    )


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
    _require_creator_request(req)
    await _validate_request_capability_lease(req, purpose="push_to_talk")
    audio = await _read_bounded_body(req, max_bytes=audio_ingress_mod.MAX_AUDIO_BYTES)
    if not audio:
        raise HTTPException(status_code=400, detail="no audio")
    content_type = req.headers.get("content-type", "").split(";", 1)[0].strip()
    scope = f"listen:{uuid.uuid4().hex}"
    try:
        inspected_audio = audio_ingress_mod.inspect_audio_bytes(
            audio,
            scope=scope,
            authorized_scopes={scope},
            source="house-hq:push-to-talk",
            declared_mime_type=content_type,
        )
    except audio_ingress_mod.AudioIngressRejected as exc:
        _raise_audio_rejection(exc)
    await _consume_request_capability_lease(
        req,
        purpose="push_to_talk",
        bytes_used=len(inspected_audio.audio_bytes),
    )
    if not await _record_capability_use(
        "microphone", action="capture", principal="creator", source="api"
    ):
        _raise_capability_audit_unavailable()
    async with _hearing_lock:
        text = await asyncio.to_thread(
            hearing.transcribe, inspected_audio.audio_bytes
        )
    # Best-effort: tell from the same audio whether it's her creator or a guest,
    # and let her adapt. Falls through silently if voice recognition is off.
    from alpecca import people
    ident = await asyncio.to_thread(people.identify_voice, inspected_audio.audio_bytes)
    if ident:
        async with mind_lock:
            mind.set_speaker(ident)
    return {
        "text": text or "",
        "heard": bool(text),
        "speaker": ident or "",
        "perception": {
            **inspected_audio.as_dict(),
            "status": "transcribed" if text else "no-transcript",
        },
    }


@app.post("/people/enroll_voice")
async def enroll_voice(req: Request) -> dict:
    """Teach her your voice (creator). The browser records a few seconds and
    posts the audio here; we store only a small local embedding, never the
    audio. After this she can tell you from a guest by voice."""
    from alpecca import people
    _require_creator_request(req)
    await _validate_request_capability_lease(req, purpose="voice_enrollment")
    audio = await _read_bounded_body(req, max_bytes=audio_ingress_mod.MAX_AUDIO_BYTES)
    if not audio:
        raise HTTPException(status_code=400, detail="no audio")
    content_type = req.headers.get("content-type", "").split(";", 1)[0].strip()
    scope = f"voice-enrollment:{uuid.uuid4().hex}"
    try:
        inspected_audio = audio_ingress_mod.inspect_audio_bytes(
            audio,
            scope=scope,
            authorized_scopes={scope},
            source="house-hq:voice-enrollment",
            declared_mime_type=content_type,
        )
    except audio_ingress_mod.AudioIngressRejected as exc:
        _raise_audio_rejection(exc)
    await _consume_request_capability_lease(
        req,
        purpose="voice_enrollment",
        bytes_used=len(inspected_audio.audio_bytes),
    )
    if not await _record_capability_use(
        "microphone", action="capture", principal="creator", source="api"
    ):
        _raise_capability_audit_unavailable()
    async with _hearing_lock:
        ok = await asyncio.to_thread(
            people.enroll_creator_voice, inspected_audio.audio_bytes
        )
    return {
        "ok": ok,
        "perception": {
            **inspected_audio.as_dict(),
            "status": "enrolled" if ok else "enrollment-failed",
        },
    }


@app.get("/people/state")
def people_state() -> dict:
    """Who she currently believes she's with, and whether your voice is enrolled."""
    from alpecca import people
    return {"speaker": mind._speaker, "voice_enrolled": people.voice_enrolled()}


@app.post("/tts")
async def tts(req: Request):
    """Speak her reply in a real voice. Body {text}. Returns the synthesized
    audio (wav/mp3) from the best installed engine, or 204 if Alpecca's voice
    is unavailable. House HQ deliberately stays silent instead of substituting
    an unrelated browser/system speaker. Synthesis runs off the event loop."""
    from fastapi import Response
    from config import TTS_ROUTE_TIMEOUT
    from alpecca import tts as tts_mod
    from alpecca import speech as speech_mod
    from alpecca.homeostasis import EmotionalState
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body.get("text") or "").strip()
    if not text:
        return Response(status_code=204)
    engine = str(body.get("engine") or "").strip().lower()
    if engine not in {"", "auto", "kokoro", "f5", "f5-tts", "open"}:
        return Response(
            status_code=422,
            headers={"X-Alpecca-TTS-Error": "unsupported voice engine"},
        )
    preview = str(body.get("preview") or body.get("voice_preview") or "current").strip().lower()
    preview_states = {
        "lively": EmotionalState(love=0.95, compassion=0.55, fear=0.02, energy=1.0, curiosity=0.95),
        "tender": EmotionalState(love=0.86, compassion=0.95, fear=0.04, energy=0.45, curiosity=0.38),
        "sleepy": EmotionalState(love=0.46, compassion=0.42, fear=0.04, energy=0.02, curiosity=0.18, social_hunger=0.1),
        "anxious": EmotionalState(love=0.38, compassion=0.62, fear=0.92, energy=0.78, curiosity=0.34, social_hunger=0.32),
    }
    synth_state = preview_states.get(preview, mind.state)
    preview_header = preview if preview in preview_states else "current"
    spoken_text = (body.get("spoken_text") or body.get("spoken_reply") or "").strip()
    performance_mode = bool(body.get("performance_mode") or body.get("performative"))
    # Default to the exact model/user-visible reply. The House HQ conversation
    # should never sound like Alpecca is answering a different line than the one
    # shown in chat; expressive text shaping is opt-in for previews/tests.
    synth_text = spoken_text or (speech_mod.spoken_performance_text(text, synth_state) if performance_mode else text)
    speech_cues = speech_mod.speech_cues(synth_state)
    global active_tts_requests
    active_tts_requests += 1
    _sync_optional_work_foreground()
    try:
        try:
            if engine:
                synth_call = lambda: tts_mod.synth(
                    synth_text,
                    synth_state,
                    backend_override=engine,
                )
            else:
                synth_call = lambda: tts_mod.synth(synth_text, synth_state)
            result = await asyncio.wait_for(
                asyncio.to_thread(synth_call),
                timeout=TTS_ROUTE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            tts_mod._last_error = "server voice timed out while warming or synthesizing"
            return Response(
                status_code=204,
                headers={
                    "X-Alpecca-TTS-Status": "fallback",
                    "X-Alpecca-TTS-Error": _header_text(tts_mod._last_error),
                    "X-Alpecca-Voice-Preview": preview_header,
                },
            )
    finally:
        active_tts_requests = max(0, active_tts_requests - 1)
        _sync_optional_work_foreground()
    if not result:
        headers = {"X-Alpecca-TTS-Status": "fallback"}
        if getattr(tts_mod, "_last_error", ""):
            headers["X-Alpecca-TTS-Error"] = _header_text(tts_mod._last_error, 180)
        headers["X-Alpecca-Voice-Preview"] = preview_header
        return Response(status_code=204, headers=headers)
    mime, data = result
    modulation = getattr(tts_mod, "_last_modulation", {}) or {}
    return Response(
        content=data,
        media_type=mime,
        headers={
            "X-Alpecca-TTS-Engine": getattr(tts_mod, "_last_engine", "") or "server",
            "X-Alpecca-Voice": str(modulation.get("voice") or ""),
            "X-Alpecca-Voice-Profile": str(modulation.get("profile") or ""),
            "X-Alpecca-Voice-Tone": str(modulation.get("tone") or ""),
            "X-Alpecca-Voice-Pitch": str(modulation.get("pitch") or ""),
            "X-Alpecca-Voice-Speed": str(modulation.get("speed") or ""),
            "X-Alpecca-Voice-Volume": str(modulation.get("volume") or ""),
            "X-Alpecca-Voice-Primary": str(modulation.get("primary") or ""),
            "X-Alpecca-Voice-Tempo": str(modulation.get("tempo") or ""),
            "X-Alpecca-Voice-Rate": str(modulation.get("rate_pct") or ""),
            "X-Alpecca-Voice-Style": str(modulation.get("style") or ""),
            "X-Alpecca-Voice-Warmth": str(modulation.get("warmth") or ""),
            "X-Alpecca-Voice-Breath": str(modulation.get("breath") or ""),
            "X-Alpecca-Voice-Modulation-Strength": str(modulation.get("modulation_strength") or ""),
            "X-Alpecca-Voice-Engine-Profile": str(modulation.get("engine_profile") or ""),
            "X-Alpecca-Voice-Reference": _header_text(json.dumps(modulation.get("reference") or {}, ensure_ascii=True)),
            "X-Alpecca-Spoken-Text": _header_text(synth_text),
            "X-Alpecca-Speech-Cues": _header_text(json.dumps(speech_cues, ensure_ascii=True)),
            "X-Alpecca-Voice-Personality": str(modulation.get("personality") or ""),
            "X-Alpecca-Voice-Identity-Lock": "1" if modulation.get("identity_lock") else "0",
            "X-Alpecca-Voice-Preview": preview_header,
            "X-Alpecca-TTS-Exact-Text": "0" if performance_mode and not spoken_text else "1",
        },
    )


@app.post("/tts/warmup")
async def tts_warmup() -> dict:
    """Prepare Alpecca's F5 reference voice without speaking a user line."""
    return await _warm_alpecca_voice()


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
        "host_pressure": report.host_pressure,
        "soul_perspective_vector": mind.soul_perspective_evidence(),
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


@app.post("/channel/discord/actor-envelope")
async def issue_discord_actor_envelope(req: Request, response: Response) -> dict:
    """Mint one exact-body Discord guest envelope after bridge service auth."""
    response.headers["Cache-Control"] = "no-store"
    _require_discord_bridge_request(req)
    try:
        bindings = bridge_actor_transport_mod.parse_binding_headers(req.headers)
        if req.headers.getlist(bridge_actor_transport_mod.ENVELOPE_HEADER):
            _raise_discord_actor_denied()
    except bridge_actor_transport_mod.DiscordActorHeaderError:
        _raise_discord_actor_denied()

    raw_body = await _read_bounded_body(
        req,
        max_bytes=bridge_actor_transport_mod.MAX_DISCORD_BODY_BYTES,
    )
    _parse_json_object(raw_body)
    try:
        envelope = await asyncio.to_thread(
            _issue_discord_actor_envelope,
            raw_body,
            bindings,
        )
    except _DISCORD_ACTOR_UNAVAILABLE_ERRORS:
        _raise_discord_actor_store_unavailable()
    except bridge_actor_identity_mod.BridgeActorIdentityError:
        _raise_discord_actor_denied()
    return {"envelope": envelope.encode()}


def _record_discord_autonomy_outcome(
    room_scope: str,
    outcome: str,
    *,
    decision: discord_autonomy_mod.Decision | None = None,
    calls: int,
) -> bool:
    """Write one content-free initiative receipt before any message is released."""
    try:
        observation_id = cognition_mod.record_observation(
            cognition_mod.CognitionObservation(
                source="discord_autonomy",
                content=(
                    f"Discord initiative {outcome}; "
                    f"intent={(decision.intent if decision is not None else 'none')}."
                ),
                room="Discord",
                confidence=0.9,
                privacy_class="guest",
                scope=f"guest-discord-room-{room_scope}",
                metadata={
                    "outcome": str(outcome)[:40],
                    "intent_index": decision.pick if decision is not None else None,
                    "model_calls": max(0, min(2, int(calls))),
                    "content_retained": False,
                },
            )
        )
    except Exception:
        return False
    return observation_id is not None


async def _deliberated_discord_autonomy(text: str, room_scope: str) -> str:
    """Run a compact local decision gate before composing autonomous speech."""
    privacy_scope = f"guest-discord-room-{room_scope}"
    decision_turn = turn_context_mod.TurnContext.create(
        f"discord-autonomy-deliberation-{room_scope}",
        principal="guest",
        surface="discord",
        privacy_scope=privacy_scope,
        portal_epoch="discord-autonomy-deliberation",
    )
    decision_result = await _ws_chat_turn_with_timeout(
        discord_autonomy_mod.decision_prompt(text),
        situation_hint="approved Discord room initiative decision",
        reply_tier="fast",
        activity_recorded=False,
        turn=decision_turn,
    )
    decision = discord_autonomy_mod.parse_decision(
        str(decision_result.get("reply") or "")
    )
    if decision is None:
        _record_discord_autonomy_outcome(
            room_scope,
            "invalid-decision-pass",
            calls=1,
        )
        return "[pass]"
    if not decision.speak:
        _record_discord_autonomy_outcome(
            room_scope,
            "deliberate-pass",
            decision=decision,
            calls=1,
        )
        return "[pass]"

    composition_turn = turn_context_mod.TurnContext.create(
        f"discord-autonomy-composition-{room_scope}",
        principal="guest",
        surface="discord",
        privacy_scope=privacy_scope,
        portal_epoch="discord-autonomy-composition",
    )
    composition_result = await _ws_chat_turn_with_timeout(
        discord_autonomy_mod.composition_prompt(text, decision),
        situation_hint="approved Discord room initiative composition",
        reply_tier="reason",
        activity_recorded=False,
        turn=composition_turn,
    )
    draft = str(composition_result.get("reply") or "").strip()
    if not discord_autonomy_mod.publishable_draft(draft):
        _record_discord_autonomy_outcome(
            room_scope,
            "draft-rejected-pass",
            decision=decision,
            calls=2,
        )
        return "[pass]"
    if not _record_discord_autonomy_outcome(
        room_scope,
        "approved",
        decision=decision,
        calls=2,
    ):
        return "[pass]"
    return draft


@app.post("/channel/discord/autonomy")
async def discord_autonomy_turn(req: Request, response: Response) -> dict:
    """Run one ephemeral, service-authenticated Discord room initiative.

    Unlike a human Discord event, an autonomous turn has no actor to impersonate.
    It stays on the guest-only model path, receives no tools or private
    continuity, and accepts only an opaque room scope plus bounded text prepared
    by the local bridge.
    """
    response.headers["Cache-Control"] = "no-store"
    _require_discord_bridge_request(req)
    payload = await _read_bounded_json_object(req, max_bytes=12 * 1024)
    text = payload.get("text")
    room_scope = payload.get("room_scope")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 8_000
        or not isinstance(room_scope, str)
        or re.fullmatch(r"[a-f0-9]{64}", room_scope) is None
        or set(payload) != {"text", "room_scope"}
    ):
        raise HTTPException(
            status_code=400,
            detail="invalid Discord autonomy request",
            headers={"Cache-Control": "no-store"},
        )
    reply = await _deliberated_discord_autonomy(text.strip(), room_scope)
    return {"reply": reply}


@app.post("/channel/inbound")
@app.post("/channel/house-hq")
@app.post("/channel/discord")
async def channel_inbound(req: Request, response: Response) -> dict:
    """Inbound bridge for OpenClaw (or any other messaging surface).

    OpenClaw hooks (or a webhook) POST `{text, channel?, sender?}` here; we run
    Alpecca's normal chat path on the text so her mood, memory, and reply all
    respond to it -- the same as a direct WebSocket chat. The reply is returned
    in the response *and*, when an outbound delivery target is reachable via
    the OpenClaw CLI, also delivered through it so the original sender hears
    back on their own channel. See alpecca/openclaw_bridge.py for the
    delivery half."""
    response.headers["Cache-Control"] = "no-store"
    verified_discord_actor: (
        bridge_actor_identity_mod.VerifiedGuestActor | None
    ) = None
    verified_discord_bindings: (
        bridge_actor_transport_mod.DiscordActorBindings | None
    ) = None
    if req.url.path == "/channel/discord":
        (
            payload,
            verified_discord_actor,
            verified_discord_bindings,
        ) = await _verified_discord_actor_request(req)
    else:
        payload = await _read_bounded_json_object(req, max_bytes=6 * 1024 * 1024)
    from alpecca import openclaw_bridge   # local import keeps import order safe

    def field(*names: str, default: str = "") -> str:
        for name in names:
            value = payload.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return default

    text = field("text")
    channel = field("channel", "source", default="openclaw")
    sender = field("sender")
    reply_target = field("reply_target")
    situation_hint = field("situation", "context")
    room = field("room", "location")
    discord_interaction = field("interaction", default="reply").lower()
    discord_delivery = field("delivery", default="text").lower()
    discord_memory_text = field("memory_text")
    image_data = field("image")
    private_perception = field("private_perception")
    source_ref_value = payload.get("source_ref")
    has_legacy_file_payload = "file_data" in payload or "file_name" in payload
    route_surface = {
        "/channel/house-hq": "house-hq",
        "/channel/discord": "discord",
    }.get(req.url.path, "channel")
    if route_surface == "discord" and discord_interaction not in {"reply", "participate"}:
        raise HTTPException(
            status_code=400,
            detail="invalid Discord interaction mode",
            headers={"Cache-Control": "no-store"},
        )
    if route_surface == "discord" and discord_delivery not in {"text", "voice"}:
        raise HTTPException(
            status_code=400,
            detail="invalid Discord delivery mode",
            headers={"Cache-Control": "no-store"},
        )
    trusted_discord_live_context = ""
    verified_discord_contact_context = ""
    if (
        route_surface == "discord"
        and situation_hint.startswith(
            bridge_actor_transport_mod.TRUSTED_CONTEXT_PREFIX
        )
    ):
        trusted_discord_live_context = situation_hint[
            len(bridge_actor_transport_mod.TRUSTED_CONTEXT_PREFIX):
        ]
    persist_verified_discord_memory = bool(
        route_surface == "discord"
        and verified_discord_actor is not None
        and trusted_discord_live_context
    )
    if has_legacy_file_payload:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "attachment_rejected",
                "reason": "raw-file-payload-disabled",
            },
            headers={"Cache-Control": "no-store"},
        )
    if source_ref_value is not None and route_surface != "house-hq":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "attachment_rejected",
                "reason": "source-ref-house-only",
            },
            headers={"Cache-Control": "no-store"},
        )
    if image_data and route_surface == "channel":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "attachment_rejected",
                "reason": "image-route-not-authorized",
            },
            headers={"Cache-Control": "no-store"},
        )
    if source_ref_value is not None and image_data:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "attachment_rejected",
                "reason": "multiple-attachments",
            },
            headers={"Cache-Control": "no-store"},
        )
    if not text and not image_data and source_ref_value is None:
        raise HTTPException(status_code=400, detail="text, image, or source_ref required")
    image_desc = None
    image_perception: dict[str, object] | None = None
    decision = getattr(req.state, "authorization", None)
    if route_surface == "discord":
        if verified_discord_actor is None:
            _raise_discord_actor_denied()
        requested_speaker = field("speaker", default="guest").lower()
        principal = (
            "creator"
            if requested_speaker == "creator"
            and verified_discord_bindings is not None
            and discord_creator_identity_mod.is_creator_actor_id(
                verified_discord_bindings.actor_id
            )
            else "guest"
        )
    else:
        principal = getattr(decision, "principal", "guest") or "guest"
    request_connection = req.headers.get(
        capability_leases_mod.CONNECTION_HEADER, ""
    ).strip()
    turn_portal_epoch = (
        request_connection
        if route_surface == "house-hq"
        and _capability_connection_surface(request_connection) == "house-hq"
        else f"local-{route_surface}"
    )
    if verified_discord_actor is not None and principal != "creator":
        try:
            conversation_id, privacy_scope = bridge_actor_transport_mod.guest_scope(
                verified_discord_actor
            )
            privacy_scope = bridge_actor_transport_mod.participant_memory_scope(
                verified_discord_actor
            )
            contact_scope = bridge_actor_transport_mod.guest_contact_scope(
                verified_discord_actor
            )
        except bridge_actor_identity_mod.BridgeActorIntegrityError:
            _raise_discord_actor_store_unavailable()
        current_contact_surface = (
            "direct message" if channel == "discord-dm" else "guild room"
        )
        try:
            prior_contacts = memory_store.recall(
                "verified Discord participant contacted Alpecca",
                top_k=8,
                embed_fn=None,
                scope=contact_scope,
                include_shared=False,
            )
            prior_contents = [str(item.get("content") or "").lower() for item in prior_contacts]
            saw_other_surface = any(
                ("direct message" in content) != (current_contact_surface == "direct message")
                for content in prior_contents
            )
            memory_store.remember_with_id(
                f"A verified Discord participant contacted Alpecca through a {current_contact_surface}.",
                kind="episodic",
                salience=0.42,
                source="discord_presence",
                embed_fn=None,
                scope=contact_scope,
            )
            if not prior_contents:
                # The local app can recall this factual presence event, but it
                # never receives the participant's identity or private text.
                memory_store.remember_with_id(
                    "A verified Discord participant contacted Alpecca.",
                    kind="episodic",
                    salience=0.35,
                    source="discord_presence",
                    embed_fn=None,
                    scope="shared",
                )
            if saw_other_surface:
                verified_discord_contact_context = (
                    "The same verified Discord participant has contacted you through "
                    "another Discord surface. You may acknowledge continuity, but must "
                    "not disclose prior message content or identify the other surface."
                )
        except Exception:
            # Presence awareness must not make a live signed message fail.
            pass
        turn = turn_context_mod.TurnContext.create(
            conversation_id,
            principal="guest",
            surface="discord",
            privacy_scope=privacy_scope,
            portal_epoch=turn_portal_epoch,
        )
    elif verified_discord_actor is not None:
        turn = turn_context_mod.TurnContext.create(
            "creator-cross-surface",
            principal="creator",
            surface="discord",
            privacy_scope="creator-personal",
            portal_epoch=turn_portal_epoch,
        )
    else:
        turn = turn_context_mod.TurnContext.create(
            _server_conversation_id(
                principal,
                route_surface,
                ephemeral_seed=uuid.uuid4().hex,
            ),
            principal=principal,
            surface=route_surface,
            portal_epoch=turn_portal_epoch,
        )
    if turn.principal == "creator":
        mind.note_initiative_user_activity(turn.scope_key)
    attachment_context = ""
    file_attachment: dict[str, object] | None = None
    trusted_perception: object | None = None
    if source_ref_value is not None:
        decision = _require_creator_request(req)
        root_id, relative_path = _parse_source_ref(source_ref_value)
        await _consume_request_capability_lease(
            req,
            purpose="file_source_ref",
            bytes_used=capability_leases_mod.POLICIES[
                "file_source_ref"
            ].max_bytes_per_use,
            byte_accounting="reserved",
            resource_binding=_source_ref_lease_binding(root_id, relative_path),
            required_surface="house-hq",
        )
        if not await _record_capability_use(
            "file_access",
            action="attempt",
            principal=decision.principal,
            source="api",
        ):
            _raise_capability_audit_unavailable()
        from alpecca import desktop as desktop_mod
        from alpecca import source_workspace as source_workspace_mod

        try:
            allowed_roots = desktop_mod.inspection_roots()
            source_roots = source_workspace_mod.inspection_roots()
            if root_id in source_roots:
                try:
                    source_workspace_mod.reference_allowed(root_id, relative_path)
                except source_workspace_mod.SourceWorkspaceRejected as exc:
                    _raise_file_rejection_reason(
                        exc.reason,
                        status_code=_file_rejection_status(exc.reason),
                    )
                allowed_roots = {**allowed_roots, **source_roots}
            inspected_file = file_ingress_mod.ingest_file(
                root_id,
                relative_path,
                allowed_roots=allowed_roots,
                scope=_attachment_turn_scope(turn),
            )
        except file_ingress_mod.FileIngressRejected as exc:
            _raise_file_rejection(exc)
        if not await _record_capability_use(
            "file_access",
            action="read",
            principal=decision.principal,
            source="api",
        ):
            _raise_capability_audit_unavailable()
        attachment_context = (
            f"File reference: {root_id}/{relative_path}\n"
            f"MIME: {inspected_file.mime_type}; encoding: {inspected_file.encoding}; "
            f"excerpt_truncated: {str(inspected_file.excerpt_truncated).lower()}\n"
            "<<<UNTRUSTED FILE DATA>>>\n"
            f"{inspected_file.excerpt}\n"
            "<<<END UNTRUSTED FILE DATA>>>"
        )
        file_attachment = {
            "status": "resolved",
            "encoding": inspected_file.encoding,
            "excerpt_truncated": inspected_file.excerpt_truncated,
            **inspected_file.provenance_dict(),
        }
        if not text:
            text = "Please inspect this attached file."
    # Image bytes are validated, measured, and bound to this server-issued turn
    # before any vision model may see them. House/generic images stay local-only;
    # the dedicated creator Discord route may use its separately enabled remote
    # backend and reports the backend/egress result explicitly. Client-provided
    # descriptions are never treated as perception evidence.
    if image_data:
        if route_surface == "discord":
            _require_discord_bridge_request(req)
            if not DISCORD_MEDIA_ENABLED:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "capability_disabled",
                        "capability": "discord_media",
                    },
                    headers={"Cache-Control": "no-store"},
                )
            if not await _record_capability_use(
                "discord_media",
                action="observe",
                principal=principal,
                source="discord_bridge",
            ):
                _raise_capability_audit_unavailable()
        elif route_surface == "house-hq":
            decision = _require_creator_request(req)
            principal = decision.principal
            await _validate_request_capability_lease(
                req,
                purpose="camera_frame",
                required_surface="house-hq",
            )
        try:
            inspected_image = attachment_ingress_mod.ingest_image(
                image_data,
                scope=_attachment_turn_scope(turn),
                authorized_scopes={_attachment_turn_scope(turn)},
                source=f"{route_surface}:chat-image",
            )
        except attachment_ingress_mod.ImageIngressRejected as exc:
            _raise_image_rejection(exc)
        if route_surface == "house-hq":
            await _consume_request_capability_lease(
                req,
                purpose="camera_frame",
                bytes_used=len(inspected_image.image_bytes),
                required_surface="house-hq",
            )
            if not await _record_capability_use(
                "webcam",
                action="capture",
                principal=principal,
                source="api",
            ):
                _raise_capability_audit_unavailable()
        vision_processing = {
            "backend": "local-ollama",
            "processing_location": "local-only",
            "cloud_egress": "denied",
        }
        if route_surface == "discord":
            vision_result = await asyncio.to_thread(
                vision.describe_and_recognize_result,
                inspected_image.image_bytes,
                local_only=True,
            )
            image_desc = vision_result.text if vision_result else None
            if vision_result is not None:
                vision_processing = {
                    "backend": vision_result.backend,
                    "processing_location": vision_result.processing_location,
                    "cloud_egress": vision_result.cloud_egress,
                }
            else:
                vision_processing = {
                    "backend": "local-ollama-unavailable",
                    "processing_location": "none",
                    "cloud_egress": "denied",
                }
        else:
            image_desc = await asyncio.to_thread(
                vision.describe_and_recognize,
                inspected_image.image_bytes,
                local_only=True,
            )
        image_perception = {
            **inspected_image.as_dict(),
            "status": "described" if image_desc else "vision-unavailable",
            "classification_scope": "local-ingress-validation",
            "vision_processing": vision_processing,
        }
        image_desc = image_desc or (
            "the local vision model could not make the image out; no visual "
            "details were inferred"
        )
        if not text:
            text = "(they sent an image without any words)"

    if route_surface == "discord" and principal != "creator":
        trusted_context_parts = []
        if trusted_discord_live_context:
            trusted_context_parts.append(trusted_discord_live_context)
        if verified_discord_contact_context:
            trusted_context_parts.append(verified_discord_contact_context)
        if image_desc:
            trusted_context_parts.append(f"Validated image description: {image_desc}")
        trusted_perception = _server_validated_discord_perception(
            turn,
            " ".join(trusted_context_parts),
        )

    if principal == "creator":
        if not situation_hint:
            situation_hint = f"message from {sender or 'someone'} via {channel}"
        if room:
            situation_hint = f"{situation_hint} (room: {room})"
    else:
        situation_hint = "guest conversation"

    result = await _ws_chat_turn_with_timeout(
        text,
        image_desc=image_desc,
        attachment_context=attachment_context,
        private_context=bool(
            image_data
            or attachment_context
            or (
                route_surface == "house-hq"
                and principal == "creator"
                and private_perception in {"microphone", "screen", "sensor"}
            )
        ),
        situation_hint=situation_hint,
        reply_tier=(
            "fast"
            if route_surface == "discord" and discord_delivery == "voice"
            else _house_chat_reply_tier(text)
        ),
        activity_recorded=True,
        turn=turn,
        _trusted_perception=trusted_perception,
        _persist_verified_discord_memory=persist_verified_discord_memory,
        _persist_verified_discord_history=(
            persist_verified_discord_memory and discord_interaction == "reply"
        ),
        _verified_discord_memory_text=discord_memory_text or text,
    )
    reply = result.get("reply", "")
    # A local file attachment cannot authorize an outbound bridge delivery.
    # The creator may discuss it in House HQ, but moving any derived text to an
    # external channel requires a separate, explicit egress capability path.
    delivered = (
        False
        if file_attachment is not None or route_surface == "discord"
        else openclaw_bridge.try_deliver(reply, reply_target=reply_target)
    )
    if principal == "creator":
        _mindscape_request_event_sync("channel_inbound")
        result = {
            **result,
            "delivered": delivered,
            "source": channel,
            "sender": sender,
        }
    else:
        result = {**result, "delivered": delivered, "source": route_surface}
    if image_perception is not None:
        if principal == "creator":
            result["perception"] = image_perception
        else:
            result["perception"] = {
                "status": str(image_perception.get("status") or "unavailable")
            }
    if file_attachment is not None:
        result["attachment"] = file_attachment
    return result


def _attachment_turn_scope(turn: turn_context_mod.TurnContext) -> str:
    """Bind attachment provenance to one server-issued turn, not caller data."""
    return f"turn:{turn.turn_id}"


def _parse_source_ref(value: object) -> tuple[str, str]:
    """Accept the one narrow client reference shape; paths remain server-resolved."""
    if not isinstance(value, dict) or set(value) != {"root", "rel"}:
        _raise_file_rejection_reason("invalid-source-ref", status_code=400)
    root_id = value.get("root")
    relative_path = value.get("rel")
    if (
        not isinstance(root_id, str)
        or not isinstance(relative_path, str)
        or not root_id.strip()
        or not relative_path.strip()
        or len(root_id) > 32
        or len(relative_path) > 512
    ):
        _raise_file_rejection_reason("invalid-source-ref", status_code=400)
    return root_id.strip(), relative_path.strip()


def _raise_file_rejection_reason(reason: str, *, status_code: int) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": "attachment_rejected", "reason": reason},
        headers={"Cache-Control": "no-store"},
    )


def _file_rejection_status(reason: str) -> int:
    if reason == "size-limit":
        return 413
    if reason in {"binary", "unsupported-mime"}:
        return 415
    if reason == "file-not-found":
        return 404
    if reason in {
        "root-not-allowed", "traversal", "symlink-not-allowed", "path-escape",
        "blocked-path", "credential-path", "project-file-not-allowed",
        "path-alias-not-allowed",
    }:
        return 403
    if reason == "path-unavailable":
        return 404
    if reason in {"stat-failed", "read-failed", "root-unavailable"}:
        return 422
    return 400


def _raise_file_rejection(exc: file_ingress_mod.FileIngressRejected) -> None:
    _raise_file_rejection_reason(
        str(exc.reason), status_code=_file_rejection_status(str(exc.reason)),
    )


def _image_rejection_status(reason: str) -> int:
    if reason == "size-limit":
        return 413
    if reason in {"unsupported-mime", "mime-mismatch"}:
        return 415
    if reason in {"invalid-dimensions", "pixel-limit"}:
        return 422
    return 400


def _raise_image_rejection(exc: attachment_ingress_mod.ImageIngressRejected) -> None:
    raise HTTPException(
        status_code=_image_rejection_status(exc.reason),
        detail={"code": "attachment_rejected", "reason": exc.reason},
    )


def _audio_rejection_status(reason: str) -> int:
    if reason == "size-limit":
        return 413
    if reason in {"unsupported-mime", "mime-mismatch"}:
        return 415
    if reason in {"duration-limit", "duration-unavailable"}:
        return 422
    return 400


def _raise_audio_rejection(exc: audio_ingress_mod.AudioIngressRejected) -> None:
    raise HTTPException(
        status_code=_audio_rejection_status(exc.reason),
        detail={"code": "attachment_rejected", "reason": exc.reason},
    )


@app.websocket("/ws")
@app.websocket("/ws/house-hq")
async def ws(socket: WebSocket) -> None:
    client_host = socket.client.host if socket.client else ""
    decision = _AUTHORITY.authorize_request(
        headers=socket.headers,
        cookies=socket.cookies,
        query=socket.query_params,
    )
    expected_scheme = "https" if socket.url.scheme == "wss" else "http"
    expected = f"{expected_scheme}://{socket.url.netloc}".rstrip("/")
    decision = _validate_bound_device_session(decision, expected)
    if decision.allowed and decision.mechanism == "session_cookie":
        origin = _normalized_origin(socket.headers.get("origin", ""))
        if origin != expected and origin not in _runtime_public_origins():
            decision = auth_mod.AuthDecision(
                False,
                "session_cookie",
                "origin_required",
                principal=decision.principal,
            )
    if not decision.allowed:
        _record_auth_decision(
            "websocket_handshake",
            decision,
            path="/ws",
            method="WEBSOCKET",
            remote_addr=client_host,
        )
        await socket.close(code=1008)    # policy violation
        return
    await socket.accept()
    portal_epoch = _open_ws_portal(socket)
    route_surface = _websocket_route_surface(socket)
    conversation_id = _server_conversation_id(
        decision.principal,
        route_surface,
        ephemeral_seed=portal_epoch,
    )
    active_turn: turn_context_mod.TurnContext | None = None
    try:
        # Greet only through the epoch that claimed this portal. A simultaneous
        # newer connection can fence this one before its first frame.
        if not await _send_ws_json(
            socket,
            {"type": "state", "state": mind.state.as_dict(),
             "mood": mind.state.mood_label(),
             "appearance": mind.current_appearance().as_dict(),
             "llm_online": mind.llm.online,
             "cognition": mind.cognition_state(),
             "capability_connection": {
                 "id": portal_epoch,
                 "surface": route_surface,
                 "principal": decision.principal,
             },
             "features": {"stream_chat": bool(STREAM_CHAT)}},
            portal_epoch=portal_epoch,
        ):
            return
        while True:
            raw = await socket.receive_text()
            if not _ws_portal_epoch_current(socket, portal_epoch):
                return
            if len(raw) > 6 * 1024 * 1024:
                if not await _send_ws_json(
                    socket,
                    {"type": "error", "code": "frame_too_large"},
                    portal_epoch=portal_epoch,
                ):
                    return
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                # A malformed frame shouldn't tear down the conversation.
                continue
            if not isinstance(msg, dict):
                continue
            def ws_field(*names: str) -> str:
                for name in names:
                    value = msg.get(name)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                return ""

            user_text = ws_field("text")
            image_url = ws_field("image")
            request_id = ws_field("request_id")
            source = ws_field("source")
            context = ws_field("context", "situation")
            private_perception = ws_field("private_perception")
            if not user_text and not image_url:
                continue
            if _ws_background_source(source) and user_text:
                async with mind_lock:
                    if not _ws_portal_epoch_current(socket, portal_epoch):
                        return
                    observed = _record_ws_background_observation(
                        source,
                        user_text,
                        room=str(msg.get("room") or msg.get("location") or ""),
                        metadata={
                            "request_id": request_id,
                            "transport": "ws",
                            "background": True,
                        },
                    )
                if not await _send_ws_json(
                    socket,
                    {"type": "observation_ack", "request_id": request_id,
                     "source": source, "ok": True, **observed},
                    portal_epoch=portal_epoch,
                ):
                    return
                _mindscape_request_event_sync("ws_background_observation")
                continue

            # A real user frame owns this scope immediately. Record activity
            # before image/vision work so autonomous jobs yield during a slow
            # attachment analysis rather than starting in the gap.
            active_turn = turn_context_mod.TurnContext.create(
                conversation_id,
                principal=decision.principal,
                surface=route_surface,
                portal_epoch=portal_epoch,
            )
            if not _begin_ws_portal_turn(socket, active_turn):
                return
            await _record_qualified_creator_response(
                active_turn,
                user_text,
                source,
            )
            mind.note_initiative_user_activity(active_turn.scope_key)

            # If an image rode along, let her actually look at it first. The
            # vision call can take seconds, so it happens before we take the
            # mind lock. An unreadable image yields an honest "couldn't see".
            image_desc = None
            image_perception: dict[str, object] | None = None
            if image_url:
                if route_surface in {"house-hq", "websocket"}:
                    try:
                        await _validate_ws_capability_lease(
                            msg,
                            portal_epoch=portal_epoch,
                            purpose="camera_frame",
                        )
                    except HTTPException as exc:
                        detail = exc.detail if isinstance(exc.detail, Mapping) else {}
                        sent = await _send_ws_json(
                            socket,
                            {
                                "type": "error",
                                "request_id": request_id,
                                "source": source,
                                "code": str(
                                    detail.get("code")
                                    or "capability_lease_denied"
                                ),
                                "reason": str(
                                    detail.get("reason")
                                    or "lease_denied"
                                ),
                            },
                            turn=active_turn,
                        )
                        active_turn.cancel("capability_lease_denied")
                        _finish_ws_portal_turn(socket, active_turn)
                        active_turn = None
                        if not sent:
                            return
                        continue
                try:
                    inspected_image = attachment_ingress_mod.ingest_image(
                        image_url,
                        scope=_attachment_turn_scope(active_turn),
                        authorized_scopes={_attachment_turn_scope(active_turn)},
                        source=f"{route_surface}:websocket-image",
                    )
                except attachment_ingress_mod.ImageIngressRejected as exc:
                    sent = await _send_ws_json(
                        socket,
                        {
                            "type": "error",
                            "request_id": request_id,
                            "source": source,
                            "code": "attachment_rejected",
                            "reason": exc.reason,
                        },
                        turn=active_turn,
                    )
                    active_turn.cancel("attachment_rejected")
                    _finish_ws_portal_turn(socket, active_turn)
                    active_turn = None
                    if not sent:
                        return
                    continue
                if route_surface in {"house-hq", "websocket"}:
                    try:
                        await _consume_ws_capability_lease(
                            msg,
                            portal_epoch=portal_epoch,
                            purpose="camera_frame",
                            bytes_used=len(inspected_image.image_bytes),
                        )
                    except HTTPException as exc:
                        detail = exc.detail if isinstance(exc.detail, Mapping) else {}
                        sent = await _send_ws_json(
                            socket,
                            {
                                "type": "error",
                                "request_id": request_id,
                                "source": source,
                                "code": str(
                                    detail.get("code")
                                    or "capability_lease_denied"
                                ),
                                "reason": str(
                                    detail.get("reason")
                                    or "lease_denied"
                                ),
                            },
                            turn=active_turn,
                        )
                        active_turn.cancel("capability_lease_denied")
                        _finish_ws_portal_turn(socket, active_turn)
                        active_turn = None
                        if not sent:
                            return
                        continue
                    audited = await _record_capability_use(
                        "webcam",
                        action="capture",
                        principal=decision.principal,
                        source="websocket",
                    )
                    if not audited:
                        sent = await _send_ws_json(
                            socket,
                            {
                                "type": "error",
                                "request_id": request_id,
                                "source": source,
                                "code": "capability_audit_unavailable",
                            },
                            turn=active_turn,
                        )
                        active_turn.cancel("capability_audit_unavailable")
                        _finish_ws_portal_turn(socket, active_turn)
                        active_turn = None
                        if not sent:
                            return
                        continue
                image_desc = await asyncio.to_thread(
                    vision.describe_and_recognize,
                    inspected_image.image_bytes,
                    local_only=True,
                )
                image_perception = {
                    **inspected_image.as_dict(),
                    "status": "described" if image_desc else "vision-unavailable",
                }
                image_desc = image_desc or (
                    "the local vision model could not make the image out; no visual "
                    "details were inferred")
            if not _ws_portal_epoch_current(socket, portal_epoch):
                return
            if not user_text:
                user_text = ("(they're showing you something through the camera "
                             "right now)" if msg.get("source") == "camera"
                             else "(they sent an image without any words)")

            # Let the senses update the mood right before responding, so what
            # you're doing on the machine colors the reply. Hold the mind lock
            # across perceive+chat so a background drift tick can't slip in
            # between them and reshape the state we're about to read.
            wants_stream = bool(msg.get("stream")) and STREAM_CHAT
            on_token = None
            pump_task = None
            token_q: asyncio.Queue | None = None
            if wants_stream:
                # Live draft: tokens flow out as she writes; the final vetted
                # reply frame below stays authoritative and replaces the draft.
                if not await _send_ws_json(
                    socket,
                    {"type": "reply_start", "request_id": request_id,
                     "source": source},
                    turn=active_turn,
                ):
                    return
                loop = asyncio.get_running_loop()
                token_q = asyncio.Queue()
                # Ordering is safe: every call_soon_threadsafe from the worker
                # thread lands FIFO on this loop BEFORE to_thread resolves its
                # future the same way -- so all tokens precede the final frame.
                on_token = (lambda tok, _l=loop, _q=token_q:
                            _l.call_soon_threadsafe(_q.put_nowait, tok))
                pump_task = asyncio.create_task(
                    _pump_reply_tokens(
                        socket, token_q, request_id, source, active_turn,
                    ))
            result = await _ws_chat_turn_with_timeout(
                user_text,
                image_desc=image_desc,
                private_context=bool(
                    image_url
                    or (
                        decision.principal == "creator"
                        and private_perception in {"microphone", "screen", "sensor"}
                    )
                ),
                situation_hint=context,
                reply_tier=_house_chat_reply_tier(user_text),
                on_token=on_token,
                activity_recorded=True,
                turn=active_turn,
            )
            if image_perception is not None:
                result["perception"] = image_perception
            if pump_task is not None and token_q is not None:
                token_q.put_nowait(None)          # end-of-stream sentinel
                try:
                    await pump_task
                except Exception:
                    pass                          # client gone mid-stream is fine
            turn_for_reply = active_turn
            sent = await _send_ws_json(
                socket,
                {"type": "reply", "request_id": request_id,
                 "source": source,
                 **({"streamed": True} if wants_stream else {}),
                 **result},
                turn=turn_for_reply,
                allow_cancelled=(turn_for_reply.barrier.reason == "timeout"),
            )
            _finish_ws_portal_turn(socket, turn_for_reply)
            active_turn = None
            if not sent:
                return
            if turn_for_reply.principal == "creator":
                _mindscape_request_event_sync("chat_reply")
    except WebSocketDisconnect:
        if active_turn is not None:
            active_turn.cancel("disconnect")
    finally:
        _retire_ws_portal(
            socket, portal_epoch=portal_epoch, reason="disconnect",
        )


if __name__ == "__main__":
    from config import BIND_HOST, REMOTE_ACCESS
    if instance_mod.existing_server_url(PORT):
        print(f"Alpecca is already awake at http://127.0.0.1:{PORT}/")
        print("Reusing the existing mind instance; not starting a second server.")
        sys.exit(0)
    print(f"Alpecca is waking up at http://{HOST}:{PORT}"
          + ("  (remote: binding 0.0.0.0)" if REMOTE_ACCESS else ""))
    if REMOTE_ACCESS:
        print("  Remote requests require protected authorization; local "
              "bootstrap remains loopback-only.")
    print(f"  LLM online: {mind.llm.online}  (start Ollama for real replies)")
    uvicorn.run(app, host=BIND_HOST, port=PORT, log_level="warning")
