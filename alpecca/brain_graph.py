"""Evidence-backed plugin graph for Alpecca's live architecture.

Plugins are declarative JSON. They may select an allowlisted probe but cannot
import code or execute commands. This keeps automatic discovery useful without
turning a diagram extension into an unreviewed code-execution path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any, Callable, Mapping


SCHEMA_VERSION = 1
VALID_STATES = {"healthy", "live", "degraded", "disabled", "unfinished", "unknown"}
BUILTIN_PLUGIN_DIR = Path(__file__).with_name("brain_plugins")
LOCAL_PLUGIN_DIR = Path(__file__).resolve().parents[1] / "data" / "brain_plugins"
SOUL_VECTOR_SCHEMA = "alpecca.soul-perspective-vector.v1"
PAGEFILE_LIVE_EVIDENCE_SCHEMA = "alpecca.phase7.pagefile-live-evidence.v1"
SOUL_RUNTIME_SCHEMA = "alpecca.soul-runtime-decision.v1"
ASR_DISPATCH_STATUS_SCHEMA = "alpecca.asr-dispatch-status.v1"
ASR_SELECTION_SCHEMA = "alpecca.asr-selection.v1"
VOICE_RUNTIME_SCHEMA = "alpecca.voice-runtime.v1"
MAX_PROBE_COUNT = 1_000_000
SOUL_PERSPECTIVE_ORDER = (
    "Feeler",
    "Expressor",
    "Carer",
    "Doer",
    "Wanderer",
    "Reflector",
    "Improver",
)


@dataclass(frozen=True)
class ProbeResult:
    state: str
    summary: str
    progress: int | None = None
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state if self.state in VALID_STATES else "unknown",
            "summary": self.summary,
            "progress": self.progress,
            "evidence": list(self.evidence),
        }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool_probe(
    facts: Mapping[str, Any], key: str, *, ready: str, disabled: str,
    evidence: str,
) -> ProbeResult:
    value = facts.get(key)
    if value is True:
        return ProbeResult("healthy", ready, 100, (evidence,))
    if value is False:
        return ProbeResult("disabled", disabled, 0, (evidence,))
    return ProbeResult("unknown", "No authoritative runtime reading is available.", None, (evidence,))


def _runtime(facts: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(facts.get("runtime"))


def _probe_server(facts: Mapping[str, Any]) -> ProbeResult:
    return ProbeResult("healthy", "The authoritative local backend produced this snapshot.", 100, ("GET /brain/graph",))


def _probe_model(facts: Mapping[str, Any]) -> ProbeResult:
    runtime = _runtime(facts)
    models = _mapping(runtime.get("models"))
    ready = bool(models.get("chat_ready") or runtime.get("llm_online"))
    model = str(models.get("reason") or facts.get("model") or "configured local model")
    return ProbeResult(
        "healthy" if ready else "degraded",
        f"{model} is available for live reasoning." if ready else f"{model} is configured but not verified ready.",
        100 if ready else 45,
        ("runtime.models.chat_ready", "runtime.models.reason"),
    )


def _probe_memory(facts: Mapping[str, Any]) -> ProbeResult:
    count = facts.get("memory_count")
    if isinstance(count, int) and count >= 0:
        return ProbeResult("healthy", f"{count:,} persistent memories are indexed locally.", 100, ("memory_store.count",))
    return ProbeResult("unknown", "The memory store did not expose a count for this snapshot.", None, ("memory_store.count",))


def _unit_score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return score if math.isfinite(score) and 0.0 <= score <= 1.0 else None


def _safe_soul_vector(value: object) -> dict[str, Any] | None:
    """Validate and project fixed numeric Soul evidence; discard all prose."""
    vector = _mapping(value)
    order = vector.get("order")
    scores = vector.get("scores")
    active = vector.get("active")
    ranks = vector.get("ranks")
    if (
        vector.get("schema") != SOUL_VECTOR_SCHEMA
        or not isinstance(order, (list, tuple))
        or not all(isinstance(item, str) for item in order)
        or tuple(order) != SOUL_PERSPECTIVE_ORDER
        or not all(
            isinstance(items, (list, tuple))
            and len(items) == len(SOUL_PERSPECTIVE_ORDER)
            for items in (scores, active, ranks)
        )
    ):
        return None
    safe_scores = tuple(_unit_score(item) for item in scores)
    if any(item is None for item in safe_scores):
        return None
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item not in {0, 1}
        for item in active
    ):
        return None
    if any(
        isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 4
        for item in ranks
    ):
        return None
    focus_index = vector.get("focus_index")
    if (
        isinstance(focus_index, bool)
        or not isinstance(focus_index, int)
        or not -1 <= focus_index < len(SOUL_PERSPECTIVE_ORDER)
    ):
        return None
    contradiction = vector.get("contradiction")
    pressure = vector.get("pressure")
    escalate = vector.get("escalate")
    model_calls = vector.get("model_calls")
    if (
        not isinstance(contradiction, bool)
        or pressure not in {"none", "high", "overflow"}
        or not isinstance(escalate, bool)
        or escalate != (contradiction or pressure != "none")
        or vector.get("source") != "deterministic"
        or isinstance(model_calls, bool)
        or not isinstance(model_calls, int)
        or model_calls != 0
        or vector.get("independent_transformers") is not False
        or vector.get("advisory_only") is not True
        or vector.get("focus_stage") != "deterministic_arbitration"
    ):
        return None
    return {
        "order": SOUL_PERSPECTIVE_ORDER,
        "scores": tuple(round(float(item), 3) for item in safe_scores),
        "active": tuple(int(item) for item in active),
        "ranks": tuple(int(item) for item in ranks),
        "focus_index": focus_index,
        "contradiction": contradiction,
        "pressure": pressure,
        "escalate": escalate,
    }


def _probe_soul(facts: Mapping[str, Any]) -> ProbeResult:
    count = facts.get("soul_agent_count")
    if count == 7:
        hyfuser = _mapping(facts.get("hyfuser_soul"))
        transformer_ready = hyfuser.get("ready") is True
        transformer_configured = hyfuser.get("configured") is True
        vector = _safe_soul_vector(facts.get("soul_perspective_vector"))
        if vector is not None:
            evidence = (
                "soul.perspective_vector.schema=v1",
                "soul.perspective_vector.order=" + ",".join(vector["order"]),
                "soul.perspective_vector.scores="
                + ",".join(f"{item:.3f}" for item in vector["scores"]),
                "soul.perspective_vector.active="
                + ",".join(str(item) for item in vector["active"]),
                "soul.perspective_vector.ranks="
                + ",".join(str(item) for item in vector["ranks"]),
                f"soul.perspective_vector.focus_index={vector['focus_index']}",
                f"soul.perspective_vector.contradiction={str(vector['contradiction']).lower()}",
                f"soul.perspective_vector.pressure={vector['pressure']}",
                f"soul.perspective_vector.escalate={str(vector['escalate']).lower()}",
                "soul.perspective_vector.model_calls=0",
                "soul.perspective_vector.independent_transformers=false",
                "soul.perspective_vector.advisory_only=true",
                "soul.hyfuser.shared_backbone=true",
                "soul.hyfuser.distinct_transformer_heads=7",
                f"soul.hyfuser.configured={str(transformer_configured).lower()}",
                f"soul.hyfuser.ready={str(transformer_ready).lower()}",
                "soul.hyfuser.shadow_only=true",
            )
            if transformer_ready:
                return ProbeResult(
                    "degraded",
                    "Seven deterministic perspectives remain authoritative; seven "
                    "distinct ROG transformer heads are live in shadow mode over one "
                    "shared multimodal backbone and cannot choose actions.",
                    84,
                    evidence,
                )
            return ProbeResult(
                "degraded",
                "Seven deterministic perspectives are live; the seven-head "
                "transformer architecture is source-complete but its ROG shadow "
                "runtime is not ready. Deterministic arbitration remains active.",
                76 if transformer_configured else 74,
                evidence,
            )
        return ProbeResult("degraded", "Seven bounded perspectives are implemented; they are not seven independent transformer instances.", 72, ("alpecca/soul.py", "soul_agent_count=7"))
    return ProbeResult("unfinished", f"Expected seven bounded perspectives; observed {count!r}.", 30, ("alpecca/soul.py",))


def _probe_voice(facts: Mapping[str, Any]) -> ProbeResult:
    """Project only bounded voice-runtime facts; supplied reason prose is ignored."""

    status = _mapping(facts.get("voice_runtime"))
    if not status:
        return ProbeResult(
            "unknown",
            "No authoritative voice runtime snapshot was supplied.",
            None,
            ("facts.voice_runtime",),
        )
    house = _mapping(status.get("house"))
    synthesis = _mapping(status.get("synthesis"))
    discord = _mapping(status.get("discord"))
    safety = _mapping(status.get("safety"))
    routes = _mapping(synthesis.get("routes"))
    route_names = ("cloud", "f5", "kokoro")
    route_statuses = {name: _mapping(routes.get(name)) for name in route_names}
    component_states = {
        "house": _bounded_identifier(
            house.get("state"),
            frozenset({"idle", "listening", "thinking", "speaking", "degraded", "unknown"}),
        ),
        "synthesis": _bounded_identifier(
            synthesis.get("state"),
            frozenset({"active", "ready", "unavailable", "degraded", "disabled", "unknown"}),
        ),
        "discord": _bounded_identifier(
            discord.get("state"),
            frozenset({"active", "ready", "disconnected", "unavailable", "degraded", "disabled", "unknown"}),
        ),
    }
    selected_route = synthesis.get("selected_route")
    if selected_route is not None and selected_route not in route_names:
        selected_route = None
    valid = (
        status.get("schema") == VOICE_RUNTIME_SCHEMA
        and status.get("state") in {"healthy", "degraded", "disabled", "unknown"}
        and isinstance(status.get("ready"), bool)
        and status.get("ready") is (status.get("state") == "healthy")
        and isinstance(status.get("degraded"), bool)
        and all(value is not None for value in component_states.values())
        and all(route_statuses.values())
        and all(
            route.get("state")
            in {"active", "ready", "unavailable", "degraded", "disabled", "unknown"}
            and (route.get("enabled") is None or isinstance(route.get("enabled"), bool))
            and (route.get("ready") is None or isinstance(route.get("ready"), bool))
            and isinstance(route.get("active"), bool)
            for route in route_statuses.values()
        )
        and all(
            safety.get(key) is False
            for key in (
                "contains_secrets",
                "contains_content",
                "contains_raw_audio",
                "readiness_from_installed_files",
            )
        )
    )
    if not valid:
        return ProbeResult(
            "unknown",
            "The supplied voice runtime snapshot did not satisfy the bounded evidence contract.",
            None,
            ("facts.voice_runtime",),
        )

    evidence = (
        "voice_runtime.schema=v1",
        f"voice_runtime.state={status['state']}",
        f"voice_runtime.house={component_states['house']}",
        f"voice_runtime.synthesis={component_states['synthesis']}",
        f"voice_runtime.discord={component_states['discord']}",
        "voice_runtime.selected_route=" + (str(selected_route) if selected_route else "none"),
        "voice_runtime.content_free=true",
    )
    degraded = (
        status.get("degraded") is True
        or status.get("state") == "degraded"
        or house.get("degraded") is True
        or synthesis.get("degraded") is True
        or discord.get("degraded") is True
        or "degraded" in component_states.values()
        or any(route.get("state") == "degraded" for route in route_statuses.values())
    )
    if degraded:
        return ProbeResult(
            "degraded",
            "Voice runtime evidence is present, but one or more live paths reported degraded.",
            50,
            evidence,
        )

    house_active = (
        (component_states["house"] == "listening" and house.get("listening") is True and house.get("mic_live") is True)
        or (component_states["house"] == "thinking" and house.get("thinking") is True)
        or (component_states["house"] == "speaking" and house.get("speaking") is True)
    )
    synthesis_live = any(
        route.get("ready") is True
        and route.get("state") in {"active", "ready"}
        for route in route_statuses.values()
    )
    send = _mapping(discord.get("send"))
    receive = _mapping(discord.get("receive"))
    vad = _mapping(discord.get("vad"))
    discord_live = component_states["discord"] in {"active", "ready"} and any(
        channel.get("ready") is True
        and channel.get("state") in {"active", "ready"}
        for channel in (send, receive, vad)
    )
    live = status.get("ready") is True and status.get("state") == "healthy" and (
        house_active or synthesis_live or discord_live
    )
    if live:
        return ProbeResult(
            "live",
            "Bounded runtime evidence verifies a live House, synthesis, or Discord voice path.",
            100,
            evidence,
        )

    all_routes_disabled = all(
        route.get("enabled") is False and route.get("state") == "disabled"
        for route in route_statuses.values()
    )
    discord_disabled = all(
        channel.get("enabled") is False and channel.get("state") == "disabled"
        for channel in (send, receive, vad)
    )
    house_inactive = (
        house.get("mic_live") is False
        and house.get("listening") is False
        and house.get("thinking") is False
        and house.get("speaking") is False
    )
    disabled = status.get("state") == "disabled" or (
        all_routes_disabled and discord_disabled and house_inactive
    )
    if disabled:
        return ProbeResult(
            "disabled",
            "Voice runtime evidence explicitly reports all House, synthesis, and Discord paths disabled.",
            0,
            evidence,
        )
    return ProbeResult(
        "unknown",
        "A bounded voice runtime snapshot was supplied, but it did not verify a live, degraded, or disabled path.",
        None,
        evidence,
    )


def _probe_senses(facts: Mapping[str, Any]) -> ProbeResult:
    senses = _mapping(facts.get("senses"))
    active = sorted(key for key, value in senses.items() if value is True)
    if active:
        return ProbeResult("healthy", f"Active channels: {', '.join(active)}.", 100, ("server._sense_status",))
    return ProbeResult("disabled", "Perception channels are currently gated or unavailable.", 0, ("server._sense_status",))


def _probe_discord(facts: Mapping[str, Any]) -> ProbeResult:
    configured = facts.get("discord_configured")
    running = facts.get("discord_running")
    if configured and running:
        return ProbeResult("healthy", "The configured Discord bridge process is running.", 100, ("Discord credential", "process inventory"))
    if configured:
        return ProbeResult("degraded", "Discord is configured, but a running bridge was not verified.", 50, ("Discord credential", "process inventory"))
    return ProbeResult("disabled", "Discord is not configured for this runtime.", 0, ("Discord credential",))


def _probe_mindpage(facts: Mapping[str, Any]) -> ProbeResult:
    enabled = facts.get("mindpage_enabled")
    pressure = facts.get("memory_pressure")
    if enabled is True:
        detail = "Mindpage budgeting is enabled"
        if isinstance(pressure, (int, float)):
            detail += f"; measured pressure is {max(0, min(100, round(float(pressure) * 100)))}%"
        return ProbeResult("healthy", detail + ".", 100, ("mindpage runtime stats",))
    return ProbeResult("disabled" if enabled is False else "unknown", "Mindpage runtime enablement was not verified.", 0 if enabled is False else None, ("mindpage runtime stats",))


def _probe_mindscape(facts: Mapping[str, Any]) -> ProbeResult:
    configured = facts.get("mindscape_configured")
    return _bool_probe(facts, "mindscape_configured", ready="Encrypted passive continuity backup is configured.", disabled="Cloud continuity backup is not configured.", evidence="mindscape vault status") if configured is not None else ProbeResult("unknown", "Mindscape status was unavailable.", None, ("mindscape vault status",))


def _probe_embodiment(facts: Mapping[str, Any]) -> ProbeResult:
    available = facts.get("vrm_available")
    return _bool_probe(facts, "vrm_available", ready="A VRM 1.0 body is installed and served to House HQ.", disabled="No VRM body is currently installed.", evidence="GET /vrm/manifest") if available is not None else ProbeResult("unknown", "VRM manifest was unavailable.", None, ("GET /vrm/manifest",))


def _probe_rsi(facts: Mapping[str, Any]) -> ProbeResult:
    return ProbeResult("degraded", "Bounded proposal, trial, evaluation, and rollback foundations exist; autonomous recursive code modification is intentionally not complete.", 68, ("alpecca/cognition.py", "behavior trial controller", "HANDOFF.md"))


def _probe_stage(facts: Mapping[str, Any]) -> ProbeResult:
    return ProbeResult("unfinished", "The broader staged roadmap still contains partial and not-started work; inspect its child nodes for current evidence.", 62, ("HANDOFF.md", "docs/ALPECCA_UNIFIED_MASTER_PLAN.md"))


def _probe_stage_complete(_: Mapping[str, Any]) -> ProbeResult:
    return ProbeResult("healthy", "Implemented and covered by repository verification evidence.", 100, ("HANDOFF.md", "tests/"))


def _probe_stage_partial(_: Mapping[str, Any]) -> ProbeResult:
    return ProbeResult("unfinished", "Implementation exists, but a live soak, creator validation, or remaining integration gate is still open.", 65, ("HANDOFF.md",))


def _probe_stage_not_started(_: Mapping[str, Any]) -> ProbeResult:
    return ProbeResult("unfinished", "No production-complete implementation is verified yet.", 0, ("docs/ALPECCA_UNIFIED_MASTER_PLAN.md",))


def _probe_stage_blocked(_: Mapping[str, Any]) -> ProbeResult:
    return ProbeResult(
        "unfinished",
        "A concrete prerequisite or verification gate blocks phase completion.",
        35,
        ("HANDOFF.md", "tests/"),
    )


def _bounded_label(value: object, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def _probe_pagefile(facts: Mapping[str, Any]) -> ProbeResult:
    """Project only fixed, content-free Phase 7 evidence into Brain Garden."""
    surface = _mapping(facts.get("pagefile_evidence"))
    if (
        surface.get("schema") != PAGEFILE_LIVE_EVIDENCE_SCHEMA
        or surface.get("state") != "blocked"
    ):
        surface = {}
    telemetry = _mapping(surface.get("telemetry"))
    telemetry_evidence = _mapping(telemetry.get("evidence"))
    wmi = _mapping(telemetry_evidence.get("wmi"))
    configured = _mapping(telemetry.get("configured"))
    proposal = _mapping(surface.get("proposal"))
    approval = _mapping(surface.get("approval"))
    execution = _mapping(surface.get("execution"))
    gates = _mapping(surface.get("gates"))

    telemetry_state = _bounded_label(
        telemetry.get("state"),
        frozenset({"ready", "partial", "unavailable"}),
    )
    wmi_state = _bounded_label(
        wmi.get("state"),
        frozenset({"available", "partial", "unavailable", "invalid"}),
    )
    configured_mode = _bounded_label(
        configured.get("mode"),
        frozenset({"custom", "system_managed", "none", "unknown"}),
    )
    proposal_state = _bounded_label(
        proposal.get("state"),
        frozenset({"proposed", "blocked", "not_recommended", "unknown"}),
    )
    request_available = approval.get("request_available") is True
    approve_available = approval.get("approve_available") is True
    consume_available = approval.get("consume_available") is True
    raw_tokens_persisted = approval.get("raw_tokens_persisted") is True
    execution_available = execution.get("available") is True

    gate_names = (
        "documented_safe_8192_measurement",
        "fresh_live_pagefile_commit_disk_readback",
        "uac_elevation",
        "separate_minimal_elevated_helper",
        "single_bounded_write",
        "post_write_readback",
    )
    evidence = (
        "phase7.state=blocked",
        f"pagefile.telemetry.state={telemetry_state}",
        f"pagefile.telemetry.wmi={wmi_state}",
        f"pagefile.configuration.mode={configured_mode}",
        f"pagefile.proposal.state={proposal_state}",
        f"pagefile.approval.request={str(request_available).lower()}",
        f"pagefile.approval.approve={str(approve_available).lower()}",
        f"pagefile.approval.consume={str(consume_available).lower()}",
        f"pagefile.approval.raw_tokens_persisted={str(raw_tokens_persisted).lower()}",
        f"pagefile.execution.available={str(execution_available).lower()}",
        *tuple(
            f"pagefile.gate.{name}={str(gates.get(name) is True).lower()}"
            for name in gate_names
        ),
    )
    live_approval_surface = (
        request_available
        and approve_available
        and not consume_available
        and not raw_tokens_persisted
        and not execution_available
    )
    summary = (
        "Bounded read-only pagefile telemetry and digest-bound one-use "
        "CreatorJD request/approval are live; no consume or execution surface "
        "exists. The live safe 8K, fresh readback, UAC, bounded-write, and "
        "post-write gate set blocks phase completion."
        if live_approval_surface
        else
        "Pagefile telemetry or creator approval evidence is unavailable. No "
        "consume or execution surface exists, and the remaining gate set "
        "blocks phase completion."
    )
    progress = 52 if live_approval_surface and telemetry_state == "ready" else 45
    return ProbeResult("unfinished", summary, progress, evidence)


def _bounded_count(value: object, *, positive: bool = False) -> int | None:
    minimum = 1 if positive else 0
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= MAX_PROBE_COUNT
    ):
        return None
    return value


def _bounded_limit(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 1_000_000_000
    ):
        return None
    return value


def _bounded_seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 31_536_000.0:
        return None
    return result


def _bounded_identifier(value: object, allowed: frozenset[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _unknown_research_stage(key: str) -> ProbeResult:
    return ProbeResult(
        "unknown",
        "No bounded authoritative runtime facts were supplied for this stage.",
        None,
        (f"facts.{key}",),
    )


def _probe_temporal_memory_shadow(facts: Mapping[str, Any]) -> ProbeResult:
    status = _mapping(facts.get("temporal_memory"))
    if not status:
        return _unknown_research_stage("temporal_memory")
    if status.get("available") is False:
        return ProbeResult(
            "unfinished",
            "The additive temporal shadow runtime is not available; legacy "
            "SQLite Mindpage recall remains authoritative.",
            20,
            ("temporal_memory.available=false",),
        )
    counters = {
        name: _bounded_count(status.get(name))
        for name in (
            "pending_observations",
            "observations_processed",
            "facts_derived",
            "shadow_comparisons",
        )
    }
    valid = (
        status.get("available") is True
        and status.get("authority") == "sqlite_mindpage"
        and status.get("mode") == "shadow"
        and all(value is not None for value in counters.values())
    )
    if not valid:
        return ProbeResult(
            "unknown",
            "Temporal memory facts did not satisfy the bounded shadow contract.",
            None,
            ("facts.temporal_memory",),
        )
    return ProbeResult(
        "healthy",
        "Temporal memory is processing observations in additive shadow mode; "
        "legacy SQLite Mindpage recall remains authoritative.",
        100,
        (
            "temporal_memory.available=true",
            "temporal_memory.mode=shadow",
            "temporal_memory.authority=sqlite_mindpage",
            f"temporal_memory.pending={counters['pending_observations']}",
            f"temporal_memory.processed={counters['observations_processed']}",
            f"temporal_memory.facts={counters['facts_derived']}",
            f"temporal_memory.shadow_comparisons={counters['shadow_comparisons']}",
        ),
    )


def _probe_selective_soul_runtime(facts: Mapping[str, Any]) -> ProbeResult:
    status = _mapping(facts.get("soul_runtime"))
    if not status:
        return _unknown_research_stage("soul_runtime")
    outcomes = frozenset({
        "not_eligible", "callback_unavailable", "callback_failed",
        "response_rejected", "textual_selection", "invalid_plan",
    })
    outcome = _bounded_identifier(status.get("outcome"), outcomes)
    roles = status.get("roles")
    valid = (
        status.get("schema") == SOUL_RUNTIME_SCHEMA
        and status.get("advisory_only") is True
        and isinstance(status.get("callback_invoked"), bool)
        and isinstance(roles, (list, tuple))
        and tuple(roles) == SOUL_PERSPECTIVE_ORDER
        and outcome is not None
    )
    if not valid:
        return ProbeResult(
            "unknown",
            "No valid bounded selective Soul advisory receipt was supplied.",
            None,
            ("facts.soul_runtime",),
        )
    degraded = outcome in {
        "callback_unavailable", "callback_failed", "response_rejected", "invalid_plan",
    }
    return ProbeResult(
        "degraded" if degraded else "healthy",
        (
            "The selective Soul runtime produced a bounded advisory receipt, but "
            "its optional deliberation path was unavailable or rejected."
            if degraded
            else "The selective Soul runtime produced a bounded advisory receipt; "
            "it does not choose or execute actions."
        ),
        60 if degraded else 100,
        (
            "soul_runtime.schema=v1",
            f"soul_runtime.outcome={outcome}",
            "soul_runtime.advisory_only=true",
            "soul_runtime.roles=7",
            "soul_runtime.callback_invoked="
            + str(status["callback_invoked"]).lower(),
        ),
    )


def _probe_video_companion(facts: Mapping[str, Any]) -> ProbeResult:
    status = _mapping(facts.get("video_companion"))
    if not status:
        return _unknown_research_stage("video_companion")
    if status.get("available") is False:
        return ProbeResult(
            "unfinished", "No bounded Video Companion runtime was verified.", 25,
            ("video_companion.available=false",),
        )
    runtime_state = _bounded_identifier(
        status.get("status"),
        frozenset({"active", "paused", "interrupted", "completed", "stopped"}),
    )
    source_kind = _bounded_identifier(
        status.get("source_kind"), frozenset({"file", "live"})
    )
    timeline_entries = _bounded_count(status.get("timeline_entries"))
    deferred_entries = _bounded_count(status.get("deferred_entries"))
    valid = (
        status.get("available") is True
        and runtime_state is not None
        and source_kind is not None
        and timeline_entries is not None
        and deferred_entries is not None
        and deferred_entries <= timeline_entries
        and status.get("raw_media_retained") is False
    )
    if not valid:
        return ProbeResult(
            "unknown",
            "Video Companion facts did not satisfy the descriptor-only contract.",
            None,
            ("facts.video_companion",),
        )
    state_map = {
        "active": "healthy", "paused": "degraded", "interrupted": "degraded",
        "completed": "healthy", "stopped": "disabled",
    }
    graph_state = state_map[runtime_state]
    return ProbeResult(
        graph_state,
        "Video Companion reported bounded derived timeline state without retaining "
        "raw media.",
        100 if graph_state == "healthy" else (0 if graph_state == "disabled" else 60),
        (
            f"video_companion.status={runtime_state}",
            f"video_companion.source_kind={source_kind}",
            f"video_companion.timeline_entries={timeline_entries}",
            f"video_companion.deferred_entries={deferred_entries}",
            "video_companion.raw_media_retained=false",
        ),
    )


def _probe_asr_dispatch(facts: Mapping[str, Any]) -> ProbeResult:
    status = _mapping(facts.get("asr_dispatch"))
    if not status:
        return _unknown_research_stage("asr_dispatch")
    selection = _mapping(status.get("selection"))
    capabilities = _mapping(status.get("capabilities"))
    selected = selection.get("selected_backend")
    capability = (
        _mapping(capabilities.get(selected)) if isinstance(selected, str) else {}
    )
    valid = (
        status.get("schema") == ASR_DISPATCH_STATUS_SCHEMA
        and selection.get("schema") == ASR_SELECTION_SCHEMA
        and isinstance(selected, str)
        and selected in {"faster-whisper", "moonshine"}
        and isinstance(capability.get("configured"), bool)
        and isinstance(capability.get("ready"), bool)
    )
    if not valid:
        return ProbeResult(
            "unknown", "No valid bounded ASR dispatch status was supplied.", None,
            ("facts.asr_dispatch",),
        )
    ready = capability["configured"] and capability["ready"]
    return ProbeResult(
        "healthy" if ready else "unfinished",
        (
            "The selected ASR backend is configured and reported ready."
            if ready
            else "ASR selected a backend, but readiness was not verified."
        ),
        100 if ready else 45,
        (
            "asr_dispatch.schema=v1",
            f"asr_dispatch.selected={selected}",
            f"asr_dispatch.configured={str(capability['configured']).lower()}",
            f"asr_dispatch.ready={str(capability['ready']).lower()}",
        ),
    )


def _probe_speaker_worker(facts: Mapping[str, Any]) -> ProbeResult:
    status = _mapping(facts.get("speaker_worker"))
    if not status:
        return _unknown_research_stage("speaker_worker")
    profiles = _bounded_count(status.get("enrolled_profiles"))
    max_audio = _bounded_seconds(status.get("max_audio_seconds"))
    backend = status.get("backend")
    valid = (
        status.get("purpose") == "familiarity-only"
        and status.get("may_authenticate") is False
        and status.get("may_grant_authority") is False
        and status.get("device") == "cpu"
        and isinstance(backend, str)
        and 0 < len(backend) <= 128
        and profiles is not None
        and max_audio is not None
        and max_audio > 0
    )
    if not valid:
        return ProbeResult(
            "unknown",
            "Speaker worker facts did not satisfy its bounded safety contract.",
            None,
            ("facts.speaker_worker",),
        )
    return ProbeResult(
        "healthy",
        "The CPU speaker-familiarity worker reported bounded non-authoritative status.",
        100,
        (
            "speaker_worker.purpose=familiarity-only",
            "speaker_worker.device=cpu",
            "speaker_worker.may_authenticate=false",
            "speaker_worker.may_grant_authority=false",
            f"speaker_worker.enrolled_profiles={profiles}",
        ),
    )


def _probe_face_worker(facts: Mapping[str, Any]) -> ProbeResult:
    status = _mapping(facts.get("face_worker"))
    if not status:
        return _unknown_research_stage("face_worker")
    worker_state = _bounded_identifier(
        status.get("status"), frozenset({"ready", "unavailable"})
    )
    max_bytes = _bounded_limit(status.get("max_image_bytes"))
    max_pixels = _bounded_limit(status.get("max_image_pixels"))
    valid = (
        worker_state is not None
        and status.get("purpose") == "familiarity-only"
        and status.get("device") == "cpu"
        and status.get("may_authenticate") is False
        and status.get("may_authorize_creator") is False
        and status.get("may_grant_authority") is False
        and status.get("image_retained") is False
        and max_bytes is not None
        and max_pixels is not None
    )
    if not valid:
        return ProbeResult(
            "unknown",
            "Face worker facts did not satisfy its bounded safety contract.",
            None,
            ("facts.face_worker",),
        )
    ready = worker_state == "ready"
    return ProbeResult(
        "healthy" if ready else "unfinished",
        (
            "The CPU face-familiarity worker reported ready without authentication "
            "authority or image retention."
            if ready
            else "The bounded face-familiarity backend reported unavailable."
        ),
        100 if ready else 35,
        (
            f"face_worker.status={worker_state}",
            "face_worker.purpose=familiarity-only",
            "face_worker.device=cpu",
            "face_worker.may_authenticate=false",
            "face_worker.may_authorize_creator=false",
            "face_worker.image_retained=false",
        ),
    )


def _probe_event_vision(facts: Mapping[str, Any]) -> ProbeResult:
    status = _mapping(facts.get("vision_dispatch"))
    if not status:
        return _unknown_research_stage("vision_dispatch")
    if status.get("available") is False:
        return ProbeResult(
            "unfinished", "Event-driven vision was not reported available.", 25,
            ("vision_dispatch.available=false",),
        )
    maximum = _bounded_count(status.get("max_queued"), positive=True)
    queued = _bounded_count(status.get("queued_count"))
    retained = _bounded_count(status.get("retained_frame_count"))
    valid = (
        status.get("available") is True
        and status.get("serialized") is True
        and status.get("raw_frame_persisted") is False
        and maximum is not None
        and queued is not None
        and retained is not None
        and queued <= maximum
        and retained <= maximum
    )
    if not valid:
        return ProbeResult(
            "unknown",
            "Vision facts did not satisfy serialized queue and persistence bounds.",
            None,
            ("facts.vision_dispatch",),
        )
    return ProbeResult(
        "healthy",
        "Event-driven vision reported one serialized bounded lane with no raw-frame "
        "persistence.",
        100,
        (
            "vision_dispatch.available=true",
            "vision_dispatch.serialized=true",
            "vision_dispatch.raw_frame_persisted=false",
            f"vision_dispatch.queued={queued}",
            f"vision_dispatch.max_queued={maximum}",
            f"vision_dispatch.retained_frames={retained}",
        ),
    )


PROBES: dict[str, Callable[[Mapping[str, Any]], ProbeResult]] = {
    "server": _probe_server,
    "model": _probe_model,
    "memory": _probe_memory,
    "soul": _probe_soul,
    "voice": _probe_voice,
    "senses": _probe_senses,
    "discord": _probe_discord,
    "mindpage": _probe_mindpage,
    "mindscape": _probe_mindscape,
    "embodiment": _probe_embodiment,
    "rsi": _probe_rsi,
    "stage": _probe_stage,
    "stage.complete": _probe_stage_complete,
    "stage.partial": _probe_stage_partial,
    "stage.not_started": _probe_stage_not_started,
    "stage.blocked": _probe_stage_blocked,
    "pagefile": _probe_pagefile,
    "research.temporal_memory_shadow": _probe_temporal_memory_shadow,
    "research.selective_soul_runtime": _probe_selective_soul_runtime,
    "research.video_companion": _probe_video_companion,
    "research.asr_dispatch": _probe_asr_dispatch,
    "research.speaker_worker": _probe_speaker_worker,
    "research.face_worker": _probe_face_worker,
    "research.event_vision": _probe_event_vision,
}


def _validate_plugin(raw: object, source: Path) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"{source}: unsupported brain plugin schema")
    plugin_id = raw.get("id")
    nodes = raw.get("nodes")
    if not isinstance(plugin_id, str) or not plugin_id or not isinstance(nodes, list):
        raise ValueError(f"{source}: plugin id and nodes are required")
    seen: set[str] = set()
    clean_nodes: list[dict[str, Any]] = []
    for item in nodes:
        if not isinstance(item, dict):
            raise ValueError(f"{source}: node must be an object")
        node_id, label, probe = item.get("id"), item.get("label"), item.get("probe")
        if not isinstance(node_id, str) or not node_id or node_id in seen:
            raise ValueError(f"{source}: node ids must be unique non-empty strings")
        if not isinstance(label, str) or not label or probe not in PROBES:
            raise ValueError(f"{source}: node {node_id!r} has an invalid label or probe")
        seen.add(node_id)
        clean_nodes.append({
            "id": node_id,
            "label": label,
            "parent": item.get("parent") if isinstance(item.get("parent"), str) else None,
            "probe": probe,
            "system": item.get("system") if isinstance(item.get("system"), str) else "overview",
            "detail": item.get("detail") if isinstance(item.get("detail"), str) else "",
            "group": item.get("group") if isinstance(item.get("group"), str) else "Structure",
        })
    return {"id": plugin_id, "name": str(raw.get("name") or plugin_id), "source": str(source), "nodes": clean_nodes}


def discover_plugins(extra_dir: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    directories = [BUILTIN_PLUGIN_DIR, extra_dir or LOCAL_PLUGIN_DIR]
    plugins: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen_plugins: set[str] = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                plugin = _validate_plugin(json.loads(path.read_text(encoding="utf-8")), path)
                if plugin["id"] in seen_plugins:
                    raise ValueError(f"duplicate plugin id {plugin['id']!r}")
                seen_plugins.add(plugin["id"])
                plugins.append(plugin)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append({"source": str(path), "error": str(exc)})
    return plugins, errors


def build_snapshot(facts: Mapping[str, Any], *, extra_dir: Path | None = None) -> dict[str, Any]:
    plugins, errors = discover_plugins(extra_dir)
    nodes: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    for plugin in plugins:
        for definition in plugin["nodes"]:
            qualified = f"{plugin['id']}:{definition['id']}"
            if qualified in seen_nodes:
                errors.append({"source": plugin["source"], "error": f"duplicate qualified node {qualified}"})
                continue
            seen_nodes.add(qualified)
            result = PROBES[definition["probe"]](facts).as_dict()
            nodes.append({
                **definition,
                **result,
                "id": qualified,
                "parent": f"{plugin['id']}:{definition['parent']}" if definition["parent"] else None,
                "plugin": plugin["id"],
            })
    counts = {state: sum(node["state"] == state for node in nodes) for state in sorted(VALID_STATES)}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "accuracy": "live-probe-or-explicit-unknown",
        "plugins": [{"id": item["id"], "name": item["name"], "nodeCount": len(item["nodes"])} for item in plugins],
        "pluginErrors": errors,
        "nodes": nodes,
        "counts": counts,
    }


__all__ = ["LOCAL_PLUGIN_DIR", "ProbeResult", "build_snapshot", "discover_plugins"]
