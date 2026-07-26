"""FastMCP server exposing the Alpecca Jason_HOLYROG compute worker as tools.

This wraps ``alpecca.rog_worker_client.RogWorkerClient`` so an MCP client can
drive the authenticated, compute-only worker (health, reasoning, vision,
Blender render, and the advisory HyFusER shadow score) without ever handling
the HMAC secret itself. The secret, URL, TLS CA, and timeouts are all read from
the environment by the underlying client — this server never accepts, logs, or
returns credentials.

Transport: stdio (a local server). Run it on the primary (RygenART) machine,
where the worker secret and tailnet route to Jason_HOLYROG already live.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Make the repo's ``alpecca`` package importable when this server is launched
# from somewhere other than the repo root. The file lives at
# <repo>/mcp/rog_worker/alpecca_rog_mcp/server.py, so the repo root is three
# parents up. An explicit ALPECCA_REPO_ROOT wins if set.
# ---------------------------------------------------------------------------
_repo_root = os.environ.get("ALPECCA_REPO_ROOT")
if _repo_root:
    sys.path.insert(0, _repo_root)
else:
    _candidate = Path(__file__).resolve().parents[3]
    if (_candidate / "alpecca" / "rog_worker_client.py").is_file():
        sys.path.insert(0, str(_candidate))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

mcp = FastMCP(
    "alpecca-rog-worker",
    instructions=(
        "Tools for Alpecca's compute-only Jason_HOLYROG worker. Call "
        "rog_health first to see which capabilities are ready (reasoning, "
        "vision, blender) before invoking them. The worker never speaks, "
        "remembers, or holds Alpecca's identity — it only answers bounded "
        "authenticated jobs. Credentials are handled by the server from the "
        "environment; never pass secrets as arguments."
    ),
)

# Max bytes to read from an image path before handing to the client (the client
# then resizes/re-encodes to <=1600px long edge and <=2 MiB before transfer).
_MAX_IMAGE_READ_BYTES = 32 * 1024 * 1024

_client = None  # lazily constructed singleton


def _get_client():
    """Build (once) and return the RogWorkerClient from the environment."""
    global _client
    if _client is None:
        from alpecca.rog_worker_client import RogWorkerClient

        try:
            _client = RogWorkerClient.from_environment()
        except Exception as exc:  # configuration/credential problems
            raise RuntimeError(
                "Could not build the ROG worker client from the environment. "
                "Set ALPECCA_ROG_WORKER_URL and provide the HMAC secret via "
                "ALPECCA_ROG_WORKER_SECRET or the Windows credential store, and "
                "(for LAN/tailnet) ALPECCA_ROG_WORKER_CA_CERT. "
                f"Underlying error: {type(exc).__name__}: {exc}"
            ) from exc
    return _client


_voice = None  # lazily constructed HOLYROG voice client singleton


def _get_voice():
    """Return the HOLYROG XTTS voice client (separate 8790 service)."""
    global _voice
    if _voice is None:
        from alpecca import holyrog_voice

        _voice = holyrog_voice.client()
    return _voice


def _guard(operation: str, fn, *args, **kwargs):
    """Run a client call, translating client errors into actionable messages."""
    from alpecca.rog_worker_client import (
        RogWorkerAuthenticationError,
        RogWorkerConfigurationError,
        RogWorkerProtocolError,
        RogWorkerRemoteJobError,
        RogWorkerResponseTooLargeError,
        RogWorkerTransportError,
        RogWorkerUnavailableError,
    )

    try:
        return fn(*args, **kwargs)
    except RogWorkerConfigurationError as exc:
        raise RuntimeError(
            f"{operation}: invalid request or client config — {exc}"
        ) from exc
    except RogWorkerAuthenticationError as exc:
        raise RuntimeError(
            f"{operation}: authentication failed (HTTP 401/403). Check the HMAC "
            "secret, the worker URL, and that the TLS CA cert matches. The "
            "secret must be identical on both machines."
        ) from exc
    except RogWorkerUnavailableError as exc:
        raise RuntimeError(
            f"{operation}: the worker is unreachable or not ready (timeout / "
            "429 / 5xx). Confirm the 'Alpecca ROG Compute Server' task is "
            "running on Jason_HOLYROG, Ollama has the model, and inbound TCP "
            "8788 is open on the HOLYROG firewall / reachable over the tailnet."
        ) from exc
    except RogWorkerTransportError as exc:
        raise RuntimeError(
            f"{operation}: could not reach the worker. Check that HOLYROG is "
            "online, the tailnet is up, and the URL/host resolves."
        ) from exc
    except RogWorkerResponseTooLargeError as exc:
        raise RuntimeError(
            f"{operation}: the worker response exceeded the size limit — {exc}"
        ) from exc
    except RogWorkerRemoteJobError as exc:
        raise RuntimeError(
            f"{operation}: the remote job failed — {getattr(exc, 'code', exc)}."
        ) from exc
    except RogWorkerProtocolError as exc:
        raise RuntimeError(
            f"{operation}: unexpected worker response — {exc}."
        ) from exc


# ---------------------------------------------------------------------------
# Output models (structured content)
# ---------------------------------------------------------------------------
class HealthOut(BaseModel):
    ok: bool = Field(description="True when the worker answered a valid health check.")
    hostname: str
    role: str = Field(description="Always 'compute-only' for a valid worker.")
    ready: bool = Field(description="reasoning_ready OR blender_ready.")
    reasoning_ready: bool
    blender_ready: bool
    vision_ready: bool
    vision_model: Optional[str] = Field(
        default=None, description="Opt-in vision model tag, or null when unset."
    )
    speaking: bool
    discord: bool
    request_id: str


class HyfuserHealthOut(BaseModel):
    ready: bool
    state: str
    architecture: str
    perspectives: list[str]
    advisory: bool
    shadow_only: bool
    request_id: str


class ReasonOut(BaseModel):
    model: str
    text: str = Field(description="The bounded visible answer. Never chain-of-thought.")
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    elapsed_ms: int
    request_id: str


class VisionOut(BaseModel):
    model: str
    description: str = Field(description="A grounded factual description of the image.")
    elapsed_ms: int
    request_id: str


class BlenderOut(BaseModel):
    job_id: str
    frame: int
    status: str
    artifact_name: str
    artifact_sha256: str
    artifact_bytes: int
    elapsed_ms: int
    request_id: str


class HyfuserHeadOut(BaseModel):
    name: str
    score: float
    confidence: float


class HyfuserScoreOut(BaseModel):
    architecture: str
    heads: list[HyfuserHeadOut]
    runtime_id: str
    weights_sha256: str
    elapsed_ms: int
    advisory: bool
    shadow_only: bool
    request_id: str


class VoiceStatusOut(BaseModel):
    engine: str
    configured: bool = Field(description="True when the voice URL and secret are set.")
    available: bool = Field(description="True when a live /health probe succeeded.")
    state: str
    cooldown_active: bool = Field(description="True when a recent failure is suppressing re-probes.")


class VoiceSynthOut(BaseModel):
    output_path: str = Field(description="Path to the written WAV file.")
    bytes: int
    mime: str
    engine: str


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool(
    annotations=ToolAnnotations(
        title="ROG worker health",
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def rog_health() -> HealthOut:
    """Report the compute worker's readiness.

    Returns which capabilities are live (reasoning, vision, blender), the opt-in
    vision model tag if configured, and confirms the worker's compute-only,
    non-speaking role. Call this before rog_reason / rog_describe_vision /
    rog_render_blender to avoid dispatching a job to a capability that is down.
    """
    h = _guard("rog_health", _get_client().health)
    return HealthOut(
        ok=True,
        hostname=h.hostname,
        role=h.role,
        ready=h.ready,
        reasoning_ready=h.reasoning_ready,
        blender_ready=h.blender_ready,
        vision_ready=h.vision_ready,
        vision_model=h.vision_model,
        speaking=h.speaking,
        discord=h.discord,
        request_id=h.request_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="HyFusER shadow-model health",
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def rog_hyfuser_health() -> HyfuserHealthOut:
    """Report readiness of the optional seven-head HyFusER shadow model.

    Advisory and shadow-only: it never speaks or mutates state. `ready` is true
    only when a trained, hash-pinned checkpoint is actually loaded.
    """
    h = _guard("rog_hyfuser_health", _get_client().hyfuser_health)
    return HyfuserHealthOut(
        ready=h.ready,
        state=h.state,
        architecture=h.architecture,
        perspectives=list(h.perspectives),
        advisory=h.advisory,
        shadow_only=h.shadow_only,
        request_id=h.request_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Reason on the worker",
        readOnlyHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def rog_reason(
    user_prompt: str = Field(description="The user turn to reason about. Required, non-empty."),
    system_prompt: str = Field(default="", description="Optional grounding/system prompt."),
    history: Optional[list[dict]] = Field(
        default=None,
        description="Optional prior turns, each {'role':'user'|'assistant','content':str}.",
    ),
    model: Optional[str] = Field(
        default=None,
        description="Model tag; defaults to the client's configured reasoning model (e.g. qwen3.5:9b). Must be on the worker allowlist.",
    ),
    max_tokens: int = Field(default=512, ge=1, le=2048, description="Max output tokens (1-2048)."),
) -> ReasonOut:
    """Run one bounded reasoning call on the worker's local Ollama model.

    Returns only the visible answer; chain-of-thought is never returned. The
    worker enforces its own model allowlist and output caps.
    """
    r = _guard(
        "rog_reason",
        _get_client().reason,
        system_prompt,
        user_prompt,
        history,
        model,
        max_tokens,
    )
    return ReasonOut(
        model=r.model,
        text=r.text,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
        elapsed_ms=r.elapsed_ms,
        request_id=r.request_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Describe an image on the worker",
        readOnlyHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def rog_describe_vision(
    image_path: str = Field(description="Absolute path to a PNG, JPEG, or WebP image file."),
    prompt: Optional[str] = Field(
        default=None, description="Optional custom prompt; defaults to the grounded describe prompt."
    ),
    model: Optional[str] = Field(
        default=None,
        description="Vision model tag; defaults to the client's configured vision model. Requires the worker to have vision enabled (see rog_health.vision_ready).",
    ),
    max_tokens: int = Field(default=512, ge=1, le=512, description="Max output tokens (1-512)."),
) -> VisionOut:
    """Describe an image via the authenticated private worker.

    The image is resized/re-encoded locally (long edge <=1600px, <=2 MiB) before
    transfer; raw bytes are not persisted. If the worker's vision path is off
    (vision_ready=false), this returns an actionable error — fall back to local
    vision on the primary instead.
    """
    path = Path(image_path)
    if not path.is_file():
        raise RuntimeError(f"rog_describe_vision: image not found at {image_path!r}.")
    size = path.stat().st_size
    if size <= 0 or size > _MAX_IMAGE_READ_BYTES:
        raise RuntimeError(
            f"rog_describe_vision: image is empty or too large ({size} bytes; "
            f"max {_MAX_IMAGE_READ_BYTES})."
        )
    data = path.read_bytes()
    kwargs = {"max_tokens": max_tokens}
    if prompt is not None:
        kwargs["prompt"] = prompt
    if model is not None:
        kwargs["model"] = model
    v = _guard("rog_describe_vision", lambda: _get_client().describe_vision(data, **kwargs))
    return VisionOut(
        model=v.model,
        description=v.description,
        elapsed_ms=v.elapsed_ms,
        request_id=v.request_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Render a Blender frame on the worker",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
def rog_render_blender(
    project: str = Field(description="A .blend filename inside the worker's approved blend root (name only, no path)."),
    frame: int = Field(default=1, ge=1, le=999999, description="Frame number to render (1-999999)."),
) -> BlenderOut:
    """Render one frame of an approved .blend project on the worker.

    Produces a PNG artifact on the worker and returns its name, sha256, and size.
    Requires the worker's Blender capability to be configured (see
    rog_health.blender_ready).
    """
    b = _guard("rog_render_blender", _get_client().render_blender, project, frame)
    return BlenderOut(
        job_id=b.job_id,
        frame=b.frame,
        status=b.status,
        artifact_name=b.artifact_name,
        artifact_sha256=b.artifact_sha256,
        artifact_bytes=b.artifact_bytes,
        elapsed_ms=b.elapsed_ms,
        request_id=b.request_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="HyFusER advisory score (shadow)",
        readOnlyHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def rog_score_soul(
    text_emotion: list[float] = Field(
        description="Probability vector over the emotion order (sums to 1, each in [0,1])."
    ),
    speech_emotion: list[float] = Field(
        description="Probability vector over the emotion order (sums to 1, each in [0,1])."
    ),
) -> HyfuserScoreOut:
    """Request the seven advisory HyFusER perspective scores (shadow-only).

    Advisory and non-authoritative: these scores never drive an action or mutate
    state, and are only meaningful when rog_hyfuser_health reports ready with a
    trained, hash-pinned, calibrated checkpoint.
    """
    s = _guard("rog_score_soul", _get_client().score_soul, text_emotion, speech_emotion)
    return HyfuserScoreOut(
        architecture=s.architecture,
        heads=[HyfuserHeadOut(name=h.name, score=h.score, confidence=h.confidence) for h in s.heads],
        runtime_id=s.runtime_id,
        weights_sha256=s.weights_sha256,
        elapsed_ms=s.elapsed_ms,
        advisory=s.advisory,
        shadow_only=s.shadow_only,
        request_id=s.request_id,
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="HOLYROG voice server status",
        readOnlyHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def rog_voice_status() -> VoiceStatusOut:
    """Report the HOLYROG XTTS voice server status (a separate 8790 service).

    Runs a live /health probe (with the client's failure cooldown). `configured`
    is false when ALPECCA_HOLYROG_VOICE_URL / ALPECCA_HOLYROG_VOICE_SECRET are
    unset; `available` is true only when the server actually answered.
    """
    vc = _get_voice()
    try:
        available = bool(vc.available())
    except Exception:
        available = False
    st = vc.status()
    return VoiceStatusOut(
        engine=str(st.get("engine", "holyrog-xtts")),
        configured=bool(st.get("configured")),
        available=available,
        state=str(st.get("state", "")),
        cooldown_active=bool(st.get("cooldown_active")),
    )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Synthesize speech on HOLYROG",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
def rog_synthesize_voice(
    text: str = Field(description="Text to synthesize (the server trims to ~600 chars)."),
    output_path: Optional[str] = Field(
        default=None,
        description="Where to write the WAV. Defaults to a temp .wav file. Parent dir must exist.",
    ),
) -> VoiceSynthOut:
    """Synthesize speech via the HOLYROG XTTS voice server and write a WAV file.

    This targets the separate voice offload service
    (scripts/run_holyrog_voice_server.py, port 8790) — not the ROG compute
    worker. Returns the output WAV path. If voice is unconfigured or the server
    is unreachable, it raises an actionable error (the primary otherwise falls
    back to local Kokoro).
    """
    if not (text or "").strip():
        raise RuntimeError("rog_synthesize_voice: text must not be empty.")
    vc = _get_voice()
    if not vc.enabled:
        raise RuntimeError(
            "rog_synthesize_voice: voice is not configured — set "
            "ALPECCA_HOLYROG_VOICE_URL and ALPECCA_HOLYROG_VOICE_SECRET."
        )
    result = vc.synthesize(text)
    if result is None:
        st = vc.status()
        raise RuntimeError(
            "rog_synthesize_voice: synthesis failed or the voice server is "
            f"unavailable (state={st.get('state')!r}). Ensure the HOLYROG XTTS "
            "server (scripts/run_holyrog_voice_server.py, port 8790) is running "
            "and inbound TCP 8790 is open on the firewall / reachable over the "
            "tailnet. The primary falls back to local Kokoro."
        )
    mime, data = result
    if output_path is None:
        import tempfile

        fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="alpecca-voice-")
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    else:
        target = Path(output_path)
        if target.parent and not target.parent.is_dir():
            raise RuntimeError(
                f"rog_synthesize_voice: output directory does not exist: {target.parent}"
            )
        target.write_bytes(data)
        output_path = str(target)
    return VoiceSynthOut(
        output_path=output_path, bytes=len(data), mime=mime, engine="holyrog-xtts"
    )


def main() -> None:
    """Run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
