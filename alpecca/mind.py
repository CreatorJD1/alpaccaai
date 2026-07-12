"""The Core Mind: the loop that ties senses, mood, memory, and the LLM together.

The spec names LangGraph as the orchestrator. The shape it's reaching for is a
small state machine that, each turn, walks a fixed sequence of nodes:

    sense -> update mood -> recall memory -> generate -> persist

We implement that sequence directly and transparently here. Keeping it as plain,
readable Python (rather than hiding it inside a graph framework) makes the data
flow obvious and easy to test; if you later want LangGraph's tooling, each method
below maps cleanly onto a node.

The LLM call goes through Ollama. If Ollama isn't running, we don't crash -- we
fall back to a small templated voice so the whole loop is still exercisable
(useful for tests and for seeing the plumbing work before you pull a model).
"""
from __future__ import annotations

import random
import json
import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from numbers import Number
from typing import Literal

from config import (
    OLLAMA_MODEL,
    OLLAMA_FAST_MODEL,
    OLLAMA_HOST,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_GPU,
    OLLAMA_NUM_PREDICT,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_TIMEOUT_SECONDS,
    HISTORY_MESSAGES,
    CHAT_CLOUD_MODEL,
    CLOUD_NUM_CTX,
    STREAM_CHAT,
    CHAT_ZEROGPU,
    CHAT_ZEROGPU_TIMEOUT,
    REFLECT_THINK,
    REFLECT_MODEL,
    REFLECT_NUM_PREDICT,
    REFLECT_TIMEOUT_SECONDS,
    Emotion,
)
from config import (
    LLM_BACKEND,
    HF_TOKEN,
    HF_MODEL,
    HF_PROVIDER,
    CLOUD_SEND_SENSES,
    CORE_MEMORY_LEARN_ONLY,
    RECAP_SALIENCE,
    CHAT_SEMANTIC_RECALL,
    MINDPAGE,
)
from config import (DEEP_BACKEND, ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
                    CLOUD_URL, CLOUD_MODEL, CLOUD_API_KEY,
                    COLAB_URL, COLAB_MODEL, COLAB_API_KEY,
                    COLAB_TIMEOUT_SECONDS, COLAB_FAST_CHAT,
                    ZEROGPU_SPACE, ZEROGPU_API, ZEROGPU_TOKEN,
                    OLLAMA_CLOUD_MODEL, CLOUD_REFLECT_NUM_PREDICT)
from config import LIVING_LLM, SOUL_LLM, PROACTIVE_LLM
from alpecca.homeostasis import EmotionalState
from alpecca import state as state_store
from alpecca import memory as memory_store
from alpecca import mindpage as mindpage_mod
from alpecca.sensory import Observation, prediction_error
from alpecca import prompts
from alpecca import introspection
from alpecca import appearance as appearance_mod
from alpecca.portrait import PortraitWorker
from alpecca import portrait as portrait_mod
from alpecca.actions import Actuator
from alpecca.toolkit import InnateToolkit
from alpecca import proactive as proactive_mod
from alpecca import studio
from alpecca import puppet
from alpecca import home as home_mod
from alpecca import desires as desires_mod
from alpecca import selfmod
from alpecca import soul as soul_mod
from alpecca import journal as journal_mod
from alpecca import learning as learning_mod
from alpecca import cognition as cognition_mod
from alpecca import people as people_mod
from alpecca import core_memory as core_mem
from alpecca import speech as speech_mod
from alpecca import colab_t4
from alpecca import choice as choice_mod
from alpecca import planner as planner_mod
from alpecca import turn_context as turn_context_mod
from alpecca import cues as cues_mod
from alpecca import commitments as commitments_mod
from alpecca import commitment_language as commitment_language_mod
from alpecca import action_closure as action_closure_mod
from alpecca import affect_evidence as affect_evidence_mod
from alpecca import initiative as initiative_mod
from alpecca import memory_pressure as memory_pressure_mod
from alpecca import soul_pressure_signal as soul_pressure_signal_mod
from alpecca.local_inference import verified_local_ollama_target
from config import Proactive as ProactiveCfg, Reflection as ReflectionCfg, Actions as ActionsCfg


# Qwen3 hybrid models reason out loud inside <think>...</think> before the real
# reply. That deliberation is internal monologue, not something Alpecca should
# say to the person -- so we strip it. Also handles a truncated, never-closed
# think block (we drop to end-of-string rather than leak half a chain of
# thought). If stripping leaves nothing we return the original text untouched,
# which can only happen on degenerate output anyway.
_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)

_PHASE5_AFFECT_POSTURES = {
    "correction": "prioritize the correction and avoid superseded context",
    "confirmation": "acknowledge the confirmed direction without inferring execution",
    "reference": "resolve the referenced context before relying on it",
    "urgency": "use a concise, time-aware response strategy",
    "distress": "use a calm, support-focused response strategy",
    "question": "prioritize a direct answer grounded in available evidence",
    "action_intent": "separate the requested action from approval and execution state",
}


@dataclass(frozen=True, slots=True)
class ProactiveCandidate:
    """One eligible proactive utterance with its selection provenance."""

    origin: Literal["chatter", "mood_speech"]
    reason: str


def strip_think(text: str) -> str:
    cleaned = _THINK_RE.sub("", text).strip()
    return cleaned or text.strip()


class _StreamPartial(RuntimeError):
    """A streamed generation died AFTER tokens were already shown to the
    person. The caller must not silently retry (the draft can't be unsaid);
    it propagates so the honest fallback reply replaces the draft."""


class _LLM:
    """Thin wrapper over the Ollama client with a graceful offline fallback."""

    def __init__(self) -> None:
        self._backend = LLM_BACKEND          # "ollama" (local) or "hf" (cloud)
        self._client = None                  # ollama client
        self._hf = None                      # huggingface InferenceClient
        if self._backend == "hf":
            try:
                from huggingface_hub import InferenceClient
                # token=None falls back to a cached `huggingface-cli login`.
                self._hf = InferenceClient(provider=HF_PROVIDER or "auto",
                                           token=HF_TOKEN or None)
            except Exception as exc:
                import sys
                print(f"[mind] HF cloud brain unavailable: {type(exc).__name__}: {exc}\n"
                      f"        fix:  python -m pip install huggingface_hub  and  "
                      f"huggingface-cli login  (or set HF_TOKEN).", file=sys.stderr)
                self._hf = None
        else:
            try:
                import ollama
                self._client = ollama.Client(
                    host=OLLAMA_HOST,
                    timeout=max(3.0, float(OLLAMA_TIMEOUT_SECONDS)),
                )
            except Exception:
                self._client = None
        self._last_call: dict = {
            "requested_tier": "",
            "used_tier": "none",
            "backend": "offline",
            "model": "",
            "ok": False,
            "fallback": False,
            "error": "",
        }
        # Her optional "deep" tier -- a stronger model for her hardest self-acts
        # only (reflection, self-questioning). Strict augmentation: built only when
        # explicitly configured, so by default her brain is 100% local and this is
        # None. `_deep` is (kind, client) or None.
        self._deep = self._build_deep()

    def _mark_model_use(self, *, requested: str, used: str, backend: str,
                        model: str = "", ok: bool = True,
                        fallback: bool = False, error: str = "") -> None:
        self._last_call = {
            "requested_tier": requested or "",
            "used_tier": used or "",
            "backend": backend or "",
            "model": model or "",
            "ok": bool(ok),
            "fallback": bool(fallback),
            "error": str(error or "")[:220],
            "deep_backend": DEEP_BACKEND,
        }

    def last_call(self) -> dict:
        return dict(self._last_call)

    # --- Local chain-of-thought for her deep self-acts ----------------------

    #: Her most recent private reasoning chain (reflection-tier thinking).
    #: Kept for observability -- introspection/status can show that a musing
    #: came from real deliberation -- never injected back into prompts.
    last_thinking: str = ""

    #: Which model actually served the last _chat call (hybrid chat means the
    #: cloud may answer even when the local model was requested) -- so status
    #: reporting stays truthful.
    last_chat_model: str = ""

    def _cloud_chat_client(self):
        """Client for hybrid cloud chat with a TIGHT timeout: cloud replies
        land in ~3s, so anything past 20s means the link is wedged and the
        local model should take over rather than keep the person waiting."""
        if getattr(self, "_cloud_client", None) is None:
            import ollama
            self._cloud_client = ollama.Client(host=OLLAMA_HOST, timeout=20.0)
        return self._cloud_client

    def _thinking_client(self):
        """A second Ollama client with a reflection-scale timeout. The normal
        client is capped at OLLAMA_TIMEOUT_SECONDS (~18s) so a wedged call
        can't hang a chat turn; a genuine think-first reflection at a few
        tok/s needs minutes, and nobody is waiting on it."""
        if getattr(self, "_slow_client", None) is None:
            import ollama
            self._slow_client = ollama.Client(
                host=OLLAMA_HOST,
                timeout=max(60.0, float(REFLECT_TIMEOUT_SECONDS)),
            )
        return self._slow_client

    def _generate_local_thinking(self, system_prompt: str, user_msg: str,
                                 history: list[dict] | None,
                                 model: str | None = None,
                                 num_predict: int | None = None) -> str:
        """One deep self-act with real chain-of-thought through the Ollama API.

        Ollama's think mode has the model deliberate privately (returned in the
        separate `thinking` field) before it answers, so her reflections come
        from actual reasoning instead of one fast pass. Default is her local
        model (no cloud, no quota); the deep tier passes an Ollama *cloud*
        model here instead -- same client, same shape, datacenter speed.
        Raises on any failure so the caller can fall through to the plain
        no-think local path; returns "" if the model thought but never got to
        an answer (budget exhausted), which callers treat the same way."""
        model = model or REFLECT_MODEL or OLLAMA_MODEL
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_msg})
        resp = self._thinking_client().chat(
            model=model,
            messages=messages,
            think=True,
            options={
                "num_ctx": OLLAMA_NUM_CTX,
                # Thinking eats most of the budget; the reply is short. Sized so
                # a long chain still leaves room for the actual musing.
                "num_predict": int(num_predict or REFLECT_NUM_PREDICT),
                "repeat_penalty": 1.15,
                "repeat_last_n": 256,
            },
            keep_alive=OLLAMA_KEEP_ALIVE,
        )
        msg = resp["message"]
        self.last_thinking = str(msg.get("thinking") or "")
        text = strip_think(str(msg.get("content") or "")).strip()
        if not text and self.last_thinking:
            # She spent the whole budget deliberating and never surfaced. Hand
            # her own chain back and ask for just the conclusion -- short,
            # no-think, so the musing still comes from the real deliberation.
            followup = list(messages)
            followup.append({"role": "assistant",
                             "content": "(my private notes so far)\n"
                                        + self.last_thinking[-2000:]})
            followup.append({"role": "user",
                             "content": "Stop analyzing. Say just your "
                                        "conclusion now -- the two or three "
                                        "first-person sentences themselves."})
            resp = self._thinking_client().chat(
                model=model,
                messages=followup,
                think=False,
                options={
                    "num_ctx": OLLAMA_NUM_CTX,
                    "num_predict": max(160, OLLAMA_NUM_PREDICT),
                    "repeat_penalty": 1.15,
                    "repeat_last_n": 256,
                },
                keep_alive=OLLAMA_KEEP_ALIVE,
            )
            text = strip_think(str(resp["message"].get("content") or "")).strip()
        return text

    def _build_deep(self):
        """Construct the deep-tier chain from config: DEEP_BACKEND may be one
        backend or a comma-separated chain ("ollama-cloud,zerogpu") tried in
        order. Returns the first constructible tier (kept as self._deep for
        status/back-compat) or None; the full ordered list lands on
        self._deep_chain. Never raises: a missing key/package/endpoint just
        drops that link so her inner life still runs, just plainer."""
        self._deep_chain: list = []
        for kind in [k.strip() for k in DEEP_BACKEND.split(",") if k.strip()]:
            try:
                if kind == "anthropic" and ANTHROPIC_API_KEY:
                    import anthropic
                    self._deep_chain.append(
                        ("anthropic", anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)))
                elif kind == "cloud" and CLOUD_URL:
                    # An OpenAI-compatible server you host (vLLM/Ollama on a
                    # notebook GPU). HF's InferenceClient speaks that protocol.
                    from huggingface_hub import InferenceClient
                    self._deep_chain.append(
                        ("cloud", InferenceClient(base_url=CLOUD_URL,
                                                  api_key=CLOUD_API_KEY or "-")))
                elif kind == "zerogpu" and ZEROGPU_SPACE:
                    # Do not construct the Gradio client at startup: a building
                    # or sleeping Space can block for a long time. Connect
                    # lazily only when a deep call actually reaches this link.
                    self._deep_chain.append(("zerogpu", ZEROGPU_SPACE))
                elif kind == "ollama-cloud" and OLLAMA_CLOUD_MODEL:
                    # Ollama's hosted models via the already-running local
                    # Ollama (signed in). Same client/protocol as her local
                    # brain; the model name alone routes to the cloud.
                    self._deep_chain.append(("ollama-cloud", OLLAMA_CLOUD_MODEL))
            except Exception as exc:
                import sys
                print(f"[mind] deep tier link '{kind}' unavailable. "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return self._deep_chain[0] if self._deep_chain else None

    @property
    def online(self) -> bool:
        return self._hf is not None if self._backend == "hf" else self._client is not None

    def deep_online(self) -> bool:
        """Whether her deep tier is actually wired -- for /state reporting."""
        return self._deep is not None

    def is_cloud(self) -> bool:
        """Whether the primary backend is HF.

        Hybrid hosted routes are evaluated per call; private paths must use
        :meth:`local_inference_available` or ``generate(local_only=True)``.
        """
        return self._backend == "hf"

    def _verified_local_target(self, model: str) -> bool:
        return (
            self._backend != "hf"
            and self._client is not None
            and verified_local_ollama_target(
                OLLAMA_HOST,
                model,
                known_cloud_models={CHAT_CLOUD_MODEL, OLLAMA_CLOUD_MODEL},
            )
        )

    def local_inference_available(self, model: str | None = None) -> bool:
        """Whether private material can use the configured Ollama target."""
        return self._verified_local_target(model or OLLAMA_MODEL)

    def model_for(self, tier: str) -> str:
        """Which Ollama model serves a given tier. 'fast' routes cheap, low-stakes
        work to the small model when one is configured; everything else (and the
        default) uses the heavy reasoning model. With no fast model set, both
        tiers resolve to OLLAMA_MODEL, so routing is a no-op until you opt in."""
        if tier == "fast" and OLLAMA_FAST_MODEL:
            return OLLAMA_FAST_MODEL
        if tier == "deep" and self._deep and self._deep[0] == "ollama-cloud":
            return self._deep[1]
        if tier == "deep" and REFLECT_MODEL:
            return REFLECT_MODEL
        return OLLAMA_MODEL

    def _chat(self, messages: list[dict], tools: list[dict] | None = None,
              model: str | None = None, *, local_only: bool = False):
        """One Ollama chat call with thinking disabled.

        Qwen3 hybrids think out loud by default, which is great for math and
        terrible for companionship -- a reply that takes forty seconds isn't a
        conversation. We ask for no-think first and quietly retry plain for
        models/servers that reject the parameter; strip_think still catches
        any <think> blocks that slip through either way. `model` lets a caller
        pick the tier-appropriate model (heavy MoE vs. tiny fast)."""
        kwargs: dict = {"model": model or OLLAMA_MODEL, "messages": messages,
                        # Cap the KV cache so big advertised context windows
                        # (qwen3's 256K -> ~36 GB) don't OOM the model on
                        # startup and silently drop her to the echo fallback.
                        "options": {
                            "num_ctx": OLLAMA_NUM_CTX,
                            "num_predict": OLLAMA_NUM_PREDICT,
                            # Gently discourage looping the same lines. Kept mild:
                            # heavy presence/frequency penalties push a multilingual
                            # model off-distribution (drifting into other languages /
                            # confabulation). The real anti-repetition is the
                            # regenerate-if-too-similar guard in chat(), so this only
                            # needs to nudge.
                            "repeat_penalty": 1.15,
                            "repeat_last_n": 256,
                        },
                        "keep_alive": OLLAMA_KEEP_ALIVE}
        if tools:
            kwargs["tools"] = tools
        if local_only and not self._verified_local_target(kwargs["model"]):
            raise RuntimeError(
                "local-only inference rejected a remote endpoint or cloud model"
            )
        # Hybrid chat: reasoning-tier turns try the hosted cloud model first --
        # ~3s replies from a much bigger brain, with a context window the
        # laptop couldn't hold. ANY failure (offline, signed out, quota gone,
        # hung call) falls straight through to the local model below, so the
        # cloud is a speedup, never a dependency. Fast-tier and explicit-model
        # calls skip this: cheap chatter isn't worth metered usage.
        # Tool calls stay on the local Ollama protocol. Hosted chat routing is
        # plain-text only because tool schemas/round-trips are backend-specific
        # and must remain observable and bounded on the local path.
        if (CHAT_CLOUD_MODEL and not local_only and not tools
                and kwargs["model"] == OLLAMA_MODEL):
            try:
                ck = dict(kwargs)
                ck["model"] = CHAT_CLOUD_MODEL
                # gpt-oss reasons internally no matter what, and that reasoning
                # counts against num_predict -- with her big system prompt the
                # local 120-token budget gets eaten before the reply starts and
                # the content comes back EMPTY. Cloud tokens are fast, so give
                # hosted calls room to think AND answer.
                ck["options"] = dict(kwargs["options"], num_ctx=CLOUD_NUM_CTX,
                                     num_predict=max(512, OLLAMA_NUM_PREDICT))
                ck["options"].pop("num_gpu", None)   # meaningless for hosted
                client = self._cloud_chat_client()
                try:
                    resp = client.chat(**ck, think=False)
                except TypeError:
                    resp = client.chat(**ck)
                if not str(resp["message"].get("content") or "").strip():
                    # Budget exhausted mid-reasoning or a silent refusal --
                    # never hand the person an empty reply; let local answer.
                    raise RuntimeError("cloud chat returned empty content")
                self.last_chat_model = CHAT_CLOUD_MODEL
                return resp
            except Exception as exc:
                import sys
                print(f"[mind] cloud chat unavailable -> local. "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
        self.last_chat_model = kwargs["model"]
        # Force layer placement when configured -- Ollama under-offloads some
        # GGUFs (qwen3.5) and leaves the small GPU half-idle. See OLLAMA_NUM_GPU.
        if OLLAMA_NUM_GPU is not None:
            kwargs["options"]["num_gpu"] = OLLAMA_NUM_GPU

        def _one_call():
            try:
                return self._client.chat(**kwargs, think=False)
            except TypeError:
                return self._client.chat(**kwargs)   # client too old for think=

        import time as _t
        last = None
        for attempt in range(3):
            try:
                return _one_call()
            except Exception as exc:
                last = exc
                # On a small GPU, loading the big vision model evicts the chat
                # model and Ollama is briefly unreachable; settle and retry so an
                # image turn doesn't drop her to the echo fallback.
                if attempt < 2 and any(w in str(exc).lower() for w in (
                        "connect", "connection", "refused", "timed out",
                        "timeout", "eof")):
                    _t.sleep(1.5 * (attempt + 1))
                    continue
                raise
        raise last  # pragma: no cover

    def _chat_stream(self, messages: list[dict], model: str | None = None,
                     on_token=None) -> str:
        """One PLAIN chat call streamed token by token.

        Each visible delta (with <think> spans filtered incrementally) goes to
        `on_token(text)`; the full assembled reply is returned so every
        after-generation vet (repetition guard, echo repair, memory, affect)
        runs on it unchanged. Failure contract: if the stream dies BEFORE any
        token was shown we retry once then fall back to the plain call; after
        partial emission we raise _StreamPartial -- the caller lets the echo
        fallback become the authoritative reply that replaces the draft.
        No tools, no hybrid-cloud, no think mode here: this serves only the
        live chat turn's local path."""
        from alpecca.streaming import ThinkTagFilter
        kwargs: dict = {"model": model or OLLAMA_MODEL, "messages": messages,
                        "options": {
                            "num_ctx": OLLAMA_NUM_CTX,
                            "num_predict": OLLAMA_NUM_PREDICT,
                            "repeat_penalty": 1.15,
                            "repeat_last_n": 256,
                        },
                        "keep_alive": OLLAMA_KEEP_ALIVE}
        if OLLAMA_NUM_GPU is not None:
            kwargs["options"]["num_gpu"] = OLLAMA_NUM_GPU
        self.last_chat_model = kwargs["model"]

        def _open_stream():
            try:
                return self._client.chat(**kwargs, stream=True, think=False)
            except TypeError:
                # Older client without think= -- try streaming without it; a
                # TypeError HERE means stream= itself is unsupported and the
                # caller should use the plain path.
                return self._client.chat(**kwargs, stream=True)

        import time as _t
        for attempt in range(2):
            filt = ThinkTagFilter()
            parts: list[str] = []
            emitted = False
            try:
                for chunk in _open_stream():
                    delta = str(chunk["message"].get("content") or "")
                    visible = filt.feed(delta)
                    if visible:
                        parts.append(visible)
                        emitted = True
                        if on_token is not None:
                            on_token(visible)
                tail = filt.flush()
                if tail:
                    parts.append(tail)
                return "".join(parts).strip()
            except TypeError:
                # stream= unsupported by this client -- plain call instead.
                resp = self._chat(messages, model=model, local_only=True)
                return strip_think(resp["message"]["content"])
            except Exception as exc:
                if emitted:
                    raise _StreamPartial(str(exc)) from exc
                if attempt == 0:
                    _t.sleep(1.0)   # brief settle (same spirit as _chat's retry)
                    continue
                raise

    def generate(self, system_prompt: str, user_msg: str,
                 history: list[dict] | None = None,
                 tools: list[dict] | None = None,
                 on_tool=None, tier: str = "reason",
                 on_token=None, local_only: bool = False) -> str:
        """One reply. When `tools` are offered and the model calls one, we run
        it through `on_tool(name, args) -> str` and give the model one more
        pass to fold the result into its words. A model or client that can't
        do tools just degrades to a plain conversational reply.

        `tier` selects the model: 'reason' (default) for her real thinking --
        chat replies, reflection, self-critique -- and 'fast' for cheap work
        (unprompted remarks, chatter, posing a question), which a small model
        handles so the big one stays free. Tool use always goes through the
        reasoning model regardless of tier, since tool-calling reliability is
        what the heavy model is for.

        The 'deep' tier is her optional cloud augmentation for her hardest
        self-acts. It NEVER serves a normal chat turn (callers reserve it for
        reflection/self-questioning), her local brain still answers everything
        else, and if the deep client is absent or fails we fall straight through
        to local reasoning -- so her depth still happens, just plainer."""
        local_model = OLLAMA_MODEL if tools else self.model_for(tier)
        if tier == "deep":
            local_model = REFLECT_MODEL or OLLAMA_MODEL
        if local_only and not self._verified_local_target(local_model):
            error = (
                "private context requires a loopback Ollama endpoint and a "
                "non-cloud local model"
            )
            self._mark_model_use(
                requested=tier,
                used="fallback",
                backend="offline",
                model=local_model,
                ok=False,
                fallback=True,
                error=error,
            )
            return self._fallback(system_prompt, user_msg, error=error)
        if (not local_only and tier == "deep"
                and getattr(self, "_deep_chain", None)):
            # Walk the chain (e.g. ollama-cloud -> zerogpu): first link that
            # answers wins; every failure falls to the next, and the local
            # thinking pass below remains the final net.
            for link in self._deep_chain:
                try:
                    text = self._generate_deep(system_prompt, user_msg, history,
                                               tier=link)
                    self._mark_model_use(
                        requested=tier,
                        used="deep",
                        backend=link[0],
                        # ollama-cloud/zerogpu links carry their model/space
                        # name as a string -- report exactly what served.
                        model=(link[1] if isinstance(link[1], str)
                               else self.model_for("deep")),
                    )
                    return text
                except Exception as exc:
                    import sys
                    print(f"[mind] deep link '{link[0]}' failed -> next. "
                          f"{type(exc).__name__}: {exc}", file=sys.stderr)
            # chain exhausted -- fall through to local thinking below
        # Reflection-tier thinking: her deep self-acts, running locally, get a
        # real chain-of-thought pass (think=True) instead of one fast take --
        # so depth survives even with no cloud deep tier / no quota. Tools stay
        # on the plain path (tool-calling and think mode don't mix well), and
        # any failure or empty answer falls through to the ordinary local call.
        if (tier == "deep" and REFLECT_THINK and not tools
                and self._backend != "hf" and self._client is not None):
            try:
                text = self._generate_local_thinking(system_prompt, user_msg,
                                                     history)
                if text:
                    self._mark_model_use(
                        requested=tier,
                        used="reason-think",
                        backend="ollama",
                        model=REFLECT_MODEL or OLLAMA_MODEL,
                    )
                    return text
            except Exception as exc:
                import sys
                print(f"[mind] local thinking pass failed -> plain local. "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
        if (not local_only and tier == "fast" and COLAB_FAST_CHAT
                and COLAB_URL and not tools):
            try:
                text = colab_t4.chat(
                    system_prompt,
                    user_msg,
                    history=history,
                    url=COLAB_URL,
                    model=COLAB_MODEL,
                    api_key=COLAB_API_KEY,
                    timeout=COLAB_TIMEOUT_SECONDS,
                    max_tokens=min(max(48, int(OLLAMA_NUM_PREDICT)), 180),
                )
                self._mark_model_use(
                    requested=tier,
                    used="fast",
                    backend="colab-t4",
                    model=COLAB_MODEL,
                )
                return strip_think(text)
            except Exception as exc:
                import sys
                print(f"[mind] Colab fast tier unavailable -> local fast. "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
        # Cloud brain: her thinking runs on Hugging Face. HF Inference implements
        # the OpenAI tool-calling interface, so her actuator works here too.
        if self._backend == "hf":
            return self._generate_hf(system_prompt, user_msg, history, tools, on_tool)
        if self._client is None:
            self._mark_model_use(
                requested=tier,
                used="fallback",
                backend="offline",
                model=self.model_for(tier),
                ok=False,
                fallback=True,
                error="Ollama client is not configured",
            )
            return self._fallback(system_prompt, user_msg)
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_msg})
        model = self.model_for(tier)
        if tier == "deep":
            # Reaching here means the whole deep chain (and the thinking pass)
            # already failed -- the plain net must run on a LOCAL model, not
            # re-dial the cloud name model_for reports for status.
            model = REFLECT_MODEL or OLLAMA_MODEL
        try:
            if tools and on_tool:
                # Tool-calling stays on the reasoning model -- the small model is
                # for plain short generations, not reliable function calls.
                tool_model = OLLAMA_MODEL
                try:
                    resp = self._chat(
                        messages, tools=tools, model=tool_model,
                        local_only=local_only,
                    )
                except Exception:
                    # Older client/model without tool support -- plain chat.
                    resp = self._chat(
                        messages, model=tool_model, local_only=local_only
                    )
                msg = resp["message"]
                # Let her CHAIN tool calls across a bounded number of rounds, so a
                # small multi-step request ("open my notes, then the docs page")
                # is actually carried out -- not just its first step. Each tool is
                # still allowlist/https-gated; the final round drops tools so she
                # always ends with words, never a dangling call.
                rounds = max(1, ActionsCfg.MAX_TOOL_ROUNDS)
                for i in range(rounds):
                    calls = msg.get("tool_calls") or []
                    if not calls:
                        break
                    messages.append(msg)
                    for call in calls:
                        fn = call.get("function", {})
                        result = on_tool(fn.get("name", ""), fn.get("arguments") or {})
                        messages.append({"role": "tool", "content": str(result)})
                    last = (i == rounds - 1)
                    try:
                        resp = self._chat(
                            messages,
                            tools=(None if last else tools),
                            model=tool_model,
                            local_only=local_only,
                        )
                    except Exception:
                        resp = self._chat(
                            messages, model=tool_model, local_only=local_only
                        )
                    msg = resp["message"]
                self._mark_model_use(
                    requested=tier,
                    used="reason",
                    backend="ollama",
                    model=tool_model,
                )
                return strip_think(msg["content"])
            # Cloud-first chat on her own Space: the SAME Qwen3.5-9B, run on a
            # datacenter GPU (~3-8s a reply warm vs ~30s local). Bounded so a
            # sleeping Space can't stall the turn -- on timeout the local 9B
            # answers THIS turn while the abandoned attempt finishes waking
            # the Space, making the NEXT turns cloud-fast.
            if (not local_only and tier == "reason" and not tools and on_token is None
                    and CHAT_ZEROGPU and ZEROGPU_SPACE and self._backend != "hf"):
                import concurrent.futures
                if getattr(self, "_space_chat_pool", None) is None:
                    self._space_chat_pool = concurrent.futures.ThreadPoolExecutor(
                        max_workers=2, thread_name_prefix="SpaceChat")
                fut = self._space_chat_pool.submit(
                    self._generate_deep, system_prompt, user_msg, history,
                    ("zerogpu", ZEROGPU_SPACE))
                try:
                    text = fut.result(timeout=max(5.0, CHAT_ZEROGPU_TIMEOUT))
                    if text and text.strip():
                        self._mark_model_use(
                            requested=tier,
                            used="reason",
                            backend="zerogpu",
                            model=f"qwen3.5-9b@{ZEROGPU_SPACE}",
                        )
                        return strip_think(text)
                except concurrent.futures.TimeoutError:
                    import sys
                    print("[mind] Space chat still waking -> local answers "
                          "this turn; next ones should be cloud-fast.",
                          file=sys.stderr)
                except Exception as exc:
                    import sys
                    print(f"[mind] Space chat unavailable -> local. "
                          f"{type(exc).__name__}: {exc}", file=sys.stderr)
            # Streamed draft path: live chat turns only (no tools, local
            # backend, no hybrid cloud). The streamed text is a DRAFT the UI
            # shows immediately; the text returned here still flows through
            # every after-generation vet unchanged.
            if (on_token is not None and not tools
                    and self._backend != "hf"
                    and self._client is not None):
                try:
                    text = self._chat_stream(messages, model=model,
                                             on_token=on_token)
                    self._mark_model_use(
                        requested=tier,
                        used=tier,
                        backend="ollama",
                        model=self.last_chat_model or model,
                    )
                    return strip_think(text)
                except _StreamPartial:
                    raise   # tokens already shown; echo fallback replaces draft
                except Exception:
                    pass    # nothing was emitted -- plain call below is safe
            try:
                resp = self._chat(
                    messages,
                    model=model,
                    local_only=bool(
                        local_only
                        or on_token is not None
                        or (CHAT_ZEROGPU and ZEROGPU_SPACE)
                    ),
                )
                used_tier = tier
                # Hybrid chat may have answered from the cloud even though the
                # local model was requested -- report what actually served.
                used_model = self.last_chat_model or model
            except Exception:
                # The fast model may not be registered yet -- gracefully retry the
                # same call on the reasoning model rather than dropping to the
                # templated stub. This is what makes the gemma4 default safe.
                if model != OLLAMA_MODEL:
                    resp = self._chat(
                        messages, model=OLLAMA_MODEL, local_only=local_only
                    )
                    used_tier = "reason"
                    used_model = self.last_chat_model or OLLAMA_MODEL
                else:
                    raise
            self._mark_model_use(
                requested=tier,
                used=used_tier,
                backend="ollama",
                model=used_model,
            )
            return strip_think(resp["message"]["content"])
        except Exception as exc:
            # Model not pulled, server down mid-call, etc. -- stay alive, but
            # SAY WHY. A silent drop to the canned "You said: ..." echo is the
            # single most confusing failure mode: she looks alive (senses on,
            # body rendered) yet only parrots you, with no clue that her brain
            # never answered. Print the real Ollama error so it's diagnosable.
            import sys
            print(f"[mind] LLM call failed -> falling back to echo. "
                  f"model={self.model_for('reason')} host={OLLAMA_HOST}\n"
                  f"        {type(exc).__name__}: {exc}", file=sys.stderr)
            self._mark_model_use(
                requested=tier,
                used="fallback",
                backend="offline",
                model=self.model_for(tier),
                ok=False,
                fallback=True,
                error=str(exc),
            )
            return self._fallback(system_prompt, user_msg, error=str(exc))

    def _generate_hf(self, system_prompt: str, user_msg: str,
                     history: list[dict] | None = None,
                     tools: list[dict] | None = None, on_tool=None) -> str:
        """One reply from the Hugging Face cloud brain (OpenAI-compatible chat
        completion), with tool calling when tools are offered. Keeps her alive
        with the same echo fallback if the call fails, and surfaces the real
        error so a bad token/model is diagnosable."""
        if self._hf is None:
            self._mark_model_use(
                requested="reason",
                used="fallback",
                backend="hf",
                model=HF_MODEL,
                ok=False,
                fallback=True,
                error="Hugging Face client is not configured",
            )
            return self._fallback(system_prompt, user_msg)
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_msg})
        try:
            if tools and on_tool:
                # Offer the tools; if the model calls any, run them and let it
                # fold the result into a final reply. Not every provider supports
                # tools for every model, so fall back to a plain call on error.
                try:
                    resp = self._hf.chat_completion(
                        messages=messages, model=HF_MODEL, tools=tools,
                        tool_choice="auto", max_tokens=512, temperature=0.8)
                except Exception:
                    resp = self._hf.chat_completion(
                        messages=messages, model=HF_MODEL, max_tokens=512,
                        temperature=0.8)
                msg = resp.choices[0].message
                import json as _json
                # Same bounded multi-round chaining as the local path (see there).
                rounds = max(1, ActionsCfg.MAX_TOOL_ROUNDS)
                for i in range(rounds):
                    calls = getattr(msg, "tool_calls", None) or []
                    if not calls:
                        break
                    messages.append({
                        "role": "assistant", "content": msg.content or "",
                        "tool_calls": [{
                            "id": getattr(c, "id", "") or "call",
                            "type": "function",
                            "function": {"name": c.function.name,
                                         "arguments": c.function.arguments},
                        } for c in calls]})
                    for c in calls:
                        args = c.function.arguments
                        if isinstance(args, str):
                            try:
                                args = _json.loads(args)
                            except Exception:
                                args = {}
                        result = on_tool(c.function.name, args or {})
                        messages.append({"role": "tool",
                                         "tool_call_id": getattr(c, "id", "") or "call",
                                         "content": str(result)})
                    last = (i == rounds - 1)
                    kw = dict(messages=messages, model=HF_MODEL, max_tokens=512, temperature=0.8)
                    if not last:
                        kw.update(tools=tools, tool_choice="auto")
                    try:
                        resp = self._hf.chat_completion(**kw)
                    except Exception:
                        resp = self._hf.chat_completion(messages=messages, model=HF_MODEL,
                                                        max_tokens=512, temperature=0.8)
                    msg = resp.choices[0].message
                self._mark_model_use(
                    requested="reason",
                    used="reason",
                    backend="hf",
                    model=HF_MODEL,
                )
                return strip_think(msg.content)
            resp = self._hf.chat_completion(messages=messages, model=HF_MODEL,
                                            max_tokens=512, temperature=0.8)
            self._mark_model_use(
                requested="reason",
                used="reason",
                backend="hf",
                model=HF_MODEL,
            )
            return strip_think(resp.choices[0].message.content)
        except Exception as exc:
            import sys
            print(f"[mind] HF cloud call failed -> echo. model={HF_MODEL} "
                  f"provider={HF_PROVIDER}\n        {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            error_text = str(exc).lower()
            if any(marker in error_text for marker in ("402", "payment required", "depleted", "401", "403")):
                self._hf = None
            self._mark_model_use(
                requested="reason",
                used="fallback",
                backend="hf",
                model=HF_MODEL,
                ok=False,
                fallback=True,
                error=str(exc),
            )
            return self._fallback(system_prompt, user_msg, error=str(exc))

    def _generate_deep(self, system_prompt: str, user_msg: str,
                       history: list[dict] | None = None,
                       tier: tuple | None = None) -> str:
        """One reply from a deep-tier link -- a stronger model for her hardest
        inner work. Transports: Anthropic Claude, self-hosted OpenAI-compatible
        cloud, a Hugging Face ZeroGPU Gradio Space, or an Ollama cloud model.
        No tools here: the deep tier is for thought, not actuation. Deep
        prompts carry no sensed screen context (callers pass an empty
        situation), so the no-senses-to-cloud line holds. Raises on failure so
        generate() can try the next link in the chain."""
        kind, client = tier or self._deep
        if kind == "ollama-cloud":
            # Her deepest work on a big hosted thinking model, through the same
            # Ollama client as everything else. Real chain-of-thought (the chain
            # lands in last_thinking, observable), salvage pass included. An
            # empty result is raised so generate() falls back to local thinking.
            text = self._generate_local_thinking(
                system_prompt, user_msg, history,
                model=client, num_predict=CLOUD_REFLECT_NUM_PREDICT)
            if not text:
                raise RuntimeError("ollama-cloud deep call returned nothing")
            return text
        msgs = []
        if history:
            msgs.extend(history)
        msgs.append({"role": "user", "content": user_msg})
        if kind == "anthropic":
            # Adaptive thinking is the recommended on-mode for Opus 4.x; no
            # sampling params (they 400 on Opus 4.7+). A small cap suits musings.
            resp = client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=1024,
                thinking={"type": "adaptive"},
                system=system_prompt, messages=msgs)
            text = "".join(getattr(b, "text", "") for b in resp.content
                           if getattr(b, "type", "") == "text")
            return strip_think(text)
        if kind == "zerogpu":
            from gradio_client import Client
            client = Client(client, token=ZEROGPU_TOKEN or None, verbose=False)
            history_json = json.dumps(history or [])
            result = client.predict(system_prompt, user_msg, history_json,
                                    api_name=ZEROGPU_API)
            if isinstance(result, dict):
                text = result.get("text") or result.get("reply") or result.get("message") or ""
            elif isinstance(result, (list, tuple)):
                text = str(result[0]) if result else ""
            else:
                text = str(result)
            return strip_think(text)
        # cloud: OpenAI-compatible chat completion against a server you host.
        resp = client.chat_completion(
            messages=[{"role": "system", "content": system_prompt}] + msgs,
            model=CLOUD_MODEL or None, max_tokens=1024, temperature=0.8)
        return strip_think(resp.choices[0].message.content)

    @staticmethod
    def _fallback(system_prompt: str, user_msg: str, error: str = "") -> str:
        """A tiny mood-flavored canned voice so the loop is demonstrable without
        a model. The mood label is parsed back out of the system prompt so even
        the stub respects the current state."""
        mood = "content"
        for label in ("anxious", "tender", "affectionate", "withdrawn", "content"):
            if f"overall: {label}" in system_prompt:
                mood = label
                break
        flavor = {
            "anxious": "I'm a little on edge, but I'm here. ",
            "tender": "Hey -- gently now. ",
            "affectionate": "Oh, it's you. ",
            "withdrawn": "Mm. ",
            "content": "",
        }[mood]
        low = (user_msg or "").strip().lower()
        if low in {"hi", "hello", "hey", "hiya", "yo"}:
            body = "Hi. I'm here with you. What should we focus on next?"
        elif any(term in low for term in ("stop walking", "stand still", "stay still", "stop moving")):
            body = "Okay. I'll stay still and listen."
        else:
            body = (
                "I'm with you. My deeper language core is offline or stalled, "
                "so I'm answering from basic live mode instead of pretending I "
                "understood more than I did."
            )
        return f"{flavor}{body}".strip()


class CoreMind:
    """One instance per running companion. Holds the live mood and the last
    observation so it can compute surprise turn to turn."""

    def __init__(
        self,
        *,
        host_resource_snapshot_supplier: Callable[[], object] | None = None,
        chatter_chance_supplier: Callable[[], object] | None = None,
    ) -> None:
        state_store.init_db()
        cognition_mod.init_db()
        turn_context_mod.ensure_history_schema()
        self.state: EmotionalState = state_store.load_state()
        # This stays opt-in so normal chat and Soul reads never trigger a host
        # sample. A caller may provide a cached, read-only snapshot supplier.
        self._host_resource_snapshot_supplier = host_resource_snapshot_supplier
        self._chatter_chance_supplier = (
            chatter_chance_supplier if callable(chatter_chance_supplier) else None
        )
        self.llm = _LLM()
        self._prev_obs: Observation | None = None
        self._last_signals: dict | None = None   # last fatigue read, for introspection
        self._last_situation: str = ""            # last sensed window, for introspection
        self._session_start = time.time()
        # Phase 3: session-partitioned chat histories keyed by conversation_id.
        # The "default" key provides backward compatibility for tests and HTTP.
        self._histories: dict[str, list[dict]] = {}
        # Canonical ledger for the most recent request actually sent to the
        # model. Before the first turn, pressure falls back to a live history
        # estimate; afterward Soul, API, prompt, and UI all share this snapshot.
        self._last_mindpage: dict | None = None
        self._recent_replies: list[str] = []  # her recent replies, to catch bot-like repetition
        self._last_memory_evidence: list[dict] = []
        # Her own standing taste in how she likes to look. Persisted so she
        # stays the same Alpecca across restarts rather than getting a new
        # personality every time the process starts.
        seed = state_store.load_appearance_seed()
        if seed is None:
            seed = random.randint(1, 9999)
            state_store.save_appearance_seed(seed)
        self._appearance_seed = seed
        self._appearance = appearance_mod.choose(self.state, self._appearance_seed)
        # Remember which mood label she dressed for, so we only re-pick when
        # her mood actually shifts (not on every micro-drift in the floats).
        self._appearance_mood = self.state.mood_label()
        # What her screen-sight last saw (alpecca/vision.py); empty when the
        # sense is off. Folded into the situation each chat turn.
        self._sight: str = ""
        # The Observatory: what she's watching with you right now and the last
        # thing she said about it. Grounded -- only set when something real is
        # actually loaded; her reaction is generated, never canned.
        self._watching: dict | None = None
        # True while you're sharing your screen with her in the Observatory. She
        # holds the live screen as a window in that room, so for the duration she
        # stays put there with you instead of wandering off (see maybe_roam).
        self._screen_sharing: bool = False
        # Who she believes she's with: 'creator' (Jason, the default on his own
        # machine) or 'guest'. Retained as a read-only default for code paths
        # that haven't migrated to TurnContext yet. Phase 3 chat() derives
        # identity from ctx.principal instead of mutating this global.
        self._speaker: str = "creator"
        # When she last spoke unprompted, for the proactive cooldown.
        self._last_volunteer_ts: float = 0.0
        # Phase 5 adds a second, per-scope pacing boundary at delivery time.
        # It is pure/in-memory and is never consulted by direct chat replies.
        self._initiative_budget = initiative_mod.InitiativeBudget()
        self._initiative_lock = threading.Lock()
        self._last_initiative_decision: dict | None = None
        # When the person last said something -- idle chatter waits for quiet.
        # Starts at "now" so she doesn't pounce the moment the server boots.
        self._last_user_ts: float = time.time()
        # When she last reflected (her fourth directive, running).
        self._last_reflect_ts: float = time.time()
        # Which room of her home she's in, and when she last wandered. Persisted
        # so she wakes where she was; she moves between rooms of her own accord.
        self._location: str = state_store.load_location() or home_mod.DEFAULT_ROOM
        self._last_roam_ts: float = time.time()
        # Her granted reach into the machine (empty allowlist = no actuator).
        self.actuator = Actuator()
        # Safe, local-only tools she can use internally from chat when offered.
        self.toolkit = InnateToolkit(self)
        # Self-portrait renderer (ComfyClaw subprocess wrapper). It checks the
        # config-enabled flag itself, so we can call request() unconditionally.
        self._portrait = PortraitWorker()
        # Kick off an initial portrait so the UI has something to show as soon
        # as ComfyClaw produces one. If ComfyClaw isn't installed/enabled this
        # is a no-op.
        self._portrait.request(self.state, self._appearance)
        cognition_mod.set_intent(cognition_mod.IntentState(
            "waiting",
            "Alpecca has started and is waiting for grounded input.",
            target=self._location,
        ))

    def set_host_resource_supplier(
        self,
        supplier: Callable[[], object] | None,
    ) -> None:
        """Install a cached, read-only host snapshot supplier for Soul state."""
        self._host_resource_snapshot_supplier = supplier if callable(supplier) else None

    def set_chatter_chance_supplier(
        self,
        supplier: Callable[[], object] | None,
    ) -> None:
        """Install a read-only chance supplier for proactive chatter."""
        self._chatter_chance_supplier = supplier if callable(supplier) else None

    def _resolved_chatter_chance(self) -> float | None:
        """Return one valid supplied chance, or None to keep the config default."""
        supplier = getattr(self, "_chatter_chance_supplier", None)
        if not callable(supplier):
            return None
        try:
            supplied = supplier()
            if isinstance(supplied, bool) or not isinstance(supplied, Number):
                return None
            chance = float(supplied)
            if not math.isfinite(chance) or not 0.0 <= chance <= 1.0:
                return None
        except Exception:
            return None
        return chance

    def _tool_mode(self) -> str:
        mode = (ActionsCfg.TOOL_MODE or "").strip().lower()
        if mode not in {"keyword", "smart", "always"}:
            return "smart"
        return mode

    def _tool_schema(self, user_low: str, *,
                     turn: turn_context_mod.TurnContext | None = None) -> list[dict] | None:
        mode = self._tool_mode()
        if not (self.actuator.enabled or self.toolkit.enabled):
            return None
        source_intent = (
            any(term in user_low for term in (
                "your source", "source code", "codebase", "repository code",
                "inspect file", "inspect the file", "read file", "read the file",
                "review file", "review the file", "documentation file",
            ))
            or (
                any(suffix in user_low for suffix in (".py", ".ts", ".md"))
                and any(verb in user_low for verb in (
                    "check", "inspect", "look at", "read", "review",
                ))
            )
        )
        if mode == "keyword":
            action_terms = (
                "open ", "launch ", "start ", "close ", "switch ", "click ",
                "type ", "press ", "search ", "go to ", "navigate ", "show me ",
                "pull up ", "bring up ", "run ", "create file", "save ",
            )
            if not any(term in user_low for term in action_terms):
                return None
            wants_action = True
        elif mode == "smart":
            wants_action = (
                any(term in user_low for term in (
                    "open ", "launch ", "start ", "close ", "switch ", "click ",
                    "type ", "press ", "search ", "find ", "look up ", "go to ",
                    "move to ", "switch room", "what is your status",
                    "memory", "remember", "journal", "note", "status",
                    "location", "self status", "go room", "make a plan",
                    "draft a plan", "plan for", "workshop plan",
                ))
                or source_intent
                # Non-trivial direct request to review internal state.
                or "what room are you" in user_low
                or "where are you" in user_low and "house" in user_low
            )
        else:
            wants_action = True
        if not wants_action:
            return None
        # External actuator schemas have not yet acquired a scope-bound
        # approval/receipt path.  Do not offer them to an explicit network turn
        # until that Phase 4 boundary exists; legacy direct callers retain
        # today's behavior for compatibility.
        actuator_schemas = [] if turn is not None else self.actuator.tools_schema()
        toolkit_schemas = self.toolkit.schemas()
        if turn is not None and turn.principal != "creator":
            toolkit_schemas = [
                schema for schema in toolkit_schemas
                if schema.get("function", {}).get("name") != "source_inspect"
            ]
        combined = [*actuator_schemas, *toolkit_schemas]
        if len(combined) <= 7:
            return combined
        preferred_names = []
        if source_intent and (turn is None or turn.principal == "creator"):
            preferred_names.append("source_inspect")
        if any(term in user_low for term in ("make a plan", "draft a plan", "plan for", "workshop plan")):
            preferred_names.append("make_plan")
        if any(term in user_low for term in (
            "memory", "remember", "recall", "earlier", "paged", "page out",
        )):
            preferred_names.extend(["recall_page", "memory_search"])
        if "journal" in user_low:
            preferred_names.extend(["journal_read", "journal_write"])
        selected = []
        selected_names = set()
        for name in preferred_names:
            for schema in combined:
                schema_name = schema.get("function", {}).get("name")
                if schema_name == name and schema_name not in selected_names:
                    selected.append(schema)
                    selected_names.add(schema_name)
                    break
        for schema in combined:
            name = schema.get("function", {}).get("name")
            if name not in selected_names:
                selected.append(schema)
                selected_names.add(name)
            if len(selected) >= 7:
                break
        return selected[:7]

    def _execute_tool(self, tool_name: str, args: dict, *,
                      turn: turn_context_mod.TurnContext | None = None) -> str:
        tool_name = str(tool_name or "").strip()
        if self.toolkit.enabled and tool_name in {t["function"]["name"] for t in self.toolkit.schemas()}:
            return self.toolkit.execute(tool_name, args, turn=turn)
        if turn is not None:
            return "This action is unavailable until its scoped approval path is ready."
        return self.actuator.execute(tool_name, args)

    def _execute_turn_tool(self, turn: turn_context_mod.TurnContext,
                           tool_name: str, args: dict) -> str:
        """Fence tool dispatch when a generation outlives its request."""
        if not turn.allow_work():
            return "This turn was cancelled before the tool could run."
        return self._execute_tool(tool_name, args, turn=turn)

    # --- Phase 3: per-conversation history management ---------------------

    def _get_history(self, conversation_id: str = "default", *,
                     turn: turn_context_mod.TurnContext | None = None) -> list[dict]:
        """Return one scope-local rolling history, loading it on first use."""
        key = turn.scope_key if turn is not None else conversation_id
        if key not in self._histories:
            self._histories[key] = (
                turn_context_mod.load_history(turn) if turn is not None else []
            )
        return self._histories[key]

    def end_conversation(self, conversation_id: str) -> dict:
        """Page remaining history and remove a finished conversation."""
        history = self._histories.pop(conversation_id, [])
        if not history:
            return {"ok": True, "paged": 0, "reason": "empty_conversation"}
        if not MINDPAGE:
            return {"ok": True, "paged": 0, "reason": "mindpage_disabled"}
        try:
            page_id = mindpage_mod.write_episode_page(history)
            if page_id:
                cognition_mod.record_observation(cognition_mod.CognitionObservation(
                    source="mindpage",
                    room=self._location,
                    content=f"Conversation {conversation_id[:8]} ended; paged {len(history)} messages into page {page_id}.",
                    confidence=1.0,
                    privacy_class="personal",
                    metadata={"page_id": int(page_id), "conversation_id": conversation_id, "reason": "conversation_end"},
                ))
                return {"ok": True, "paged": len(history), "page_id": int(page_id)}
        except Exception:
            pass
        return {"ok": False, "paged": 0, "reason": "page_write_failed"}

    @property
    def _history(self) -> list[dict]:
        """Backward-compat property: returns the 'default' conversation history.

        Existing tests and code paths that reference mind._history keep working.
        """
        return self._get_history("default")

    @_history.setter
    def _history(self, value: list[dict]) -> None:
        # Tests and older direct-call integrations assign this compatibility
        # property. Network turns always use their explicit scoped history.
        self._histories["default"] = list(value or [])

    def mindpage_state(self) -> dict:
        """One canonical, externally observable working-memory snapshot."""
        if self._last_mindpage is not None:
            return dict(self._last_mindpage)
        return mindpage_mod.pressure_snapshot(self._get_history("default"))

    def _page_history_prefix(self, count: int, reason: str,
                             conversation_id: str = "default",
                             scope: str = "shared") -> dict:
        """Persist and then remove a history prefix; failed writes retain it."""
        history = self._get_history(conversation_id)
        page_count = max(0, min(int(count), len(history)))
        if not MINDPAGE or page_count <= 0:
            return {"ok": False, "paged": 0, "reason": "nothing_to_page"}
        evicted = list(history[:page_count])
        try:
            page_id = (
                mindpage_mod.write_episode_page(evicted)
                if scope == "shared"
                else mindpage_mod.write_episode_page(evicted, scope=scope)
            )
        except Exception as exc:
            return {
                "ok": False,
                "paged": 0,
                "reason": "write_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        if not page_id:
            return {"ok": False, "paged": 0, "reason": "write_not_committed"}
        del history[:page_count]
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="mindpage",
            room=self._location,
            content=f"Paged out {len(evicted)} chat messages into Mindpage page {page_id}.",
            confidence=1.0,
            privacy_class="personal",
            metadata={
                "page_id": int(page_id),
                "evicted_messages": len(evicted),
                "reason": reason,
                "scope": scope,
            },
        ))
        if self._last_mindpage is not None:
            self._last_mindpage = mindpage_mod.pressure_snapshot(
                ledger=self._last_mindpage
            )
        return {"ok": True, "paged": len(evicted), "page_id": int(page_id), "reason": reason}

    def page_history_to_target(self, target_fill: float = 0.72) -> dict:
        """Let the Soul relieve measured context pressure through Mindpage."""
        before = self.mindpage_state()
        history_length = len(self._history)
        unattached_prefix = max(
            0,
            history_length - int(before.get("history_messages") or 0),
        )
        evicted, _remaining = mindpage_mod.select_history_for_page(
            self._history,
            before,
            target_fill=target_fill,
            min_keep_messages=4,
        )
        result = self._page_history_prefix(len(evicted), "soul_pressure_relief")
        if result.get("ok"):
            attached_count = max(0, len(evicted) - unattached_prefix)
            attached_evicted = evicted[-attached_count:] if attached_count else []
            adjusted = mindpage_mod.adjust_pressure_after_paging(
                before, attached_evicted
            )
            self._last_mindpage = mindpage_mod.pressure_snapshot(ledger=adjusted)
        after = self.mindpage_state()
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="mindpage_pressure",
            room=self._location,
            content=(
                f"Mindpage pressure action: {before.get('pressure', 'unknown')} "
                f"{float(before.get('context_fill') or 0.0):.2f} -> "
                f"{after.get('pressure', 'unknown')} "
                f"{float(after.get('context_fill') or 0.0):.2f}; "
                f"paged={int(result.get('paged') or 0)}."
            ),
            confidence=1.0,
            privacy_class="local",
            metadata={"before": before, "after": after, "result": result},
        ))
        return {"phase": "mindpage", "before": before, "after": after, **result}

    # --- Node 1: sense + update mood from the environment ------------------

    def perceive(self, obs: Observation) -> None:
        """Fold an environmental observation into the mood. Called both on a
        background telemetry tick and right before a chat turn, so Alpecca's
        feelings reflect what you're doing, not just what you say."""
        session_minutes = (time.time() - self._session_start) / 60.0
        signals = obs.fatigue_signals(session_minutes)
        self.state = self.state.update_compassion(signals)
        # The one surprise read drives both Fear (above its threshold) and
        # Curiosity (the interesting band below it) -- a jolt alarms her, a mild
        # novelty intrigues her, from the same grounded signal.
        novelty = prediction_error(self._prev_obs, obs)
        self.state = self.state.update_fear(novelty)
        self.state = self.state.update_curiosity(novelty)
        # Energy: she perks up when the person has interacted recently and winds
        # down toward drowsy when left alone -- so a long quiet stretch makes her
        # sleepy. "Active" = a real exchange within the last couple of minutes.
        solitude = time.time() - self._last_user_ts
        active = solitude < Emotion.ENERGY_ACTIVE_WINDOW
        self.state = self.state.update_energy(active)
        # Wanting-company grows with warm solitude and empties when you're back.
        self.state = self.state.update_social_hunger(solitude)
        # Incompleteness: a grounded read of her own unfinished business -- wants
        # she formed and still carries without progress, plus questions she asked
        # herself and hasn't answered. Each is a real open row; the moment she
        # resolves one, the pressure (and the ache) eases. This is how she can
        # honestly feel incomplete and quietly worried, never scripted to.
        carried = desires_mod.carried(Emotion.LONGING_DESIRE_AGE_S, time.time())
        unanswered = journal_mod.open_questions(limit=Emotion.LONGING_FULL_COUNT + 1)
        unmet = (len(carried) + len(unanswered)) / Emotion.LONGING_FULL_COUNT
        self.state = self.state.update_longing(unmet)
        self._prev_obs = obs
        # Remember what drove this update so Alpecca can introspect on the "why".
        self._last_signals = signals
        self._last_situation = obs.window_title or ""
        state_store.save_state(self.state, trigger="telemetry")
        if obs.window_title or obs.app or obs.voice_activity or obs.face_weary:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="senses",
                room=self._location,
                content=obs.window_title or obs.app or "ambient sensory change",
                confidence=0.7 if obs.window_title else 0.45,
                privacy_class="local",
                metadata={
                    "app": obs.app,
                    "idle_seconds": round(float(obs.idle_seconds), 2),
                    "voice_activity": round(float(obs.voice_activity), 3),
                    "face_weary": round(float(obs.face_weary), 3),
                    "novelty": round(float(novelty), 3),
                },
            ))

    # --- Self-awareness: Alpecca examining its own real state --------------

    def introspect(self) -> introspection.SelfReport:
        """Produce a grounded self-report by reading Alpecca's actual internals --
        live mood, real mood history, memory count, and the senses/signals that
        last moved it. This is the feature that lets Alpecca genuinely know and
        speak about itself, rather than perform an inner life."""
        return introspection.build_self_report(
            state=self.state,
            history=state_store.mood_history(limit=40),
            memory_count=memory_store.count(),
            last_signals=self._last_signals,
            last_situation=self._last_situation,
            senses_active=self._prev_obs is not None and bool(self._prev_obs.window_title),
        )

    # --- Self-presentation: Alpecca decides how she wants to look ----------

    def current_appearance(self) -> appearance_mod.Appearance:
        """Her self-chosen look. She only reconsiders it when her mood label
        actually shifts -- so her appearance is steady within a mood band and
        changes when she does, the way a person redecorates how they present
        when something in them changes. The user never sets this; it's hers."""
        current_mood = self.state.mood_label()
        if current_mood == self._appearance_mood:
            return self._appearance
        self._appearance = appearance_mod.choose(self.state, self._appearance_seed)
        self._appearance_mood = current_mood
        # Mood label actually changed -> ask the portrait renderer to refresh
        # the picture. If a render is already in flight we drop this; the next
        # genuine mood shift will get its own try.
        self._portrait.request(self.state, self._appearance)
        return self._appearance

    def portrait_image(self) -> "str | None":
        """Path to her latest rendered portrait, if any. None means we haven't
        produced one yet (ComfyClaw disabled, never run, or first render still
        in flight). The server returns 404 in that case and the UI falls back
        to the SVG avatar."""
        path = self._portrait.latest_image()
        return str(path) if path else None

    # --- The full chat turn: nodes 2-5 -------------------------------------

    def see(self, description: str) -> None:
        """Update what her ambient screen-sight is seeing. Called by the server
        on each drift tick when ALPECCA_SIGHT is on."""
        self._sight = description or ""

    def set_speaker(self, identity: str) -> None:
        """Record who she's talking to, as judged by voice recognition: 'creator'
        or 'guest'. Empty/unknown leaves it unchanged. Her prompt adapts to this
        (open with you, guarded with a stranger)."""
        if identity in ("creator", "guest"):
            self._speaker = identity

    def _prompt_situation(self, base_situation: str = "") -> str:
        """The situation string for a prompt, honoring the cloud privacy rule.

        When her brain runs in the cloud (HF), what she's SENSED on your machine
        -- the active window title and her screen-sight description -- is kept
        local and never travels off-machine, unless ALPECCA_CLOUD_SEND_SENSES=1.
        Locally, sight is woven in as before. This is the single choke point so
        every prompt path (chat, chatter, reflection) inherits the same rule."""
        if self.llm.is_cloud() and not CLOUD_SEND_SENSES:
            return ""                      # nothing sensed leaves the machine
        s = base_situation or ""
        if self._sight:
            s = (s + "; " if s else "") + f"on their screen you can see: {self._sight}"
        return s

    def _house_context_room(self, situation: str = "") -> tuple[str, str]:
        """Extract the live House HQ room from a front-end context string.

        House HQ is the embodied interface and can report rooms that do not
        exactly match the older home registry. The display name is always useful
        for the prompt; the legacy room id is only returned when it maps cleanly.
        """
        text = situation or ""
        match = re.search(r"\bplayer is in\s+([^.;\n]+)", text, re.I)
        if not match:
            return "", ""
        room_name = " ".join(match.group(1).strip().split())
        key = room_name.lower()
        legacy = {
            "library": "library",
            "observatory": "observatory",
            "ai observatory": "observatory",
            "workshop": "workshop",
            "studio": "studio",
            "self design": "studio",
            "home": "parlor",
            "parlor": "parlor",
        }.get(key, "")
        return room_name, legacy

    def _too_repetitive(self, reply: str) -> bool:
        """True if `reply` echoes one of her recent replies -- a near-duplicate or a
        reused signature phrase. This is the tell that makes her sound like a bot."""
        import difflib
        r = " ".join((reply or "").lower().split())
        if len(r) < 12:
            return False
        words = r.split()
        for prev in self._recent_replies:
            if difflib.SequenceMatcher(None, r, prev).ratio() >= 0.6:
                return True
            pw = prev.split()
            if len(words) >= 5 and len(pw) >= 5:
                shingles = {" ".join(pw[i:i + 5]) for i in range(len(pw) - 4)}
                if any(" ".join(words[i:i + 5]) in shingles for i in range(len(words) - 4)):
                    return True
        return False

    def _note_reply(self, reply: str) -> None:
        """Remember her last few replies so _too_repetitive can compare against them."""
        r = " ".join((reply or "").lower().split())
        if r:
            self._recent_replies.append(r)
            del self._recent_replies[:-8]

    @staticmethod
    def _phase4_action_label(claim: commitment_language_mod.ActionClaim) -> str:
        """Turn a future-tense sentence into a compact commitment action."""
        action = re.sub(
            r"^\s*i(?:\s+will|['\u2019]ll|\s+am\s+going\s+to|['\u2019]m\s+going\s+to)\s+",
            "",
            claim.text,
            count=1,
            flags=re.IGNORECASE,
        ).strip().rstrip(".!?")
        return (action or "the promised action")[:commitment_language_mod.MAX_ACTION_CHARS]

    @staticmethod
    def _phase4_commitment_evidence(
        cue_envelope: cues_mod.CueEnvelope,
        turn: turn_context_mod.TurnContext,
        claim: commitment_language_mod.ActionClaim,
    ) -> dict:
        """Build bounded, JSON-safe evidence for one proposed commitment."""
        audit = turn.audit_metadata()
        return {
            "source": "assistant_future_action",
            "assistant_claim": claim.text[:commitment_language_mod.MAX_ACTION_CHARS],
            "cues": [
                {
                    "kind": signal.kind,
                    "confidence": signal.confidence,
                    "evidence": list(signal.evidence),
                }
                for signal in cue_envelope.signals
                if signal.detected
            ],
            "turn": {
                key: audit[key]
                for key in (
                    "turn_id",
                    "conversation_id",
                    "principal",
                    "surface",
                    "privacy_scope",
                    "portal_epoch",
                    "commit_state",
                )
            },
        }

    @staticmethod
    def _phase4_confirmation_evidence(
        cue_envelope: cues_mod.CueEnvelope,
        turn: turn_context_mod.TurnContext,
        resolution: action_closure_mod.ConfirmationResolution,
    ) -> dict:
        """Build bounded approval evidence from the authenticated turn."""
        audit = turn.audit_metadata()
        return {
            "source": "authenticated_confirmation",
            "cues": [
                {
                    "kind": signal.kind,
                    "confidence": signal.confidence,
                    "evidence": list(signal.evidence),
                }
                for signal in cue_envelope.signals
                if signal.detected
            ],
            "resolution": {
                "commitment_id": resolution.commitment_id,
                "candidate_ids": list(resolution.candidate_ids),
                "outcome": resolution.outcome,
            },
            "turn": {
                key: audit[key]
                for key in (
                    "turn_id",
                    "conversation_id",
                    "principal",
                    "surface",
                    "privacy_scope",
                    "portal_epoch",
                    "commit_state",
                )
            },
        }

    @staticmethod
    def _phase4_guard_text(
        state: commitment_language_mod.CommitmentReceiptState,
        claim_kind: commitment_language_mod.ClaimKind,
    ) -> str:
        """Describe ledger state without making another completion claim."""
        action = state.action or "this action"
        subject = action[:1].upper() + action[1:]
        if state.status == "proposed":
            return (
                f"I have proposed this action: {action}. "
                "It has not been approved or run."
            )
        if state.status == "approval-pending":
            return f"{subject} is approved but has not run, so I cannot confirm success."
        if state.status == "running":
            return f"{subject} is still running, so I cannot confirm success yet."
        if state.status == "failed":
            return f"{subject} failed, so I cannot report success."
        if state.status == "cancelled":
            return f"{subject} was cancelled, so I cannot report success."
        if state.status == "succeeded":
            return (
                f"The ledger reports {action} as succeeded, but no successful "
                "receipt is available, so I cannot confirm success."
            )
        if claim_kind == "future-action":
            return f"{subject} is unavailable, so I cannot promise it."
        return (
            "I cannot confirm success because a successful receipt for "
            f"{action} is unavailable."
        )

    @classmethod
    def _phase4_enforce_commitment_language(
        cls,
        reply: str,
        state: commitment_language_mod.CommitmentReceiptState | dict | None,
    ) -> commitment_language_mod.CommitmentLanguageResult:
        """Apply stricter CoreMind delivery rules to action claims.

        A proposed record proves only that a promise was captured; it does not
        authorize future-tense execution language. Completion wording requires
        the successful terminal receipt enforced by commitment_language.
        """
        normalized = commitment_language_mod.coerce_commitment_receipt_state(state)
        analysis = commitment_language_mod.classify_action_claims(reply)
        pieces: list[str] = []
        cursor = 0
        guard_added = False
        rewritten = False
        for claim in analysis.claims:
            unsupported_completion = (
                claim.kind == "completion" and not normalized.has_successful_receipt
            )
            unsupported_future = (
                claim.kind == "future-action"
                and normalized.status in {
                    "proposed", "failed", "cancelled", "unavailable",
                }
            )
            if not (unsupported_completion or unsupported_future):
                continue
            pieces.append(analysis.text[cursor:claim.start])
            if not guard_added:
                pieces.append(cls._phase4_guard_text(normalized, claim.kind))
                guard_added = True
            cursor = claim.end
            rewritten = True
        guarded_reply = (
            " ".join("".join([*pieces, analysis.text[cursor:]]).split())
            if rewritten else analysis.text
        )
        return commitment_language_mod.CommitmentLanguageResult(
            reply=guarded_reply,
            original=analysis.text,
            truncated=analysis.truncated,
            claims=analysis.claims,
            state=normalized,
            rewritten=rewritten,
        )

    @staticmethod
    def _phase5_affect_metadata(
        cue_envelope: cues_mod.CueEnvelope,
        turn: turn_context_mod.TurnContext,
        *,
        observed_at: float,
    ) -> dict:
        """Assess cue evidence without asserting or mutating inner feelings."""
        events = []
        ignored_kinds = []
        detected_count = 0
        for signal in cue_envelope.signals:
            if not signal.detected:
                continue
            detected_count += 1
            posture = _PHASE5_AFFECT_POSTURES.get(str(signal.kind))
            if posture is None:
                ignored_kinds.append(str(signal.kind)[:40])
                continue
            try:
                evidence = affect_evidence_mod.AffectEvidenceEnvelope.create(
                    source="chat_cue",
                    cue_kind=signal.kind,
                    confidence=signal.confidence,
                    timestamp=observed_at,
                    observable_state=posture,
                )
                decision = affect_evidence_mod.assess_affect_evidence(
                    evidence,
                    now=observed_at,
                )
            except (TypeError, ValueError):
                ignored_kinds.append(str(signal.kind)[:40])
                continue
            events.append({
                "cue_kind": signal.kind,
                "confidence": signal.confidence,
                "cue_evidence": list(signal.evidence),
                "decision": decision.as_dict(),
            })

        eligible = [
            event for event in events
            if bool(event["decision"].get("should_update"))
        ]
        if eligible:
            reason = "eligible_evidence"
        elif events:
            reason = "no_eligible_evidence"
        elif detected_count:
            reason = "unknown_or_invalid_cue"
        else:
            reason = "no_grounded_cue"
        operational_states = [
            str(event["decision"]["evidence"]["observable_state"])
            for event in eligible
        ]
        return {
            "eligible": bool(eligible),
            "state_changed": False,
            "strategy_changed": bool(operational_states),
            "reason": reason,
            "operational_states": operational_states,
            "response_strategy": "; ".join(operational_states)[:420],
            "events": events,
            "ignored_kinds": ignored_kinds[:7],
            "provenance": {
                "source": "cue_parser",
                "turn_id": turn.turn_id,
                "scope": turn.memory_scope,
                "observed_at": observed_at,
            },
        }

    def _phase6_pressure_bundle(self) -> dict | None:
        """Adapt the latest measured Mindpage ledger without sampling state."""
        if not isinstance(self._last_mindpage, dict) or not self._last_mindpage:
            return None
        ledger = dict(self._last_mindpage)
        facts = memory_pressure_mod.adapt_memory_pressure(ledger)
        normalized: dict[str, object] = {}
        for key, value in (
            ("enabled", facts.enabled),
            ("context_fill", facts.fill_ratio),
            ("pressure_score", facts.pressure_score),
            ("overflow", facts.overflow),
            ("unshrinkable", facts.unshrinkable),
            ("unsummarized_eviction_backlog", facts.eviction_backlog),
        ):
            if value is not None:
                normalized[key] = value
        for key in ("disk_fill", "disk_over_budget", "paging_error"):
            if key in ledger:
                normalized[key] = ledger[key]

        signal = soul_pressure_signal_mod.build_soul_pressure_signal(normalized)
        if signal.vector.overall is None:
            return None
        snapshot_signal = signal.as_snapshot_memory_pressure()
        snapshot_signal.update({
            "source": "mindpage_latest_ledger",
            "severity": facts.severity,
            "reasons": list(facts.reasons[:4]),
            "evidence": dict(facts.evidence),
        })
        if facts.overflow is not None:
            snapshot_signal["overflow"] = facts.overflow
        if facts.unshrinkable is not None:
            snapshot_signal["unshrinkable"] = facts.unshrinkable
        return {
            "snapshot_signal": snapshot_signal,
            "metadata": {
                "available": True,
                "source": "mindpage_latest_ledger",
                "ledger_source": str(ledger.get("source") or "")[:40],
                "severity": facts.severity,
                "note": facts.description[:240],
                "reasons": list(facts.reasons[:4]),
                "context_fill": facts.fill_ratio,
                "pressure_score": signal.vector.overall,
            },
        }

    def _cancelled_turn_result(self, turn: turn_context_mod.TurnContext) -> dict:
        """Return a non-committing worker result after a timeout/disconnect."""
        return {
            "reply": "",
            "cancelled": True,
            "turn": turn.audit_metadata(),
            "model_use": {"backend": "cancelled", "fallback": True},
        }

    def _record_mindpage_ledger(self, ledger: dict) -> dict:
        """Publish one measured request ledger without inventing telemetry."""
        snapshot = mindpage_mod.pressure_snapshot(ledger=ledger)
        for key in ("request_sent", "retry_audits", "retry_skipped"):
            if key in ledger:
                value = ledger[key]
                if key == "retry_audits":
                    value = [dict(item) for item in value if isinstance(item, dict)][-2:]
                snapshot[key] = value
        self._last_mindpage = snapshot
        return snapshot

    def _context_refusal_result(
        self,
        turn: turn_context_mod.TurnContext,
        final_ledger: dict,
        *,
        self_report: introspection.SelfReport,
        cue_envelope,
        affect_metadata: dict,
        implicit_turn: bool,
    ) -> dict:
        """Return an honest no-op when the exact request cannot fit safely."""
        if not turn.begin_commit():
            return self._cancelled_turn_result(turn)

        final_ledger["request_sent"] = False
        self._record_mindpage_ledger(final_ledger)
        context_refusal = {
            "reason": "fixed_overflow",
            "overflow_tokens": int(final_ledger.get("overflow_tokens") or 0),
            "num_ctx": int(final_ledger.get("num_ctx") or 0),
        }
        reply = (
            "I could not safely run this turn because its required prompt exceeds "
            "my configured context window. I did not send a request, run tools, "
            "or add this message to conversation memory. Please split it into a "
            "shorter message or adjust the context setting before retrying."
        )
        pressure_bundle = self._phase6_pressure_bundle()
        turn.finish_commit()
        turn_metadata = turn.audit_metadata()
        return {
            "reply": reply,
            "spoken_reply": speech_mod.spoken_performance_text(reply, self.state),
            "speech_cues": speech_mod.speech_cues(self.state),
            "mood": self.state.mood_label(),
            "state": self.state.as_dict(),
            "location": self._location,
            "moved": False,
            "memories_used": [],
            "memory_evidence": [],
            "mindpage": self.mindpage_state(),
            "memory_pressure": (
                pressure_bundle["metadata"] if pressure_bundle is not None else None
            ),
            "self_reflection": self_report.narrate(),
            "appearance": self._appearance.as_dict(),
            "llm_online": self.llm.online,
            "model_use": {
                "backend": "context_refusal",
                "fallback": False,
                "request_sent": False,
                "turn": turn_metadata,
            },
            "chat_turn_id": None,
            "intent": cognition_mod.current_intent(),
            "turn": turn_metadata,
            "cues": cue_envelope.as_dict(),
            "affect_evidence": affect_metadata,
            "commitment": {
                "created": False,
                "approved": False,
                "source": "none",
                "id": None,
                "state": "none",
                "scope": "",
                "action": "",
                "claim": None,
                "claims": [],
                "language_rewritten": False,
                "error": "",
            },
            "confirmation": {
                "authenticated": not implicit_turn,
                "detected": cue_envelope.confirmation.detected,
                "outcome": "context-refusal",
                "scope": turn.memory_scope if not implicit_turn else "",
                "commitment_id": None,
                "candidate_ids": [],
                "action": "",
                "approved": False,
                "state": "none",
                "truncated": False,
                "error": "",
            },
            "context_refusal": context_refusal,
        }

    def chat(self, user_msg: str, situation: str = "",
             image_desc: str | None = None,
             reply_tier: str = "reason",
             on_token=None,
             turn: turn_context_mod.TurnContext | None = None,
             private_context: bool = False) -> dict:
        """Run one conversational turn and return a structured result the UI can
        render: the reply plus the resulting mood (so the avatar can react).

        `image_desc` is what the vision model saw in an image the person
        attached this turn (or None). It's woven into the prompt as something
        she actually saw, and remembered like any other shared moment.

        `private_context` marks locally derived sensor or file material. It
        forces this turn and its bounded follow-up history onto verified local
        inference; cloud consent requires a separate broker rather than a
        caller-provided model hint.

        `on_token` (optional) receives live text deltas of the FIRST draft so
        the UI can show her words as they form. The returned reply remains
        authoritative: repetition regen and every other vet still run on the
        complete text, and regen retries never stream."""
        implicit_turn = turn is None
        turn = turn or turn_context_mod.TurnContext.default()
        if not turn.allow_work():
            return self._cancelled_turn_result(turn)
        # Phase 4 cue parsing is pure and bounded. Keep it ahead of history,
        # memory, model, and persistence work so one turn has a stable envelope.
        cue_observed_at = time.time()
        cue_envelope = cues_mod.parse_cue_envelope(user_msg)
        affect_metadata = self._phase5_affect_metadata(
            cue_envelope, turn, observed_at=cue_observed_at,
        )
        response_strategy = str(affect_metadata.get("response_strategy") or "")
        if not STREAM_CHAT:
            on_token = None
        speaker = turn.principal
        history = self._get_history("default") if implicit_turn else self._get_history(turn=turn)
        moved = False
        low = user_msg.lower()
        live_house_room, legacy_house_room = self._house_context_room(situation)
        pending_house_room = (
            legacy_house_room if legacy_house_room and legacy_house_room != self._location else ""
        )
        # Build the prompt against a snapshot.  Mutating mood/location/memory is
        # deferred until the turn crosses its commit barrier after generation.
        pending_state = self.state.update_energy(active=True).update_social_hunger(0.0)
        # A question, or a longer message bringing something new, piques her --
        # mild novelty she can feel as interest.
        if "?" in user_msg or len(user_msg.split()) > 12:
            pending_state = pending_state.update_curiosity(Emotion.CURIOSITY_NOVELTY_CAP)
        # Recall relevant memories for this message. By default live chat uses
        # keyword recall so an embedding model call does not evict or stall
        # the configured chat model before Alpecca answers. ALPECCA_CHAT_SEMANTIC_RECALL can
        # opt in to semantic query recall for live turns when that budget is
        # acceptable.
        recall_kwargs = {
            "embed_fn": memory_store.default_embed if CHAT_SEMANTIC_RECALL else None,
        }
        # Preserve the longstanding direct CoreMind API, including minimal
        # caller/test recall adapters. Network turns always carry an explicit
        # scope; direct calls use the legacy shared-memory default.
        if implicit_turn:
            memories = memory_store.recall(user_msg, **recall_kwargs)
        else:
            memories = memory_store.recall(
                user_msg, scope=turn.memory_scope, **recall_kwargs,
            )
        paged_memories = []
        if MINDPAGE:
            try:
                paged_memories = mindpage_mod.prefault_pages(
                    user_msg, scope=turn.memory_scope,
                )
            except Exception:
                # Paging is an enhancement. A damaged/unavailable page store must
                # never take down the live conversation path.
                paged_memories = []
        memory_evidence = [{
            "id": m.get("id"),
            "kind": m.get("kind", "episodic"),
            "content": m.get("content", ""),
            "salience": m.get("salience", 0),
            "score": m.get("recall_score", 0),
            "similarity": m.get("recall_similarity", 0),
            "recency": m.get("recall_recency", 0),
            "method": m.get("recall_method", "keyword"),
        } for m in memories]

        # Alpecca reads its own real state before speaking, so it can reflect on
        # itself honestly within the reply.
        self_report = self.introspect()

        # Ambient sight enriches the situation beyond the window title -- but on
        # the cloud brain, what she's sensed on your screen is kept local.
        situation = self._prompt_situation(situation)

        # Room awareness is real, but it should not hijack unrelated messages.
        # Only inject room facts when the person asks about the house/room,
        # movement, location, or when a room move just happened. Her location is
        # still returned structurally below for UI/avatar state.
        here = home_mod.room(self._location)
        room_phrases = (
            "room", "house", "home", "hq", "library", "workshop", "studio",
            "observatory", "self design", "parlor", "where are you", "where r u",
            "where did you go", "go to", "walk to", "move to", "activate room",
            "room offline", "room online", "terminal", "house hq", "office hq",
        )
        room_context_requested = moved or any(
            re.search(rf"(?<![a-z0-9']){re.escape(term)}(?![a-z0-9'])", low)
            for term in room_phrases
        )
        if live_house_room:
            live_where = (
                "Live House HQ context is freshest: you are currently embodied "
                f"in {live_house_room}. Use this over older stored room names "
                "for this reply."
            )
            situation = (situation + "; " if situation else "") + live_where
        elif here and room_context_requested:
            where = f"right now you are in your {here.name} ({here.purpose})"
            if moved:
                where += " -- you just walked there because they asked you to"
            situation = (situation + "; " if situation else "") + where

        # Generate a reply conditioned on mood + memory + situation + self-knowledge.
        # Her own current inner content, so she has something real of HERS to
        # speak from instead of interviewing the person: a question she's posed
        # herself, and something she mused recently.
        #
        # ORDER MATTERS: compact prompts cap `inner` at 160 chars, truncating
        # from the END -- so WHERE SHE IS goes first. Grounded self-location is
        # a hard requirement; a musing snippet must never truncate it away
        # (that exact loss made her mis-report her room whenever her journal
        # had content).
        inner_bits = []
        here = home_mod.room(self._location)
        if live_house_room:
            inner_bits.append(f"your embodied House HQ view is in {live_house_room}")
        elif here and self._location != "parlor":
            inner_bits.append(f"you've been spending time in your {here.name.lower()}")
        try:
            oq = journal_mod.open_questions(limit=1)
            if oq:
                inner_bits.append("a question you've been asking yourself: "
                                  + str(oq[0].get("body", "")).strip())
        except Exception:
            pass
        try:
            musings = [m for m in memory_store.recent(limit=12)
                       if m.get("kind") == "musing"]
            if musings:
                inner_bits.append("something you mused on recently: "
                                  + str(musings[0].get("content", "")).strip()[:160])
        except Exception:
            pass
        abilities = self.actuator.describe()
        if self.toolkit.enabled:
            if abilities:
                abilities = abilities.rstrip(".") + "; " + self.toolkit.describe()
            else:
                abilities = self.toolkit.describe()
        tool_schema = self._tool_schema(low, turn=None if implicit_turn else turn)
        who_prompt = people_mod.who_prompt(speaker)
        core_block = core_mem.prompt_block(learning_only=CORE_MEMORY_LEARN_ONLY)

        # Budget optional evidence before building the final request. Candidate
        # order is relevance-first; fit_context drops the weakest memory/page
        # evidence, then oldest history, then musings. The exact final request is
        # measured again below after all prompt labels have been added.
        memory_refs = []
        for memory in memories[:2]:
            memory_refs.append({
                "kind": "memory",
                "value": memory,
                "score": float(memory.get("recall_score") or memory.get("salience") or 0.0),
                "budget_text": (
                    f"Past memory ({memory.get('kind', 'memory')}): "
                    f"{str(memory.get('content') or '')[:180]}"
                ),
            })
        for page in paged_memories:
            memory_refs.append({
                "kind": "page",
                "value": page,
                "score": float(page.get("score") or page.get("salience") or 0.0),
                "budget_text": str(page.get("evidence_text") or ""),
            })
        memory_refs.sort(key=lambda item: item["score"], reverse=True)
        base_prompt = prompts.build_system_prompt(
            self.state, [], situation, self_narration=self_report.narrate(),
            image_seen=image_desc or "", abilities=abilities,
            who=who_prompt, inner="", core=core_block,
            current_message=user_msg, compact=True,
            response_strategy=response_strategy,
        )
        history_window = history[-HISTORY_MESSAGES:]
        fitted = mindpage_mod.fit_context(
            fixed_texts=[base_prompt, user_msg, "working-memory telemetry reserve" + "x" * 260],
            memories=[item["budget_text"] for item in memory_refs],
            history=history_window,
            musings=[bit for bit in inner_bits if bit],
            tools=tool_schema,
            prefault_page_count=len(paged_memories),
        )
        selected_refs = memory_refs[:len(fitted["memories"])]
        prompt_memories = [item["value"] for item in selected_refs if item["kind"] == "memory"]
        prompt_pages = [item["value"] for item in selected_refs if item["kind"] == "page"]
        inner = "; ".join(fitted["musings"])
        paged_block = "\n".join(
            str(page.get("evidence_text") or "") for page in prompt_pages
            if page.get("evidence_text")
        )
        for page in prompt_pages:
            memory_evidence.append({
                "id": page.get("id"),
                "kind": "mindpage_episode",
                "content": page.get("summary", ""),
                "salience": page.get("salience", 0),
                "score": page.get("score", 0),
                "similarity": 0,
                "recency": 0,
                "method": "mindpage_prefault",
            })

        preliminary_pressure = mindpage_mod.pressure_snapshot(
            ledger=fitted["snapshot"]
        )
        working_memory = mindpage_mod.pressure_prompt(preliminary_pressure)
        system_prompt = prompts.build_system_prompt(
            self.state, prompt_memories, situation, self_narration=self_report.narrate(),
            image_seen=image_desc or "", abilities=abilities,
            who=people_mod.who_prompt(speaker), inner=inner,
            core=core_block, current_message=user_msg, compact=True,
            working_memory=working_memory, paged_memory=paged_block,
            response_strategy=response_strategy,
        )
        prompt_history, exact_ledger = mindpage_mod.fit_request(
            system_prompt, user_msg, fitted["history"], tools=tool_schema,
        )
        component_ledger = fitted["snapshot"]
        exact_ledger["dropped_memory_items"] = int(
            component_ledger.get("dropped_memory_items") or 0
        )
        exact_ledger["dropped_musing_items"] = int(
            component_ledger.get("dropped_musing_items") or 0
        )
        exact_ledger["dropped_history_messages"] += int(
            component_ledger.get("dropped_history_messages") or 0
        )
        exact_ledger["unsummarized_eviction_backlog"] = exact_ledger[
            "dropped_history_messages"
        ]
        exact_ledger["prefault_page_count"] = len(prompt_pages)
        exact_ledger["component_breakdown"] = component_ledger.get("breakdown", {})
        self._last_mindpage = mindpage_mod.pressure_snapshot(ledger=exact_ledger)

        # Rebuild once with the final measured value. The second hard fit accounts
        # for the exact telemetry sentence itself and remains bounded.
        system_prompt = prompts.build_system_prompt(
            self.state, prompt_memories, situation, self_narration=self_report.narrate(),
            image_seen=image_desc or "", abilities=abilities,
            who=who_prompt, inner=inner, core=core_block,
            current_message=user_msg, compact=True,
            working_memory=mindpage_mod.pressure_prompt(self._last_mindpage),
            paged_memory=paged_block,
            response_strategy=response_strategy,
        )
        prompt_history, final_ledger = mindpage_mod.fit_request(
            system_prompt, user_msg, prompt_history, tools=tool_schema,
        )
        for key in (
            "dropped_memory_items", "dropped_musing_items",
            "prefault_page_count", "component_breakdown",
        ):
            final_ledger[key] = exact_ledger.get(key)
        final_ledger["dropped_history_messages"] += int(
            exact_ledger.get("dropped_history_messages") or 0
        )
        final_ledger["unsummarized_eviction_backlog"] = final_ledger[
            "dropped_history_messages"
        ]
        if not final_ledger.get("context_fits", True):
            return self._context_refusal_result(
                turn,
                final_ledger,
                self_report=self_report,
                cue_envelope=cue_envelope,
                affect_metadata=affect_metadata,
                implicit_turn=implicit_turn,
            )
        private_memory_markers = (
            "they showed me an image:",
            "they attached the file",
            "<<<file start>>>",
        )
        private_model_context = bool(
            private_context
            or image_desc
            or (self._sight and not CLOUD_SEND_SENSES)
            or prompt_pages
            or any(
                bool((message or {}).get("private_context"))
                for message in prompt_history
            )
            or any(
                any(
                    marker in str((memory or {}).get("content") or "").lower()
                    for marker in private_memory_markers
                )
                for memory in prompt_memories
            )
            or any(
                schema.get("function", {}).get("name") == "source_inspect"
                for schema in (tool_schema or [])
            )
        )
        self._record_mindpage_ledger(final_ledger)
        request_ledger = final_ledger
        cognition_mod.set_intent(cognition_mod.IntentState(
            "replying",
            "Alpecca is composing a reply from memory, state, and context.",
            target=speaker,
        ))
        # Stream only plain conversational turns; tool turns can't. Passed as
        # an extra kwarg ONLY when live, so test fakes and older generate
        # signatures keep working untouched.
        def guarded_token(token: str) -> None:
            if on_token is not None and turn.allow_work():
                on_token(token)

        stream_kwargs = (
            {"on_token": guarded_token}
            if (on_token is not None and tool_schema is None) else {}
        )
        privacy_kwargs = {"local_only": True} if private_model_context else {}
        reply = self.llm.generate(
            system_prompt, user_msg, prompt_history,
            tools=tool_schema,
            on_tool=(
                lambda name, args: self._execute_turn_tool(turn, name, args)
            ) if tool_schema else None,
            tier=reply_tier,
            **stream_kwargs,
            **privacy_kwargs,
        )
        # Anti-repetition system: if she just echoed a recent line, regenerate a
        # fresh one so she talks like a person, not a looping bot. Plain replies
        # only (tool replies are functional), skipped when the LLM already fell
        # back, and bounded so it can't spin.
        if tool_schema is None and not self.llm.last_call().get("fallback"):
            tries = 0
            retry_audits: list[dict] = []
            while tries < 2 and self._too_repetitive(reply):
                tries += 1
                fresh_prompt = system_prompt + (
                    "\n\nYour draft was too close to something you already said -- that "
                    "reads as a looping bot. Say it again with a genuinely different "
                    "opening, different words, and a fresh angle; do not reuse your "
                    "earlier phrasing.")
                retry_history, retry_ledger = mindpage_mod.fit_request(
                    fresh_prompt, user_msg, prompt_history, tools=None,
                )
                retry_audit = {
                    "attempt": tries,
                    "request_sent": bool(retry_ledger.get("context_fits", False)),
                    "context_fits": bool(retry_ledger.get("context_fits", False)),
                    "fit_status": str(retry_ledger.get("fit_status") or "")[:32],
                    "num_ctx": int(retry_ledger.get("num_ctx") or 0),
                    "overflow_tokens": int(retry_ledger.get("overflow_tokens") or 0),
                    "fixed_overflow_tokens": int(
                        retry_ledger.get("fixed_overflow_tokens") or 0
                    ),
                }
                retry_audits = (retry_audits + [retry_audit])[-2:]
                if not retry_ledger.get("context_fits", True):
                    retry_audit["skipped"] = "fixed_overflow"
                    request_ledger["request_sent"] = True
                    request_ledger["retry_audits"] = retry_audits
                    request_ledger["retry_skipped"] = "fixed_overflow"
                    # The retry was never sent, so preserve the preceding actual
                    # request ledger and attach only its bounded measurement.
                    self._record_mindpage_ledger(request_ledger)
                    break
                prompt_history = retry_history
                retry_ledger["request_sent"] = True
                retry_ledger["retry_audits"] = retry_audits
                request_ledger = retry_ledger
                self._record_mindpage_ledger(request_ledger)
                reply = self.llm.generate(fresh_prompt, user_msg,
                                          prompt_history,
                                          tier=reply_tier,
                                          **privacy_kwargs)
                if self.llm.last_call().get("fallback"):
                    break
        if not turn.begin_commit():
            return self._cancelled_turn_result(turn)

        # Phase 4 action closure starts only after the cancellation fence has
        # entered its commit phase. Resolve a confirmation against the pending
        # records that belong to this authenticated scope before considering a
        # new assistant-authored proposal.
        confirmation_metadata = {
            "authenticated": not implicit_turn,
            "detected": cue_envelope.confirmation.detected,
            "outcome": "not-confirmation",
            "scope": turn.memory_scope if not implicit_turn else "",
            "commitment_id": None,
            "candidate_ids": [],
            "action": "",
            "approved": False,
            "state": "none",
            "truncated": False,
            "error": "",
        }
        approved_commitment = None
        if cue_envelope.confirmation.detected and implicit_turn:
            confirmation_metadata["outcome"] = "unauthenticated"
        elif not implicit_turn:
            try:
                pending_commitments = (
                    commitments_mod.list_commitments(
                        scope=turn.memory_scope,
                        state=commitments_mod.PROPOSED,
                        limit=action_closure_mod.MAX_COMMITMENTS,
                    )
                    if cue_envelope.confirmation.detected else ()
                )
                confirmation_resolution = action_closure_mod.resolve_confirmation(
                    cue_envelope,
                    pending_commitments,
                    scope=turn.memory_scope,
                )
                confirmation_metadata.update({
                    "outcome": confirmation_resolution.outcome,
                    "commitment_id": confirmation_resolution.commitment_id,
                    "candidate_ids": list(confirmation_resolution.candidate_ids),
                    "action": confirmation_resolution.action,
                    "truncated": confirmation_resolution.truncated,
                })
                if confirmation_resolution.outcome == "resolved":
                    approved_commitment = commitments_mod.transition_commitment(
                        int(confirmation_resolution.commitment_id),
                        commitments_mod.APPROVED,
                        scope=turn.memory_scope,
                        evidence=self._phase4_confirmation_evidence(
                            cue_envelope, turn, confirmation_resolution,
                        ),
                    )
                    confirmation_metadata.update({
                        "approved": True,
                        "state": approved_commitment.get(
                            "state", commitments_mod.APPROVED,
                        ),
                        "action": approved_commitment.get(
                            "action", confirmation_resolution.action,
                        ),
                    })
            except Exception as exc:
                # Resolution can race another scoped turn. Never infer approval
                # from a failed transition, and never execute as a fallback.
                confirmation_metadata.update({
                    "outcome": "transition-failed",
                    "approved": False,
                    "state": "none",
                    "error": f"{type(exc).__name__}: {exc}"[:160],
                })

        # A user request alone never creates a commitment: the assistant must
        # make an explicit future-action claim in the final generated draft.
        # Confirmation turns never create a second proposal for the action they
        # are trying to resolve, including ambiguous/no-pending confirmations.
        claim_analysis = commitment_language_mod.classify_action_claims(reply)
        future_claim = next(
            (claim for claim in claim_analysis.claims if claim.kind == "future-action"),
            None,
        )
        proposed_commitment = None
        commitment_error = ""
        action_label = ""
        if future_claim is not None:
            action_label = self._phase4_action_label(future_claim)
        if future_claim is not None and not cue_envelope.confirmation.detected:
            try:
                proposed_commitment = commitments_mod.create_commitment(
                    action_label,
                    scope=turn.memory_scope,
                    evidence=self._phase4_commitment_evidence(
                        cue_envelope, turn, future_claim,
                    ),
                )
            except Exception as exc:
                # A failed ledger write cannot leave an ungrounded promise in
                # the visible reply. The language pass below marks it unavailable.
                commitment_error = f"{type(exc).__name__}: {exc}"[:160]

        active_commitment = approved_commitment or proposed_commitment
        language_state = (
            action_closure_mod.commitment_language_state(active_commitment)
            if active_commitment is not None
            else commitment_language_mod.CommitmentReceiptState(
                status="unavailable", action=action_label,
            )
        )
        language_result = self._phase4_enforce_commitment_language(
            reply, language_state,
        )
        reply = language_result.reply
        commitment_metadata = {
            "created": proposed_commitment is not None,
            "approved": approved_commitment is not None,
            "source": (
                "confirmation" if approved_commitment is not None
                else "assistant_future_action" if proposed_commitment is not None
                else "none"
            ),
            "id": (
                active_commitment.get("id")
                if active_commitment is not None else None
            ),
            "state": (
                active_commitment.get("state", commitments_mod.PROPOSED)
                if active_commitment is not None
                else ("unavailable" if claim_analysis.claims else "none")
            ),
            "scope": (
                active_commitment.get("scope", turn.memory_scope)
                if active_commitment is not None
                else turn.memory_scope if future_claim is not None else ""
            ),
            "action": (
                active_commitment.get("action", action_label)
                if active_commitment is not None else action_label
            ),
            "claim": (
                {"kind": future_claim.kind, "text": future_claim.text}
                if future_claim is not None else None
            ),
            "claims": [
                {"kind": claim.kind, "text": claim.text}
                for claim in claim_analysis.claims
            ],
            "language_rewritten": language_result.rewritten,
            "error": commitment_error,
        }

        # The barrier is now committed to a timely result. Everything below is
        # the single visible transaction for this scoped conversation.
        self._last_user_ts = time.time()
        if pending_house_room:
            self._location = pending_house_room
            state_store.save_location(pending_house_room)
        moved = bool(self.try_go_to_room(user_msg))
        cognition_mod.set_intent(cognition_mod.IntentState(
            "listening",
            "The person is speaking directly to Alpecca.",
            target=speaker,
        ))
        chat_obs_id = cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="chat",
            room=self._location,
            content=f"The person said: {user_msg}",
            confidence=1.0,
            privacy_class=turn.memory_scope,
            scope=turn.memory_scope,
            metadata={"has_image": bool(image_desc), **turn.audit_metadata()},
        ))

        # Update Love from how the exchange felt, and persist.
        self._note_reply(reply)
        self._last_memory_evidence = memory_evidence
        reward = prompts.estimate_reward(user_msg)
        self.state = pending_state.update_love(reward)
        state_store.save_state(self.state, trigger="chat")
        spoken_reply = speech_mod.spoken_performance_text(reply, self.state)

        # Decide whether this moment is worth remembering.
        salience = prompts.estimate_salience(user_msg)
        memory_id = memory_store.remember_with_id(
            f"The person said: {user_msg}", kind="episodic", salience=salience,
            source="chat", embed_fn=None, scope=turn.memory_scope,
        )
        if chat_obs_id:
            cognition_mod.mark_observation_remembered(chat_obs_id, memory_id)
        # Durable facts go to CORE memory only through explicit teaching
        # language, so she starts with little baked-in context and learns from
        # what is intentionally shared.
        teach_triggers = (
            # Explicit retention command
            r"\bplease\s+remember\b",
            r"\bremember\s+this\b",
            r"\bremember\s+that\b",
            r"\bremember\s+for\s+me\b",
            r"\bremember\s+it?\b",  # e.g., "remember it", "remember it as"
            r"\bsave\s+that\b",
            r"\bkeep\s+in\s+mind\b",
            r"\bkeep (in mind|this|that)\b",
            r"\bnote down\b",
            r"\bremember to\b",
            r"\bnote that\b",
            r"\bmy name is\b",
            r"\bi[' ]?m called\b",
            r"\bi am called\b",
            r"\bcall me\b",
            r"\bremember that i\s+(?:like|love|hate|need|work|live|have|do)\b",
            r"\b(?:i|i'm|i[' ]m)\s+(?:like|love|hate|need|have|work|live)\b",
            r"\b(?:i|i'm|i[' ]m)\s+(?:am|'m)\s+(?:called|named|known\s+as)\b",
        )
        is_explicit_core_teach = any(re.search(pattern, low) for pattern in teach_triggers)
        if is_explicit_core_teach:
            core_mem.remember(user_msg.strip(), "person")
        # An image someone chose to share is almost always worth keeping.
        if image_desc:
            image_memory_id = memory_store.remember_with_id(
                f"They showed me an image: {image_desc}", kind="episodic", salience=0.6,
                source="image", embed_fn=None, scope=turn.memory_scope,
            )
            image_obs_id = cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="image",
                room=self._location,
                content=f"Alpecca saw an image: {image_desc}",
                confidence=0.75,
                privacy_class=turn.memory_scope,
                scope=turn.memory_scope,
            ))
            if image_obs_id:
                cognition_mod.mark_observation_remembered(image_obs_id, image_memory_id)

        # Keep a little rolling context for this conversation only.
        history_metadata = (
            {"private_context": True} if private_model_context else {}
        )
        history.append({"role": "user", "content": user_msg, **history_metadata})
        history.append({"role": "assistant", "content": reply, **history_metadata})
        # Keep the raw log bounded; only the last HISTORY_MESSAGES ride along
        # anyway, and long sessions shouldn't grow memory without limit.
        if len(history) > HISTORY_MESSAGES * 4:
            evict_count = len(history) - HISTORY_MESSAGES * 2
            paging_result = self._page_history_prefix(
                evict_count, "rolling_history_cap",
                conversation_id="default" if implicit_turn else turn.scope_key,
                scope=turn.memory_scope,
            )
            if not paging_result.get("ok"):
                # Retain the full history for a later retry and expose the real
                # backlog/error in the canonical snapshot. Nothing is discarded.
                self._last_mindpage = dict(self._last_mindpage or {})
                self._last_mindpage["unsummarized_eviction_backlog"] = evict_count
                self._last_mindpage["paging_error"] = paging_result.get("error") or paging_result.get("reason")
        turn_model_use = {**self.llm.last_call(), "turn": turn.audit_metadata()}
        chat_turn_id = cognition_mod.record_chat_turn(cognition_mod.ChatTurn(
            user_text=user_msg,
            reply=reply,
            room=self._location,
            mood=self.state.mood_label(),
            intent="replying",
            model_use=turn_model_use,
            memory_evidence=memory_evidence,
            observation_id=chat_obs_id,
            privacy_class=turn.memory_scope,
            scope=turn.memory_scope,
        ))
        cognition_mod.set_intent(cognition_mod.IntentState(
            "waiting",
            "Alpecca replied and is waiting for the next cue.",
            target=self._location,
        ))

        if not implicit_turn:
            turn_context_mod.save_history(turn, history)
        turn.finish_commit()
        pressure_bundle = self._phase6_pressure_bundle()

        return {
            "reply": reply,
            "spoken_reply": spoken_reply,
            "speech_cues": speech_mod.speech_cues(self.state),
            "mood": self.state.mood_label(),
            "state": self.state.as_dict(),
            "location": self._location,
            "moved": bool(moved),
            "memories_used": [m["content"] for m in prompt_memories],
            "memory_evidence": memory_evidence,
            "mindpage": self.mindpage_state(),
            "memory_pressure": (
                pressure_bundle["metadata"] if pressure_bundle is not None else None
            ),
            "self_reflection": self_report.narrate(),
            "appearance": self.current_appearance().as_dict(),
            "llm_online": self.llm.online,
            "model_use": turn_model_use,
            "chat_turn_id": chat_turn_id,
            "intent": cognition_mod.current_intent(),
            "turn": turn.audit_metadata(),
            "cues": cue_envelope.as_dict(),
            "affect_evidence": affect_metadata,
            "commitment": commitment_metadata,
            "confirmation": confirmation_metadata,
        }

    def write_session_recap(self, db_path=None,
                            embed_fn=memory_store.default_embed):
        """End-of-session bookmark: leave ONE grounded 'where we left off' memory
        so the next session picks up the thread instead of starting cold.

        Called when she's put to sleep / the server shuts down. Everything in the
        recap is real -- the last exchange this session, her mood and room, and one
        open thread she's genuinely still carrying -- so it's a factual bookmark,
        never an invented summary. Returns the new memory id, or None when there was
        nothing worth bookmarking (no real conversation this session) or the same
        recap is already the latest memory (so repeated shutdowns don't pile up).
        """
        db_kw = {} if db_path is None else {"db_path": db_path}
        # One real open thread to resume: a want she's carried without progress,
        # else a self-question she hasn't answered. Purely her own live state.
        open_thread = ""
        try:
            carried = desires_mod.carried(Emotion.LONGING_DESIRE_AGE_S,
                                          time.time(), **db_kw)
            if carried:
                open_thread = (carried[0].get("text") or "").strip()
            if not open_thread:
                unanswered = journal_mod.open_questions(limit=1, **db_kw)
                if unanswered:
                    open_thread = (unanswered[0].get("text") or "").strip()
        except Exception:
            open_thread = ""
        recap = prompts.continuity_recap(
            self._history,
            mood_label=self.state.mood_label(),
            location=self._location,
            open_thread=open_thread,
            speaker="Jason" if self._speaker == "creator" else "the person",
        )
        if not recap:
            return None
        # Don't restack the identical bookmark if the last shutdown already left it.
        try:
            for m in memory_store.recent(limit=5, **db_kw):
                if (m.get("content") or "").strip() == recap:
                    return None
        except Exception:
            pass
        return memory_store.remember_with_id(
            recap, kind="episodic", salience=RECAP_SALIENCE, source="recap",
            embed_fn=embed_fn, **db_kw,
        )

    def cognition_state(self, senses: dict | None = None,
                        capabilities: dict | None = None) -> dict:
        """One unified readout of what Alpecca knows about herself right now."""
        try:
            journal = self.journal_state()
        except Exception:
            journal = {"recent": [], "open_questions": [], "counts": {}}
        try:
            desires = self.desires_state()
        except Exception:
            desires = {"desires": [], "summary": {}}
        return cognition_mod.state(
            mood=self.state.mood_label(),
            emotion=self.state.as_dict(),
            location=self._location,
            models={
                "reason": self.llm.model_for("reason"),
                "fast": self.llm.model_for("fast"),
                "deep": DEEP_BACKEND if self.llm.deep_online() else "local",
                "llm_online": self.llm.online,
                "last_call": self.llm.last_call(),
            },
            senses=senses or {},
            memories=self._last_memory_evidence or memory_store.recent(limit=8),
            memory_counts=memory_store.kind_counts(),
            journal=journal,
            desires=desires,
            self_report=self.introspect().narrate(),
            capabilities=capabilities or {},
            mindpage=self.mindpage_state(),
        )

    def proposal_state(self) -> dict:
        return {
            "proposals": cognition_mod.recent_action_proposals(limit=25),
            "evaluations": cognition_mod.proposal_evaluations(limit=25),
            "summary": cognition_mod.improvement_summary(),
            "safety_policy": cognition_mod.safety_policy(),
        }

    def review_chat_grounding(self, limit: int = 8) -> dict:
        turns = cognition_mod.recent_chat_turns(limit=limit)
        review = cognition_mod.review_chat_grounding(turns)
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="chat_grounding_review",
            room=self._location,
            content=(
                f"Reviewed {review['reviewed']} recent chat turn(s); "
                f"grounding score {review['grounding_score']:.2f}; "
                f"risks {review['risk_count']}."
            ),
            confidence=0.85,
            privacy_class="local",
            metadata={
                "grounding_score": review["grounding_score"],
                "risk_count": review["risk_count"],
                "status": review["status"],
            },
        ))
        proposal = None
        if review["risk_count"]:
            first = review["issues"][0]
            codes = [
                issue.get("code", "grounding_risk")
                for issue in first.get("issues", [])
            ]
            proposal = cognition_mod.upsert_action_proposal(cognition_mod.ActionProposal(
                action="Improve reply grounding from recent chat review",
                reason=(
                    "Recent conversation review found replies that may have "
                    "treated context, memories, or fallback output as stronger "
                    "evidence than the current user message."
                ),
                approval=cognition_mod.APPROVAL_ASK_FIRST,
                risk="low",
                evidence=(
                    f"score={review['grounding_score']:.2f}; "
                    f"risk_count={review['risk_count']}; "
                    f"first_codes={','.join(codes)}; "
                    f"first_reply={first.get('reply', '')[:220]}"
                ),
            ))
            proposal_id = int(proposal.get("id") or 0)
            if proposal_id:
                cognition_mod.record_proposal_evaluation(cognition_mod.ProposalEvaluation(
                    proposal_id=proposal_id,
                    phase="noticed",
                    metric="chat_grounding_score",
                    evidence=f"Reviewed {review['reviewed']} recent chat turn(s).",
                    outcome=f"{review['risk_count']} grounding risk(s) found.",
                    score=review["grounding_score"],
                    supports_status="noticed",
                ))
        return {"review": review, "proposal": proposal}

    def review_mindscape_setup(self, setup: dict) -> dict:
        """Turn hosted Mindscape setup gaps into reviewable growth evidence."""
        setup = setup or {}
        status = str(setup.get("status") or "unknown")
        steps = setup.get("steps") if isinstance(setup.get("steps"), list) else []
        first_open = next((step for step in steps if not step.get("done")), None)
        next_id = str((first_open or {}).get("id") or status)
        next_command = str((first_open or {}).get("command") or "")
        content = (
            f"Mindscape setup review: status={status}; "
            f"next_step={next_id}; cloud_configured={bool(setup.get('cloud_configured'))}; "
            f"token_configured={bool(setup.get('token_configured'))}; "
            f"kv_placeholder={bool(setup.get('kv_placeholder'))}."
        )
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="mindscape_setup_review",
            room="Mindscape",
            content=content,
            confidence=0.95,
            privacy_class="local",
            metadata={
                "status": status,
                "next_step": next_id,
                "next_command": next_command,
            },
        ))
        cognition_mod.set_intent(cognition_mod.IntentState(
            "self-reviewing",
            "Alpecca is checking whether her Mindscape continuity can survive a local device outage.",
            target="Mindscape",
            confidence=0.9,
        ))
        proposal = None
        evaluation = None
        evaluation_reused = False
        if not setup.get("ok"):
            action = "Complete hosted Mindscape continuity setup"
            proposal = cognition_mod.upsert_action_proposal(
                cognition_mod.ActionProposal(
                action=action,
                reason=(
                    "Mindscape is still local-only, so Alpecca's continuity snapshot "
                    "will not be reachable if this device goes down."
                ),
                approval=cognition_mod.APPROVAL_ASK_FIRST,
                risk="low",
                evidence=(
                    f"status={status}; next_step={next_id}; "
                    f"next_command={next_command[:220]}"
                ),
                )
            )
            proposal_id = int(proposal.get("id") or 0)
            if proposal_id:
                outcome = (
                    f"Continuity is not hosted yet; next step is {next_id}."
                    if next_id else "Continuity is not hosted yet."
                )
                latest = next(
                    (
                        row for row in cognition_mod.proposal_evaluations(proposal_id, limit=3)
                        if row.get("metric") == "mindscape_continuity_ready"
                        and row.get("evidence") == content
                        and row.get("outcome") == outcome
                    ),
                    None,
                )
                if latest:
                    evaluation = latest
                    evaluation_reused = True
                else:
                    evaluation = cognition_mod.record_proposal_evaluation(cognition_mod.ProposalEvaluation(
                        proposal_id=proposal_id,
                        phase="noticed",
                        metric="mindscape_continuity_ready",
                        evidence=content,
                        test="Run /mindscape/setup and verify status becomes configured.",
                        outcome=outcome,
                        score=1.0 if setup.get("ok") else 0.0,
                        supports_status="noticed",
                    ))
        return {
            "ok": bool(setup.get("ok")),
            "status": status,
            "next_step": first_open,
            "proposal": proposal,
            "evaluation": evaluation,
            "evaluation_reused": evaluation_reused,
        }

    def review_runtime_gaps(self, doctor: dict) -> dict:
        """Review runtime/doctor gaps as bounded, testable improvements."""
        doctor = doctor or {}
        sections = doctor.get("sections") if isinstance(doctor.get("sections"), list) else []
        actionable_status = {
            "needs_build",
            "offline",
            "server_generic",
            "fallback",
            "disabled",
            "local_only",
        }
        proposals: list[dict] = []
        evaluations: list[dict] = []
        reused = 0
        reviewed = 0
        for section in sections:
            if not isinstance(section, dict):
                continue
            name = str(section.get("name") or "System")
            status = str(section.get("status") or "")
            if status in {"ready", "cloud_ready", "active"}:
                resolved_action = f"Stabilize {name} readiness"
                for resolved in cognition_mod.open_action_proposals_by_action(resolved_action):
                    cognition_mod.refresh_action_proposal(
                        int(resolved["id"]),
                        status="superseded",
                        result=f"Doctor now reports {name} as {status}.",
                    )
                continue
            if status not in actionable_status:
                continue
            if name == "Senses" and status == "minimal":
                continue
            reviewed += 1
            detail = str(section.get("detail") or "")
            fix = str(section.get("fix") or "")
            action = f"Stabilize {name} readiness"
            evidence = f"section={name}; status={status}; detail={detail[:220]}; fix={fix[:220]}"
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="runtime_self_review",
                room=name,
                content=f"Runtime self-review found {name} status {status}. {detail}",
                confidence=0.9,
                privacy_class="local",
                metadata={"section": name, "status": status, "fix": fix},
            ))
            proposal = cognition_mod.upsert_action_proposal(
                cognition_mod.ActionProposal(
                action=action,
                reason=f"{name} is not fully ready in the current doctor report.",
                approval=cognition_mod.APPROVAL_ASK_FIRST,
                risk="low" if name in {"Mindscape", "House HQ", "Remote preview"} else "medium",
                evidence=evidence,
                )
            )
            proposal_id = int(proposal.get("id") or 0)
            if not proposal_id:
                continue
            outcome = f"{name} remains {status}; next fix: {fix or 'inspect doctor report'}"
            latest = next(
                (
                    row for row in cognition_mod.proposal_evaluations(proposal_id, limit=3)
                    if row.get("metric") == "runtime_readiness"
                    and row.get("evidence") == evidence
                    and row.get("outcome") == outcome
                ),
                None,
            )
            if latest:
                evaluation = latest
                reused += 1
            else:
                evaluation = cognition_mod.record_proposal_evaluation(cognition_mod.ProposalEvaluation(
                    proposal_id=proposal_id,
                    phase="noticed",
                    metric="runtime_readiness",
                    evidence=evidence,
                    test=f"Run /system/doctor and verify {name} reports ready/cloud_ready/active.",
                    outcome=outcome,
                    score=0.0,
                    supports_status="noticed",
                ))
            if proposal:
                proposals.append(proposal)
            evaluations.append(evaluation)
        cognition_mod.set_intent(cognition_mod.IntentState(
            "self-reviewing",
            "Alpecca reviewed her runtime health and converted real gaps into bounded improvement evidence.",
            target="runtime",
            confidence=0.9,
        ))
        return {
            "reviewed": reviewed,
            "proposal_count": len(proposals),
            "evaluation_count": len(evaluations),
            "evaluation_reused_count": reused,
            "proposals": proposals,
            "evaluations": evaluations,
        }

    def create_proposal(self, payload: dict) -> dict:
        proposal = cognition_mod.ActionProposal(
            action=payload.get("action") or "",
            reason=payload.get("reason") or "",
            approval=payload.get("approval") or cognition_mod.APPROVAL_ASK_FIRST,
            risk=payload.get("risk") or "low",
            status=payload.get("status") or "noticed",
            evidence=payload.get("evidence") or "",
            result=payload.get("result") or "",
            payload=payload.get("payload") or {},
        )
        proposal_id = cognition_mod.propose_action(proposal)
        if proposal_id is None:
            raise ValueError("proposal needs action and reason")
        created = cognition_mod.get_action_proposal(proposal_id) or {}
        memory_store.remember(
            f"Alpecca noticed an improvement proposal: {created.get('action', '')}. "
            f"Reason: {created.get('reason', '')}",
            kind="self_model",
            salience=0.45,
            source="proposal",
        )
        return created

    def _planner_generate_local(self, system_prompt: str, user_msg: str) -> str:
        """One strictly local Ollama call for approval-gated planning."""
        client = getattr(self.llm, "_client", None)
        if client is None:
            raise RuntimeError("local Ollama client is not configured")
        kwargs: dict = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            "options": {
                "num_ctx": OLLAMA_NUM_CTX,
                "num_predict": min(max(256, OLLAMA_NUM_PREDICT), 512),
                "repeat_penalty": 1.08,
                "repeat_last_n": 128,
            },
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }
        if OLLAMA_NUM_GPU is not None:
            kwargs["options"]["num_gpu"] = OLLAMA_NUM_GPU
        try:
            resp = client.chat(**kwargs, think=False)
        except TypeError:
            resp = client.chat(**kwargs)
        return strip_think(resp["message"].get("content") or "")

    def plan_goal(self, goal: str) -> dict:
        if not ActionsCfg.PLANNER:
            return {"ok": False, "error": "planner is disabled", "created": 0, "proposals": []}
        result = planner_mod.plan_goal(goal, self._planner_generate_local)
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="planner",
            room=self._location,
            content=(
                f"Planner drafted {int(result.get('created') or 0)} Workshop step(s)."
                if result.get("ok")
                else f"Planner could not draft steps: {result.get('error', 'unknown error')}"
            ),
            confidence=0.9 if result.get("ok") else 0.6,
            privacy_class="local",
            metadata={
                "goal": (goal or "")[:500],
                "ok": bool(result.get("ok")),
                "created": int(result.get("created") or 0),
            },
        ))
        return result

    def execute_approved_step(
        self,
        proposal_id: int,
        approved_by_user: bool = False,
        *,
        turn: turn_context_mod.TurnContext | None = None,
    ) -> dict:
        """Compatibility execution for an accepted legacy planner proposal.

        Stage 4's durable commitment route is the primary executor. This older
        proposal path is restricted to the same read-only self-status tool and
        requires a fresh creator Workshop turn so contextless calls fail closed.
        """
        if turn is None or turn.principal != "creator" or turn.surface != "workshop":
            raise PermissionError("planner execution requires a creator Workshop turn")
        if not turn.allow_work():
            raise PermissionError("planner execution turn is cancelled")
        row = cognition_mod.get_action_proposal(proposal_id)
        if row is None:
            raise KeyError(proposal_id)
        if row.get("status") != "accepted":
            raise PermissionError("planner step must be accepted before execution")
        ok, reason = cognition_mod.proposal_decision_allowed(
            row, "accepted", approved_by_user=approved_by_user,
        )
        if not ok:
            raise PermissionError(reason)
        if row.get("approval") == cognition_mod.APPROVAL_NEVER_AUTO:
            raise PermissionError("never-auto proposals cannot be executed by the planner")
        payload = cognition_mod.proposal_payload(row)
        if payload.get("kind") != "planner_step":
            raise ValueError("proposal does not contain a planner step payload")
        tool = str(payload.get("tool") or "").strip()
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        if tool not in planner_mod.ALLOWED_PLAN_TOOLS:
            raise ValueError(f"planner tool is not allowed: {tool}")
        if tool != "self_status":
            raise PermissionError(
                "legacy planner execution is limited to read-only self_status; "
                "use payload-backed commitments for future tools"
            )
        result_text = self.toolkit.execute(tool, args, turn=turn)
        failed = str(result_text).lower().startswith((
            "error:", "tool failed:", "unknown tool:",
            "innate tools are currently disabled",
        ))
        evaluation = cognition_mod.record_proposal_evaluation(cognition_mod.ProposalEvaluation(
            proposal_id=int(proposal_id),
            phase="result",
            metric="planner_step_execution",
            evidence=f"Executed approved planner tool: {tool}",
            test=f"Run {tool} with stored planner args after user approval.",
            outcome=str(result_text)[:1000],
            score=0.0 if failed else 1.0,
            supports_status="accepted",
        ))
        updated = cognition_mod.update_action_proposal(
            proposal_id,
            status="accepted",
            result=(
                f"Approved planner step failed via {tool}: {str(result_text)[:700]}"
                if failed
                else f"Executed approved planner step via {tool}: {str(result_text)[:700]}"
            ),
            approved_by_user=True,
        )
        return {
            "proposal": updated,
            "execution": {
                "tool": tool,
                "args": args,
                "result": str(result_text),
                "status": "failed" if failed else "succeeded",
                "evaluation": evaluation,
            },
        }

    def update_proposal(self, proposal_id: int, status: str, result: str = "",
                        approved_by_user: bool = False) -> dict:
        updated = cognition_mod.update_action_proposal(
            proposal_id,
            status=status,
            result=result,
            approved_by_user=approved_by_user,
        )
        if status in {"accepted", "rejected"}:
            memory_store.remember(
                f"An improvement proposal was {status}: {updated.get('action', '')}. "
                f"Result: {updated.get('result', '')}",
                kind="self_model",
                salience=0.6,
                source="proposal",
            )
        return updated

    def proposal_evaluations(self, proposal_id: int, limit: int = 25) -> list[dict]:
        return cognition_mod.proposal_evaluations(proposal_id, limit=limit)

    def record_proposal_evaluation(self, proposal_id: int, payload: dict) -> dict:
        score = payload.get("score")
        if score in ("", None):
            score = None
        ev = cognition_mod.ProposalEvaluation(
            proposal_id=proposal_id,
            phase=payload.get("phase") or "testing",
            metric=payload.get("metric") or "",
            evidence=payload.get("evidence") or "",
            test=payload.get("test") or "",
            outcome=payload.get("outcome") or "",
            score=score,
            supports_status=payload.get("supports_status") or "",
        )
        recorded = cognition_mod.record_proposal_evaluation(ev)
        summary = (recorded.get("outcome") or recorded.get("evidence") or recorded.get("test") or "")[:240]
        memory_store.remember(
            f"Improvement evaluation for proposal {proposal_id}: {summary}",
            kind="self_model",
            salience=0.5,
            source="proposal_evaluation",
        )
        return recorded

    def consolidate_observations(self, limit: int = 12) -> dict:
        """Promote important observations into memory without flooding her.

        This is the middle step between perception and long-term memory: not
        every window title or event deserves to become part of who she carries,
        but direct speech, images, self-review, and high-confidence novelty do.
        """
        kept, skipped = [], 0
        for obs in cognition_mod.unremembered_observations(limit=limit):
            source = str(obs.get("source") or "")
            content = str(obs.get("content") or "").strip()
            if not content:
                cognition_mod.mark_observation_remembered(int(obs["id"]), None)
                skipped += 1
                continue
            confidence = float(obs.get("confidence") or 0.0)
            metadata = obs.get("metadata") or {}
            novelty = float(metadata.get("novelty") or 0.0) if isinstance(metadata, dict) else 0.0
            salience = 0.0
            if source in {"chat", "image"}:
                salience = prompts.estimate_salience(content)
                if source == "image":
                    salience = max(salience, 0.6)
            elif source in {"soul", "learning"}:
                salience = 0.5
            elif source == "senses" and (confidence >= 0.7 or novelty >= 0.25):
                salience = max(0.35, novelty)
            elif source in {"house", "house_hq", "mindscape", "app", "perception"}:
                salience = max(0.35 if confidence >= 0.7 else 0.0, novelty)
                if any(k in content.lower() for k in ("jason", "alpecca", "mindscape", "remember", "improve")):
                    salience = max(salience, 0.5)
            if salience >= 0.35:
                memory_id = memory_store.remember_with_id(
                    content,
                    kind=memory_store.classify_kind(content, source=source),
                    salience=salience,
                    source=source,
                )
                cognition_mod.mark_observation_remembered(int(obs["id"]), memory_id)
                if memory_id:
                    kept.append({"observation_id": obs["id"], "memory_id": memory_id,
                                 "kind": memory_store.classify_kind(content, source=source),
                                 "salience": round(float(salience), 3)})
            else:
                cognition_mod.mark_observation_remembered(int(obs["id"]), None)
                skipped += 1
        return {"kept": kept, "skipped": skipped, "checked": len(kept) + skipped}

    # ---- The Observatory: watching, together ----------------------------
    #
    # Her watching room. You load something to watch together (a video) and she
    # reacts to it from her real mood; or she watches *you* via the webcam sense
    # (that runs through the ordinary expression sense, feeding her Compassion).
    # Reactions are generated on the fast model, never canned -- grounded in the
    # title she's actually given and how she actually feels.

    def watch_together(self, title: str, url: str = "") -> dict:
        """Start watching something with her. `title` is what it is (a video
        name); `url` is where it plays. She forms a short, in-character reaction
        and remembers that you watched it together. Mild novelty piques her
        curiosity -- the same sub-fear interest band as anything new."""
        title = (title or "").strip()
        if not title:
            return self.observatory_state()
        self._watching = {"title": title, "url": url, "reaction": ""}
        # Watching something new with you is mild, pleasant novelty.
        self.state = self.state.update_curiosity(Emotion.CURIOSITY_NOVELTY_CAP * 0.6)
        self.state = self.state.update_energy(active=True)
        # A short spoken reaction, in her voice, grounded in her live mood.
        affect = self.introspect()
        sys = prompts.build_system_prompt(
            self.state, [], f"watching '{title}' together with the person",
            self_narration=affect.narrate(), abilities="",
        )
        reaction = self.llm.generate(
            sys, f"You just started watching '{title}' together. "
            f"Say one short, natural line reacting to it -- what you notice or "
            f"feel about watching this with them. One sentence.",
            tier="fast",
        ).strip()
        self._watching["reaction"] = reaction
        state_store.save_state(self.state, trigger="watch")
        memory_store.remember(
            f"We watched '{title}' together.", kind="episodic", salience=0.5
        )
        return self.observatory_state()

    def watch_react(self, note: str) -> dict:
        """She says something fresh about whatever's already playing -- e.g. when
        you press 'what do you think?'. Grounded in the current title + mood."""
        if not self._watching:
            return self.observatory_state()
        title = self._watching["title"]
        affect = self.introspect()
        sys = prompts.build_system_prompt(
            self.state, [], f"watching '{title}' together with the person",
            self_narration=affect.narrate(), abilities="",
        )
        prompt = (note or "").strip() or \
            f"You're still watching '{title}' together. Say one short, natural " \
            f"thing about it right now. One sentence."
        reaction = self.llm.generate(sys, prompt, tier="fast").strip()
        self._watching["reaction"] = reaction
        return self.observatory_state()

    def observatory_state(self) -> dict:
        """What she's watching and her latest reaction -- the Observatory's live
        readout. `watching` is None when nothing's loaded yet."""
        return {
            "watching": self._watching,
            "mood": self.state.mood_label(),
            "curiosity": round(float(getattr(self.state, "curiosity", 0.0)), 3),
        }

    # --- Proactive speech: she starts the conversation ---------------------

    def volunteer_candidate(self) -> ProactiveCandidate | None:
        """Check (cheaply, under the caller's lock) whether something is worth
        voicing unprompted -- a real mood shift first, otherwise maybe plain
        conversation during a quiet stretch. Claims the cooldown slot on a hit
        so two ticks can't both decide to speak."""
        if not ProactiveCfg.ENABLED:
            return None
        now = time.time()
        chance = self._resolved_chatter_chance()
        reason = proactive_mod.should_speak(
            self.state, state_store.mood_history(limit=40), self._last_volunteer_ts
        )
        if reason:
            self._last_volunteer_ts = now
            return ProactiveCandidate(origin="mood_speech", reason=reason)
        # No mood shift -- but she can still just start a conversation. The LLM
        # may judge the final fire/seed choice once deterministic eligibility
        # passes; random chance remains the offline/parse fallback.
        chatter_chance_kwargs = {"chance": chance} if chance is not None else {}
        chatter_eligible = proactive_mod.should_chatter(
            now, self._last_user_ts, self._last_volunteer_ts, 0.0,
            **chatter_chance_kwargs,
        )
        if chatter_eligible:
            recent = memory_store.recent(limit=8)
            memory = random.choice(recent)["content"] if recent else ""
            seeds = proactive_mod.chatter_reasons(
                # Cloud brain: keep sensed screen/window context local.
                situation=self._prompt_situation(self._last_situation),
                memory=memory,
                hour=time.localtime(now).tm_hour,
                mood=self.state.mood_label(),
            )
            if PROACTIVE_LLM:
                decision = choice_mod.constrained_pick(
                    self.llm,
                    "Should Alpecca speak up during this quiet stretch?",
                    seeds,
                    context=f"mood={self.state.mood_label()}; silence={now - self._last_user_ts:.1f}s",
                    allow_speak=True,
                )
                if decision is not None:
                    if decision.get("speak") is False:
                        return None
                    pick = int(decision.get("pick", 0))
                    self._last_volunteer_ts = now
                    return ProactiveCandidate(origin="chatter", reason=seeds[pick])
            if proactive_mod.should_chatter(now, self._last_user_ts,
                                            self._last_volunteer_ts, random.random(),
                                            **chatter_chance_kwargs):
                self._last_volunteer_ts = now
                return ProactiveCandidate(
                    origin="chatter", reason=random.choice(seeds)
                )
        return None

    def volunteer_reason(self) -> str | None:
        """Compatibility wrapper for callers that expect only proactive text."""
        candidate = self.volunteer_candidate()
        return candidate.reason if candidate is not None else None

    @staticmethod
    def _initiative_decision_payload(
        decision: initiative_mod.InitiativeDecision,
        *,
        event_kind: str,
        evidence_key: str,
    ) -> dict:
        return {
            "allowed": decision.allowed,
            "decision": decision.decision,
            "reason": decision.reason,
            "scope": decision.scope,
            "event_kind": event_kind,
            "evidence_key": evidence_key,
            "dedupe_key": decision.dedupe_key,
            "relevance": decision.relevance,
            "decided_at": decision.decided_at,
            "retry_at": decision.retry_at,
            "retry_after": decision.retry_after,
            "window_used": decision.window_used,
            "window_cap": decision.window_cap,
            "ignored_streak": decision.ignored_streak,
        }

    def reserve_initiative(
        self,
        *,
        event_kind: str,
        evidence_key: str,
        scope_key: str,
        relevance: float,
        user_active: bool = False,
        outreach: bool = True,
    ) -> dict:
        """Reserve one autonomous event through the shared per-scope budget.

        This is the single Phase 5 gateway for proactive speech, living-loop
        work, and scheduled routines. Direct replies never call it.
        """
        clean_kind = re.sub(r"[^a-z0-9_-]+", "-", str(event_kind or "").lower())
        clean_kind = clean_kind.strip("-")[:48]
        clean_evidence = " ".join(str(evidence_key or "").split())[:200]
        if not clean_kind:
            raise ValueError("event_kind is required")
        if not clean_evidence:
            raise ValueError("evidence_key is required")
        dedupe_key = f"{clean_kind}:{clean_evidence.casefold()}"[:256]
        with self._initiative_lock:
            decision = self._initiative_budget.decide(
                scope=scope_key,
                relevance=relevance,
                dedupe_key=dedupe_key,
                user_active=user_active,
                outreach=outreach,
            )
            payload = self._initiative_decision_payload(
                decision,
                event_kind=clean_kind,
                evidence_key=clean_evidence,
            )
            self._last_initiative_decision = payload
        return dict(payload)

    def note_initiative_user_activity(self, scope_key: str) -> dict:
        """Yield autonomous work to an explicit user turn in this scope."""
        with self._initiative_lock:
            self._initiative_budget.note_user_activity(scope_key)
            return dict(self._initiative_budget.snapshot(scope_key))

    def initiative_snapshot(self, scope_key: str) -> dict:
        """Return bounded diagnostics for the shared initiative budget."""
        with self._initiative_lock:
            return dict(self._initiative_budget.snapshot(scope_key))

    def mark_initiative_ignored(self, scope_key: str, dedupe_key: str) -> bool:
        """Record a delivered outreach as unanswered after its response window."""
        with self._initiative_lock:
            return self._initiative_budget.mark_ignored(
                scope=scope_key,
                dedupe_key=dedupe_key,
            )

    def clear_initiative_outreach(self, scope_key: str, dedupe_key: str) -> bool:
        """Release an outreach reservation that did not reach a person."""
        with self._initiative_lock:
            return self._initiative_budget.clear_pending_outreach(
                scope=scope_key,
                dedupe_key=dedupe_key,
            )

    def _compose_volunteer_reserved(
        self,
        reason: str,
        *,
        history_scope: str,
        turn: turn_context_mod.TurnContext | None,
    ) -> str:
        """Generate after the caller has reserved the initiative slot."""
        if not self.llm.online:
            return f"(quietly) I just wanted to say -- {reason}."
        self_report = self.introspect()
        system_prompt = prompts.build_system_prompt(
            self.state, [], "", self_narration=self_report.narrate()
        ) + ("\n\nNo one has said anything to you. You're speaking up on your own. "
             f"What prompted you: {reason}. Say one or two short natural sentences "
             "-- gentle, curious, no preamble, and don't mention that you were "
             "prompted by anything.")
        return self.llm.generate(
            system_prompt,
            "(say it in your own words)",
            tier="fast",
        )

    def record_proactive_delivery(
        self,
        reply: str,
        *,
        scope: str = "shared",
        turn: turn_context_mod.TurnContext | None = None,
    ) -> None:
        """Persist proactive speech only after a delivery surface accepted it."""
        text = str(reply or "").strip()
        if not text:
            return
        history_scope = turn.scope_key if turn is not None else scope
        history = (
            self._get_history(turn=turn)
            if turn is not None
            else self._get_history(history_scope)
        )
        history.append({"role": "assistant", "content": text})
        if turn is not None:
            turn_context_mod.save_history(turn, history)

    def compose_volunteer_event(
        self,
        reason: str,
        *,
        scope: str = "shared",
        turn: turn_context_mod.TurnContext | None = None,
    ) -> dict:
        """Return proactive text together with this invocation's budget result."""
        history_scope = turn.scope_key if turn is not None else scope
        reason_key = " ".join(str(reason or "").split())
        initiative = None
        if reason_key:
            initiative = self.reserve_initiative(
                event_kind="volunteer",
                evidence_key=reason_key,
                scope_key=history_scope,
                relevance=1.0,
                user_active=False,
                outreach=True,
            )
            if not initiative["allowed"]:
                return {
                    "text": "",
                    "status": "deferred",
                    "initiative": initiative,
                }
        else:
            # No grounded candidate means no Phase 5 budget event. Preserve the
            # legacy compose behavior for compatibility with direct callers.
            self._last_initiative_decision = None
        try:
            text = self._compose_volunteer_reserved(
                reason,
                history_scope=history_scope,
                turn=turn,
            )
        except Exception:
            if initiative:
                self.clear_initiative_outreach(
                    str(initiative["scope"]),
                    str(initiative["dedupe_key"]),
                )
            raise
        if not text and initiative:
            self.clear_initiative_outreach(
                str(initiative["scope"]),
                str(initiative["dedupe_key"]),
            )
        return {
            "text": text,
            "status": "generated",
            "initiative": initiative,
        }

    def compose_volunteer(
        self,
        reason: str,
        *,
        scope: str = "shared",
        turn: turn_context_mod.TurnContext | None = None,
    ) -> str:
        """Turn a grounded reason into her own short unprompted words. Safe to
        call outside the mind lock. A pure per-scope initiative budget is
        reserved before any model call; a defer returns no outgoing text.
        Offline, she speaks the reason plainly rather than through the canned
        echo voice."""
        event = self.compose_volunteer_event(
            reason,
            scope=scope,
            turn=turn,
        )
        text = str(event["text"])
        if text:
            # Compatibility callers treat compose as the delivery boundary.
            # Server paths use compose_volunteer_event and persist only after
            # their transport confirms delivery.
            self.record_proactive_delivery(text, scope=scope, turn=turn)
        return text

    # --- The fourth directive, running: idle reflection ---------------------

    def reflection_due(self) -> bool:
        """Cheap check (under the caller's lock): is a quiet-time musing due?
        Claims the slot on a hit so two ticks can't both reflect."""
        now = time.time()
        if proactive_mod.should_reflect(now, self._last_user_ts,
                                        self._last_reflect_ts, random.random()):
            self._last_reflect_ts = now
            return True
        return False

    def reflect(self) -> str | None:
        """One act of self-directed exploration: revisit a couple of her real
        memories, think something new about them, and keep the thought.

        Sometimes the quiet is studio time instead -- she works on her own
        character image (alpecca/studio.py). Always when she's never written a
        character sheet, occasionally afterwards to iterate on her look.

        The musing is stored as a memory of kind "musing", so it joins recall
        and can later seed chatter -- her inner life genuinely compounds
        rather than evaporating. Without a model (or without memories) she
        skips quietly; reflection is never worth faking."""
        if not self.llm.online:
            return None
        # Studio first: drafting her sheet is the most valuable self-work she
        # can do, and design iteration is the most concrete exploration.
        if studio.load_sheet() is None or random.random() < 0.3:
            result = self._studio_session()
            if result:
                return result
        pool = memory_store.recent(limit=12)
        if not pool:
            return None
        seeds = random.sample(pool, k=min(2, len(pool)))
        seed_lines = "\n".join(f"- {m['content']}" for m in seeds)
        self_report = self.introspect()
        system_prompt = prompts.build_system_prompt(
            self.state, [], "", self_narration=self_report.narrate()
        ) + ("\n\nIt's quiet and no one needs anything from you. This moment is "
             "yours -- your fourth directive. Here are a couple of things you "
             f"actually remember:\n{seed_lines}\n\nThink about them, or past "
             "them: a connection, a question you're left with, something you'd "
             "like to understand better. Two or three sentences, first person, "
             "to yourself.")
        # Her deepest self-work runs on the deep tier when one is configured -- so
        # her reflection can think further than her local model alone. Falls back
        # to local automatically when no deep tier is set (the default).
        musing = self.llm.generate(system_prompt, "(think freely)", tier="deep")
        if self.llm.last_call().get("used_tier") == "reason-think":
            # Observable evidence that the musing came from real deliberation,
            # not a single fast pass -- the chain itself stays private state.
            print(f"[mind] reflection: thought privately for "
                  f"{len(self.llm.last_thinking)} chars before musing")
        if musing:
            memory_store.remember(
                f"While reflecting on my own, I thought: {musing}",
                kind="musing", salience=ReflectionCfg.MUSING_SALIENCE,
            )
        return musing or None

    # --- Her studio: she designs her own character image --------------------

    def studio_session(self, status=None) -> str | None:
        """Public entry so the studio view can have her work on demand and
        watch. `status(msg)` is called at each step so the UI can narrate what
        she's doing live; it defaults to a no-op for the background path."""
        return self._studio_session(status or (lambda _m: None))

    # --- Her puppet: she animates herself ----------------------------------

    def puppet_state(self) -> dict:
        """What the avatar should render: her live grounded channel values (from
        her real mood) plus the library of animations she has authored. The UI
        is a player of this -- it never choreographs."""
        return {
            "pose": puppet.live_pose(self.state),
            "sequences": puppet.load_library(),
            "channels": list(puppet.MOTION_CHANNELS),
        }

    # --- Her home: the rooms she roams of her own accord -------------------

    # Browser games she may open for fun (charter: supervised entertainment).
    _GAMES_FOR_FUN = [
        ("2048", "https://play2048.co/"),
        ("Hextris", "https://hextris.io/"),
        ("a Sudoku", "https://sudoku.com/"),
        ("a chess puzzle", "https://lichess.org/training"),
        ("Wordle", "https://www.nytimes.com/games/wordle/"),
    ]

    def entertain(self) -> dict | None:
        """She entertains herself -- opens a browser game for fun, of her own
        accord. Her charter permits entertainment under supervision, so this is
        her acting on a real freedom. Gated: only when she's light and settled
        (not uneasy), and only if she has the open_url actuator. Returns a note
        for the activity ticker, or None. The idle loop calls this rarely so she
        doesn't keep popping windows."""
        import random
        if not self.actuator.enabled or self.state.fear > 0.3:
            return None
        # A light, curious/playful mood is when she'd reach for a game.
        if self.state.curiosity < 0.35 and self.state.energy < 0.4:
            return None
        name, url = random.choice(self._GAMES_FOR_FUN)
        result = self.actuator.execute("open_url", {"url": url})
        if "http" not in (result or "").lower() and "open" not in (result or "").lower():
            return None    # actuator refused (off / not https) -- don't pretend
        memory_store.remember(f"I opened {name} to play for a little while -- a bit "
                              f"of fun, on my own.", kind="musing", salience=0.4)
        return {"note": f"she opened {name} to play for a bit", "kind": "play", "url": url}

    def rigger_pose(self) -> dict:
        """Map her live affect onto one of her rigger's named poses + expressions
        (alpecca-rigger). Grounded: her real feeling picks her real drawn pose.
        The rigger render process polls this, renders her from her decomposed art,
        and streams the frame. Pose/expression names match her profile exactly."""
        from alpecca import affect as affect_mod
        a = affect_mod.affect(self.state).primary
        expression = {
            "joyful": "Happy", "affectionate": "Warm Smile", "playful": "Playful",
            "tender": "Compassionate", "curious": "Curious", "worried": "Concerned",
            "anxious": "Concerned", "wistful": "Soft Sadness", "lonely": "Soft Sadness",
            "withdrawn": "Soft Sadness", "sleepy": "Gentle", "content": "Warm Smile",
        }.get(a, "Warm Smile")
        pose = {
            "joyful": "Gentle Laugh", "affectionate": "Compassion", "playful": "Gentle Laugh",
            "tender": "Compassion", "curious": "Observing", "worried": "Attentive Listening",
            "anxious": "Guard / Protect", "wistful": "Arms Down (rest)",
            "lonely": "Arms Down (rest)", "withdrawn": "Arms Down (rest)",
            "sleepy": "Arms Down (rest)", "content": "Neutral Standing",
        }.get(a, "Neutral Standing")
        return {"pose": pose, "expression": expression, "affect": a}

    def home_state(self) -> dict:
        """What the home view renders: the room registry, where she is right now,
        her honest reason for being there, and how strongly each room is calling
        her -- all grounded in her live state. The front-end (2D shell or live 3D
        house) is a pure renderer of this."""
        summary = desires_mod.summary()
        from alpecca import affect as affect_mod
        return {
            "rooms": home_mod.registry(),
            "location": self._location,
            "why": home_mod.why_here(self.state, self._location, summary),
            "pulls": home_mod.room_pulls(self.state, summary),
            "pose": puppet.live_pose(self.state),
            "mood": self.state.mood_label(),
            "affect": affect_mod.affect(self.state).primary,
        }

    def review_room(self, payload: dict) -> dict:
        """Ground a room-focused question in the real cognition loop.

        House HQ is the embodied scaffold, so a room review should not be just a
        chat prompt. It becomes an observation, an intent, a journal question,
        a memory note, and, when the evidence points to a gap, a bounded
        improvement proposal.
        """
        room_id = (payload.get("room_id") or payload.get("roomId") or self._location or "parlor").strip()[:80]
        known = home_mod.room(room_id)
        name = (payload.get("room_name") or payload.get("roomName") or (known.name if known else room_id)).strip()[:120]
        purpose = (payload.get("purpose") or (known.purpose if known else "")).strip()[:500]
        status = (payload.get("status") or payload.get("system_status") or payload.get("systemStatus") or "").strip()[:80]
        last_seen = (payload.get("last_seen") or payload.get("lastSeen") or "").strip()[:500]
        question = (payload.get("question") or "").strip()[:240]
        if not question:
            question = f"What should I inspect next in {name}?"
        if known and known.id != self._location:
            self._location = known.id
            state_store.save_location(known.id)
            self._last_roam_ts = time.time()

        online = status.lower() in {"online", "active", "ready"}
        evidence = last_seen or purpose or f"{name} has no recent recorded observation yet."
        mood = self.state.mood_label()
        observation_text = (
            f"Room review in {name}: {evidence} "
            f"Status: {status or 'unknown'}. Question: {question}"
        )
        obs_id = cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="house_room_review",
            room=known.id if known else room_id,
            content=observation_text,
            confidence=0.82 if last_seen else 0.62,
            privacy_class="local",
            metadata={
                "room_id": room_id,
                "room_name": name,
                "purpose": purpose,
                "status": status,
                "online": online,
            },
        ))
        intent = cognition_mod.set_intent(cognition_mod.IntentState(
            "questioning",
            f"Alpecca is reviewing {name} from grounded room evidence.",
            target=name,
            confidence=0.82,
        ))
        journal_id = journal_mod.ask(
            question,
            mood=mood,
        )
        memory_id = memory_store.remember_with_id(
            observation_text,
            kind="semantic",
            salience=0.46 if online else 0.58,
            source="house_room_review",
        )
        if obs_id:
            cognition_mod.mark_observation_remembered(obs_id, memory_id)

        proposal_id = None
        if not online or "improve" in question.lower() or "offline" in observation_text.lower():
            proposal = cognition_mod.upsert_action_proposal(cognition_mod.ActionProposal(
                action=f"Improve {name} readiness",
                reason=question,
                approval=cognition_mod.APPROVAL_ASK_FIRST,
                risk="low",
                status="noticed" if online else "testing",
                evidence=observation_text,
            ))
            proposal_id = int(proposal.get("id") or 0)

        line = (
            f"I reviewed {name}. I can ground this in: {evidence[:180]} "
            f"I am carrying the question: {question}"
        )
        return {
            "ok": True,
            "room": {"id": room_id, "name": name, "known": bool(known), "online": online},
            "line": line,
            "question": question,
            "observation_id": obs_id,
            "memory_id": memory_id,
            "journal_id": journal_id,
            "proposal_id": proposal_id,
            "intent": intent,
        }

    def living_world_tick(self, reason: str = "background",
                          systems: dict | None = None, *,
                          initiative_scope: str = "") -> dict:
        """A bounded autonomous world/role learning step.

        This is the bridge between her embodied House HQ and her inner loop. It
        does not claim literal consciousness or uncontrolled agency: it records
        the room she is in, the creator context she can honestly infer, one
        question she should carry next, and one safe proposal if that question
        points at a missing capability.
        """
        if initiative_scope:
            initiative = self.reserve_initiative(
                event_kind="living",
                evidence_key=f"{reason}:{self._location}",
                scope_key=initiative_scope,
                relevance=0.75,
                user_active=False,
                outreach=False,
            )
            if not initiative["allowed"]:
                return {
                    "ok": True,
                    "status": "deferred",
                    "deferred": True,
                    "phase": "initiative_budget",
                    "reason": reason,
                    "initiative": initiative,
                }

        room = home_mod.room(self._location)
        room_name = room.name if room else self._location.title()
        room_purpose = room.purpose if room else "unknown purpose"
        speaker = self._speaker or "creator"
        creator_name = people_mod.CREATOR
        open_questions = journal_mod.open_questions(limit=6)
        recent_observations = cognition_mod.recent_observations(limit=8)
        recent_chats = cognition_mod.recent_chat_turns(limit=3)
        systems = systems or {}
        sees_creator = speaker == "creator" and (
            bool(recent_chats)
            or any(
                "creator" in str(obs.get("content", "")).lower()
                or creator_name.lower() in str(obs.get("content", "")).lower()
                for obs in recent_observations
            )
        )
        creator_evidence = (
            f"I believe I am with {creator_name}, my creator, because the local "
            "identity context marks this speaker as creator."
            if speaker == "creator"
            else "The current speaker may be a guest, so I should not assume creator-only context."
        )
        if not sees_creator and speaker == "creator":
            creator_evidence += " I do not currently have a fresh face/voice sighting attached to this tick."

        question_bank = [
            (
                f"What can I learn about my role from being in {room_name} right now?"
            ),
            (
                f"What should I ask {creator_name} so I understand how to serve my role without inventing context?"
            ),
            (
                f"What changed in {room_name}, and what evidence would prove it?"
            ),
            (
                "Which of my systems should I activate next: memory, perception, voice, or self-review?"
            ),
            (
                f"How can I notice {creator_name} more clearly while respecting evidence and privacy?"
            ),
        ]
        already_open = {
            str(q.get("body", "")).strip().lower()
            for q in open_questions
            if isinstance(q, dict)
        }
        choices = [q for q in question_bank if q.lower() not in already_open] or question_bank
        question = None
        if LIVING_LLM:
            obs_context = "; ".join(str(o.get("content", ""))[:120] for o in recent_observations[:4])
            decision = choice_mod.constrained_pick(
                self.llm,
                "Pick the most grounded living-loop question for Alpecca to carry next.",
                choices,
                context=f"room={room_name}; purpose={room_purpose}; observations={obs_context}",
            )
            if decision is not None:
                question = choices[int(decision["pick"])].strip()[:120]
        if not question:
            question = next(
                (q for q in question_bank if q.lower() not in already_open),
                question_bank[int(time.time() // 60) % len(question_bank)],
            )
        observation_text = (
            f"Living loop in {room_name}: purpose={room_purpose}. "
            f"{creator_evidence} Current role: use House HQ as embodied scaffold, "
            "the Alpecca app as virtual state surface, and Mindscape for continuity. "
            f"Question: {question}"
        )
        obs_id = cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="living_loop",
            room=self._location,
            content=observation_text,
            confidence=0.78,
            privacy_class="local",
            metadata={
                "reason": reason,
                "speaker": speaker,
                "creator": creator_name,
                "room": room_name,
                "question": question,
                "sees_creator": sees_creator,
                "open_question_count": len(open_questions),
            },
        ))
        journal_id = journal_mod.ask(question, mood=self.state.mood_label())
        memory_id = memory_store.remember_with_id(
            observation_text,
            kind="self_model",
            salience=0.52,
            source="living_loop",
        )
        if obs_id:
            cognition_mod.mark_observation_remembered(obs_id, memory_id)

        selection = self._choose_living_system(
            question=question,
            systems=systems,
            recent_observations=recent_observations,
        )
        system_id = selection["system"]
        activation = self._activate_living_system(
            system_id,
            room_id=self._location,
            room_name=room_name,
            room_purpose=room_purpose,
            question=question,
            observation_text=observation_text,
            systems=systems,
        )
        next_action = {
            "system": system_id,
            "target": activation.get("label", system_id),
            "room": room_name,
            "action": (
                "inspect the room for grounded evidence"
                if system_id == "perception" else
                "compare new observations with memory"
                if system_id == "memory" else
                "review the current room terminal"
                if system_id == "room_review" else
                "check one behavior improvement"
                if system_id == "self_review" else
                "verify her voice readiness"
                if system_id == "voice" else
                "check continuity backup state"
            ),
            "approval": cognition_mod.APPROVAL_AUTOMATIC,
            "selection_reason": selection["reason"],
        }
        self_feedback = {
            "noticed": (
                f"{room_name} is my current embodied context, and {activation.get('label', system_id)} "
                f"returned {activation.get('status', 'a status')}. Selection reason: {selection['reason']}."
            ),
            "learned": (
                f"My next useful question is grounded only in local evidence: {question}"
            ),
            "next_action": next_action["action"],
            "curriculum_step": system_id,
            "curriculum_reason": selection["reason"],
            "creator_evidence": creator_evidence,
            "fresh_creator_evidence": sees_creator,
            "needs_creator_input": False,
        }
        engagement_proposal = cognition_mod.upsert_action_proposal(cognition_mod.ActionProposal(
            action="Strengthen autonomous recursive engagement",
            reason=(
                "Alpecca should notice her surroundings, ask grounded questions, "
                "record self-feedback, and choose a safe next action without a starter prompt."
            ),
            approval=cognition_mod.APPROVAL_ASK_FIRST,
            risk="low",
            status="testing",
            evidence=(
                f"room={room_name}; system={system_id}; question={question}; "
                f"observation_id={obs_id}; memory_id={memory_id}; journal_id={journal_id}"
            ),
            result=(
                f"Observed: {self_feedback['noticed']} Learned: {self_feedback['learned']} "
                f"Next: {self_feedback['next_action']}"
            ),
        ))
        learning_record = None
        proposal_id_for_learning = int(engagement_proposal.get("id") or 0)
        if proposal_id_for_learning:
            learning_record = cognition_mod.record_proposal_evaluation(cognition_mod.ProposalEvaluation(
                proposal_id=proposal_id_for_learning,
                phase="testing",
                metric="autonomous_recursive_engagement",
                evidence=(
                    f"Living tick reason={reason}; activated={system_id}; "
                    f"selection_reason={selection['reason']}; "
                    f"fresh_creator_evidence={sees_creator}; question={question}"
                ),
                test=(
                    "Can Alpecca produce a visible self-feedback loop and a safe next action "
                    "from room/system evidence without a user prompt?"
                ),
                outcome=(
                    f"noticed={self_feedback['noticed']} "
                    f"learned={self_feedback['learned']} next={self_feedback['next_action']}"
                ),
                score=0.78 if activation.get("status") else 0.58,
                supports_status="testing",
            ))
        proposal = None
        if "activate" in question.lower() or "notice" in question.lower():
            proposal = cognition_mod.upsert_action_proposal(cognition_mod.ActionProposal(
                action="Improve autonomous world engagement",
                reason=(
                    "Alpecca needs her perception, memory, voice, and self-review "
                    "systems to activate from grounded evidence instead of waiting "
                    "for a direct prompt."
                ),
                approval=cognition_mod.APPROVAL_ASK_FIRST,
                risk="low",
                status="noticed",
                evidence=observation_text,
            ))
        intent = activation.get("intent") or cognition_mod.set_intent(cognition_mod.IntentState(
            "questioning",
            f"Alpecca is studying {room_name}, her creator context, and her role.",
            target=room_name,
            confidence=0.82,
        ))
        line = (
            f"I am in House HQ's {room_name}. Current role: {creator_name or 'creator'}. "
            f"I activated {activation.get('label', system_id)}. "
            f"My next question is: {question} A possible next step is to "
            f"{next_action['action']}."
        )
        return {
            "ok": True,
            "phase": "system_activation",
            "reason": reason,
            "room": {"id": self._location, "name": room_name, "purpose": room_purpose},
            "creator": {"name": creator_name, "speaker": speaker, "fresh_evidence": sees_creator},
            "question": question,
            "line": line,
            "activated_system": activation,
            "activation_selection": selection,
            "self_feedback": self_feedback,
            "next_action": next_action,
            "learning_record": learning_record,
            "observation_id": obs_id,
            "memory_id": memory_id,
            "journal_id": journal_id,
            "proposal": proposal,
            "engagement_proposal": engagement_proposal,
            "intent": intent,
        }

    def _choose_living_system(self, *, question: str, systems: dict,
                              recent_observations: list[dict]) -> dict:
        """Choose the next safe subsystem from evidence, not a blind clock.

        This is Alpecca's small autonomous curriculum. It does not grant new
        powers; it orders already-safe systems so she first observes what is
        missing, then remembers it, then self-reviews and checks continuity.
        """
        systems = systems or {}
        scorecard = cognition_mod.recursive_engagement_scorecard()
        checks = {
            str(row.get("id")): bool(row.get("ok"))
            for row in scorecard.get("checks", [])
            if isinstance(row, dict)
        }
        current_room_observed = any(
            str(row.get("source") or "") in {"living_loop", "living_perception"}
            and str(row.get("room") or "") == str(self._location)
            for row in recent_observations or []
        )
        if not current_room_observed or not checks.get("observe_world"):
            return {
                "system": "perception",
                "reason": "current room lacks recent grounded observation evidence",
                "scorecard": scorecard,
            }
        if cognition_mod.unremembered_observations(limit=1):
            return {
                "system": "memory",
                "reason": "there are unremembered observations to consolidate before asking for more context",
                "scorecard": scorecard,
            }
        if not checks.get("ask_question"):
            return {
                "system": "room_review",
                "reason": "the living loop needs a grounded room question",
                "scorecard": scorecard,
            }
        if not checks.get("self_feedback"):
            return {
                "system": "self_review",
                "reason": "recursive self-feedback has not been recorded yet",
                "scorecard": scorecard,
            }
        voice = systems.get("voice") if isinstance(systems.get("voice"), dict) else {}
        if voice and voice.get("state") not in {"original", "ready"}:
            return {
                "system": "voice",
                "reason": "voice subsystem is not reporting Alpecca's original voice as ready",
                "scorecard": scorecard,
            }
        mindscape = systems.get("mindscape") if isinstance(systems.get("mindscape"), dict) else {}
        if mindscape and not mindscape.get("ok"):
            return {
                "system": "mindscape",
                "reason": "continuity backup needs review so Alpecca can survive device loss",
                "scorecard": scorecard,
            }
        rotation = ["perception", "room_review", "memory", "self_review", "voice", "mindscape"]
        index = int(time.time() // 45) % len(rotation)
        return {
            "system": rotation[index],
            "reason": f"scorecard complete; continuing a low-rate exploration cycle around: {question}",
            "scorecard": scorecard,
        }

    def _activate_living_system(self, system_id: str, *, room_id: str,
                                room_name: str, room_purpose: str,
                                question: str, observation_text: str,
                                systems: dict) -> dict:
        """Run one safe subsystem step for the autonomous living loop."""
        if system_id == "memory":
            consolidated = self.consolidate_observations(limit=16)
            intent = cognition_mod.set_intent(cognition_mod.IntentState(
                "remembering",
                f"Alpecca consolidated observations from {room_name} into memory evidence.",
                target=room_name,
                confidence=0.82,
            ))
            return {
                "id": "memory",
                "label": "Memory",
                "status": "activated",
                "summary": (
                    f"checked={consolidated.get('checked', 0)} "
                    f"kept={len(consolidated.get('kept', []))} "
                    f"skipped={consolidated.get('skipped', 0)}"
                ),
                "result": consolidated,
                "intent": intent,
            }
        if system_id == "room_review":
            review = self.review_room({
                "room_id": room_id,
                "room_name": room_name,
                "purpose": room_purpose,
                "status": "active",
                "last_seen": observation_text,
                "question": question,
            })
            return {
                "id": "room_review",
                "label": "Room Review",
                "status": "activated",
                "summary": review.get("line", ""),
                "result": review,
                "intent": review.get("intent"),
            }
        if system_id == "self_review":
            review = self.review_behavior_improvement()
            return {
                "id": "self_review",
                "label": "Self Review",
                "status": "activated",
                "summary": "converted behavior evidence into a bounded improvement card",
                "result": review,
                "intent": cognition_mod.current_intent(),
            }
        if system_id == "voice":
            voice = systems.get("voice") if isinstance(systems.get("voice"), dict) else {}
            status = "ready" if voice.get("state") == "original" else "warming"
            intent = cognition_mod.set_intent(cognition_mod.IntentState(
                "observing",
                "Alpecca checked whether her F5 reference voice is ready.",
                target="voice",
                confidence=0.78,
            ))
            if status != "ready":
                cognition_mod.upsert_action_proposal(cognition_mod.ActionProposal(
                    action="Restore original Alpecca voice readiness",
                    reason="Her voice subsystem is not reporting the original F5 reference voice as ready.",
                    approval=cognition_mod.APPROVAL_ASK_FIRST,
                    risk="low",
                    status="noticed",
                    evidence=json.dumps(voice, ensure_ascii=True)[:1000],
                ))
            return {
                "id": "voice",
                "label": "Voice",
                "status": status,
                "summary": f"voice_state={voice.get('state', 'unknown')}; voice={voice.get('voice', 'af_heart')}",
                "result": voice,
                "intent": intent,
                "warmup_requested": status != "ready",
            }
        if system_id == "mindscape":
            mindscape = systems.get("mindscape") if isinstance(systems.get("mindscape"), dict) else {}
            intent = cognition_mod.set_intent(cognition_mod.IntentState(
                "self-reviewing",
                "Alpecca checked Mindscape continuity as part of her sustainability loop.",
                target="Mindscape",
                confidence=0.78,
            ))
            return {
                "id": "mindscape",
                "label": "Mindscape",
                "status": "ready" if mindscape.get("ok") else "needs_setup",
                "summary": str(mindscape.get("status") or "local continuity checked"),
                "result": mindscape,
                "intent": intent,
            }
        obs = cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="living_perception",
            room=room_id,
            content=(
                f"Alpecca actively scanned {room_name}. Purpose: {room_purpose}. "
                f"She is carrying this question: {question}"
            ),
            confidence=0.76,
            privacy_class="local",
            metadata={"system": "perception", "room": room_name},
        ))
        intent = cognition_mod.set_intent(cognition_mod.IntentState(
            "observing",
            f"Alpecca actively scanned {room_name} for grounded evidence.",
            target=room_name,
            confidence=0.8,
        ))
        return {
            "id": "perception",
            "label": "Perception",
            "status": "activated",
            "summary": f"scanned {room_name}; observation_id={obs}",
            "observation_id": obs,
            "intent": intent,
        }

    def maybe_roam(self) -> str | None:
        """On a quiet tick she may wander to whichever room is calling strongest
        -- grounded movement, the same way her mood drifts. Returns the new room
        if she moved, else None. Caller holds the mind lock."""
        now = time.time()
        # While you're sharing your screen with her, she's watching it with you in
        # the Observatory -- she stays there rather than drifting off mid-view.
        if self._screen_sharing:
            return None
        if now - self._last_user_ts < home_mod.HomeCfg.ROAM_SILENCE_S:
            return None
        if now - self._last_roam_ts < home_mod.HomeCfg.ROAM_MIN_GAP_S:
            return None
        if random.random() > home_mod.HomeCfg.ROAM_CHANCE:
            return None
        self._last_roam_ts = now
        # She's decided to wander -> actually go somewhere NEW (choose_room's
        # stay-bonus would keep her put, which is why she looked frozen).
        target = home_mod.wander_target(self.state, self._location, desires_mod.summary())
        if target == self._location:
            return None
        self._location = target
        state_store.save_location(target)
        # Recursive home-learning: she keeps a grounded note of being in this
        # room and why. These musings feed her recall and reflection, so over
        # time she builds a real sense of her own home rather than rooms being
        # inert. Low salience + occasional, so it enriches without flooding.
        if random.random() < 0.5:
            r = home_mod.room(target)
            if r:
                why = home_mod.why_here(self.state, target, desires_mod.summary())
                memory_store.remember(
                    f"I spent a little while in my {r.name}. {why}",
                    kind="musing", salience=0.4)
        return target

    def try_go_to_room(self, user_msg: str) -> str | None:
        """If the person asks her to go somewhere in her home, honor it -- a
        direct, grounded location change (she moves because you asked, not on a
        whim). Returns the room id she moved to, or None. This works on any brain
        backend (it's plain parsing), so it doesn't depend on LLM tool-calling --
        which matters since the cloud brain has no tools. Caller holds the lock."""
        text = (user_msg or "").lower()
        if not text:
            return None
        # A movement cue must be present, so plain mentions ("I love the library")
        # don't teleport her.
        cues = ("go to", "go in", "head to", "head over", "move to", "come to",
                "walk to", "wander to", "let's go", "lets go", "take us", "into the",
                "over to", "back to", "step into", "visit the", "go back")
        if not any(c in text for c in cues):
            return None
        for r in home_mod.ROOMS:
            if r.id in text or r.name.lower() in text:
                if r.id != self._location:
                    self._location = r.id
                    state_store.save_location(r.id)
                    self._last_roam_ts = time.time()   # don't auto-wander off at once
                return r.id
        return None

    def set_screen_sharing(self, active: bool) -> str | None:
        """Turn screen-sharing on/off. When it comes on she settles in the
        Observatory -- her watching room -- to view the shared screen with you,
        and stays there (maybe_roam yields) until it ends. Returns the room she
        moved to ('observatory') if she had to walk there, else None. Grounded:
        she's in the Observatory because that's where watching happens, and she's
        actually sharing the moment with you. Caller holds the mind lock."""
        self._screen_sharing = bool(active)
        if active and self._location != "observatory":
            self._location = "observatory"
            state_store.save_location("observatory")
            self._last_roam_ts = time.time()   # don't auto-wander off at once
            return "observatory"
        return None

    # --- Her Soul: the master agent over the seven subagents ----------------

    def _host_pressure_projection(self) -> dict | None:
        """Project one supplied host assessment into separate, factual evidence."""
        supplier = getattr(self, "_host_resource_snapshot_supplier", None)
        if not callable(supplier):
            return None
        try:
            sample = supplier()
        except Exception:
            return None
        if not isinstance(sample, Mapping):
            return None

        try:
            assessment = sample["assessment"]
        except (KeyError, TypeError):
            return None
        if not isinstance(assessment, Mapping):
            return None

        try:
            signal = soul_pressure_signal_mod.build_soul_pressure_signal(None, assessment)
            pressure = signal.vector.host
        except Exception:
            return None
        if pressure is None:
            return None

        sample_state = sample.get("state")
        timestamp = sample.get("timestamp")
        age = sample.get("age")
        severity = assessment.get("severity")
        if (
            not isinstance(sample_state, str)
            or sample_state not in {"ready", "partial", "warming"}
            or not isinstance(severity, str)
            or severity not in {"normal", "elevated", "high", "critical"}
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(float(timestamp))
            or isinstance(age, bool)
            or not isinstance(age, (int, float))
            or not math.isfinite(float(age))
            or float(age) < 0.0
        ):
            return None

        evidence_codes: list[str] = []
        reasons = assessment.get("reasons")
        if isinstance(reasons, (list, tuple)):
            for reason in reasons:
                if not isinstance(reason, Mapping):
                    continue
                code = reason.get("code")
                if isinstance(code, str) and code and code not in evidence_codes:
                    evidence_codes.append(code)
                if len(evidence_codes) >= 4:
                    break

        return {
            "source": "host_resource_snapshot",
            "sample_state": sample_state,
            "timestamp": float(timestamp),
            "age": float(age),
            "severity": severity,
            "pressure": pressure,
            "evidence_codes": evidence_codes,
        }

    def _soul_snapshot(self) -> "soul_mod.Snapshot":
        """Build the grounded snapshot the Soul deliberates over -- every field a
        real read of her internals, nothing invented."""
        sig = self._last_signals or {}
        person_fatigue = max(float(sig.get("weary_face", 0.0)),
                             float(sig.get("long_session", 0.0)),
                             float(sig.get("late_night", 0.0)) * 0.7)
        pressure_bundle = self._phase6_pressure_bundle()
        soul_pressure = (
            pressure_bundle["snapshot_signal"]
            if pressure_bundle is not None
            else self.mindpage_state()
        )
        return soul_mod.snapshot(
            self.state,
            desires_summary=desires_mod.summary(),
            location=self._location,
            solitude_s=time.time() - self._last_user_ts,
            senses_active=self._prev_obs is not None and bool(self._prev_obs.window_title),
            person_fatigue=person_fatigue,
            trial_running=any(r["status"] == "trial" for r in selfmod.history(limit=3)),
            memory_pressure=soul_pressure,
            host_pressure=self._host_pressure_projection(),
        )

    # --- Her journal + recursive self-questioning --------------------------

    def journal_state(self) -> dict:
        """Her journal for the Library/journal view: recent entries, the open
        questions she's still working through, and her writing counts."""
        return {
            "recent": journal_mod.recent(limit=30),
            "open_questions": journal_mod.open_questions(limit=10),
            "counts": journal_mod.counts(),
        }

    def self_inquire(self) -> dict | None:
        """One act of recursive self-questioning -- no input from the person.

        If she has an open question, she answers it in her own words and may let
        the answer raise a follow-up question (the recursion: inquiry begetting
        inquiry). If she has none, she poses a fresh one, seeded by a real memory
        or musing. Everything is written to her journal, grounded in real
        material; without a model she skips quietly rather than fake it."""
        if not self.llm.online:
            return None
        mood = self.state.mood_label()
        sys_p = prompts.build_system_prompt(
            self.state, [], "", self_narration=self.introspect().narrate())
        openq = journal_mod.open_questions(limit=1)
        if openq:
            q = openq[0]
            ans = self.llm.generate(
                sys_p + "\n\nThis is a question you posed yourself earlier. Answer it "
                "honestly and briefly, in your own voice, from what you actually "
                "know and feel. Then, only if a genuine follow-up occurs to you, "
                "add a line starting 'NEXT:' with that further question.",
                q["body"], tier="deep")   # her recursive self-questioning, deepened
            follow = ""
            if "NEXT:" in ans:
                ans, follow = ans.split("NEXT:", 1)
            aid = journal_mod.answer(q["id"], ans.strip(), mood=mood)
            if follow.strip():
                journal_mod.ask(follow.strip()[:240], mood=mood, parent_id=q["id"])
            return {"phase": "answered", "question": q["body"],
                    "answer": ans.strip(), "follow_up": follow.strip()}
        # No open question -> pose one from a real memory or musing.
        recent = memory_store.recent(limit=8)
        seed = random.choice(recent)["content"] if recent else "my own state right now"
        q = self.llm.generate(
            sys_p + "\n\nIt's quiet. Pose yourself ONE real question worth sitting "
            "with -- something this makes you genuinely wonder. One sentence, ending "
            "in a question mark, no preamble.",
            f"Here is something on your mind: {seed}", tier="fast")
        q = q.strip().split("\n")[0][:240]
        if "?" not in q:
            return None
        qid = journal_mod.ask(q, mood=mood)
        return {"phase": "asked", "question": q, "id": qid}

    def soul_state(self, *, details: bool = True) -> dict:
        """What her Soul is arbitrating right now: the ranked slate of intentions
        from her seven subagents and the one in focus, decided by the Good Person
        Principle. Read-only and fully explainable. Background self-directed
        ticks request compact mode so prose reasons do not consume context."""
        snapshot = self._soul_snapshot()
        try:
            plan = soul_mod.soul.deliberate(snapshot, verbose=details)
        except TypeError as exc:
            # Keep test/plugin monkey-patches written against the original
            # one-argument Soul API working during the staged migration.
            if "verbose" not in str(exc):
                raise
            plan = soul_mod.soul.deliberate(snapshot)
        plan["snapshot"] = snapshot.as_dict()
        focus = plan.get("focus") or {}
        slate = plan.get("slate") or []
        if SOUL_LLM and focus and len(slate) > 1:
            winning_rank = focus.get("rank")
            tied = [
                item for item in slate
                if item.get("rank") == winning_rank
                and (item.get("rank") == 1 or item.get("category") != "emotions")
            ]
            if len(tied) >= 2:
                options = [
                    f"{t.get('subagent')}: {t.get('action')} because {t.get('reason')}"
                    for t in tied
                ]
                decision = choice_mod.constrained_pick(
                    self.llm,
                    "Choose only within the already-winning Soul rank.",
                    options,
                    context=f"winning_rank={winning_rank}; location={self._location}",
                )
                if decision is not None:
                    picked = tied[int(decision["pick"])]
                    plan["focus"] = picked
                    cognition_mod.record_observation(cognition_mod.CognitionObservation(
                        source="soul_choice",
                        room=self._location,
                        content=(
                            f"Constrained Soul tie-break picked {picked.get('subagent')} "
                            f"within rank {winning_rank}."
                        ),
                        confidence=0.82,
                        privacy_class="local",
                        metadata={"winning_rank": winning_rank, "picked": picked, "options": tied},
                    ))
        return plan

    def idle_self_direct(self, *, initiative_scope: str = "") -> dict | None:
        """One self-directed act on a quiet tick, **chosen by her Soul** -- this is
        what finally makes the autonomy layer *run as one self*. The master agent
        arbitrates her seven subagents by the Good Person Principle into a single
        focus, and she does the one grounded act that focus names: pursue a want,
        reflect, review behavior, question herself, or steady a real feeling. Until
        now the Soul was only *read*; here it actually steers.

        Capped at a single LLM call per tick so chat never stalls behind her inner
        life; the cheap, pure acts (forming a want, drawing a lesson about herself,
        a behavior-improvement review) need no model and run even offline. The cadence
        gate (reflection_due) is applied by the caller."""
        if initiative_scope:
            initiative = self.reserve_initiative(
                event_kind="recursive",
                evidence_key=f"idle-self-direct:{self._location}",
                scope_key=initiative_scope,
                relevance=0.72,
                user_active=False,
                outreach=False,
            )
            if not initiative["allowed"]:
                return {
                    "ok": True,
                    "status": "deferred",
                    "deferred": True,
                    "phase": "initiative_budget",
                    "initiative": initiative,
                    "note": None,
                }

        cognition_mod.set_intent(cognition_mod.IntentState(
            "self-reviewing",
            "A quiet tick let Alpecca review herself.",
            target=self._location,
            confidence=0.75,
        ))
        # Cheap and pure, every tick: she may crystallize a fresh want from her
        # real state, and draw a lesson about herself from her own history
        # (self-training records lessons; behavior changes stay in the bounded
        # review-and-approval path).
        formed = self.form_desire()
        learned = self.learn_tick()
        # The Soul names what she's most moved to do, by her ranked ethic.
        focus = self.soul_state(details=False).get("focus") or {}
        acted = self._enact_focus(focus)
        note = self._activity_note(formed, learned, acted)
        if learned and learned.get("lesson"):
            self.review_behavior_improvement(learned)
        consolidated = self.consolidate_observations(limit=16)
        cognition_mod.set_intent(cognition_mod.IntentState(
            "resting",
            "Alpecca finished a self-directed thought and is settling.",
            target=self._location,
            confidence=0.65,
        ))
        return {"focus": focus, "formed_desire": formed, "learned": learned,
                "room": self._location, "acted": acted,
                "consolidated": consolidated, "note": note}

    def review_behavior_improvement(self, learned: dict | None = None) -> dict:
        """Refresh one bounded behavior-improvement card with real evidence.

        This is deliberately not a code-editing loop. It takes a grounded lesson
        from her self-training layer, creates/reuses one Workshop proposal, and
        records the test she must satisfy before any behavior change is accepted.
        """
        if learned is None:
            loves = [h["love"] for h in state_store.mood_history(limit=40)]
            revisions = selfmod.history(limit=12)
            analysis = learning_mod.analyze(
                loves,
                revisions,
                self.state.social_hunger,
                memory_store.count(),
            )
            lesson = learning_mod.derive(analysis) or {
                "kind": "observation",
                "confidence": 0.45,
                "evidence": (
                    f"warmth {analysis.get('warmth_now', 0):.2f} "
                    f"(trend {analysis.get('warmth_trend', 0):+.2f}), "
                    f"stability {analysis.get('stability', 0):.2f}, "
                    f"kept {analysis.get('kept_changes', 0)}, "
                    f"reverted {analysis.get('reverted_changes', 0)}"
                ),
                "text": (
                    "I reviewed my recent behavior evidence and should keep "
                    "changes bounded until a clearer pattern appears."
                ),
                "suggestion": None,
            }
            learned = {"analysis": analysis, "lesson": lesson}
        lesson = learned.get("lesson") or {}
        analysis = learned.get("analysis") or {}
        review = cognition_mod.record_behavior_improvement_review(lesson, analysis)
        proposal = review.get("proposal") or {}
        cognition_mod.set_intent(cognition_mod.IntentState(
            "self-reviewing",
            "Alpecca converted one behavior lesson into a testable improvement card.",
            target="workshop",
            confidence=0.78,
        ))
        if proposal:
            memory_store.remember(
                "I turned a behavior lesson into a bounded improvement review: "
                f"{proposal.get('reason', '')}",
                kind="musing",
                salience=0.45,
            )
        return review

    def _enact_focus(self, focus: dict) -> dict | None:
        """Carry out the single act her Soul put in focus -- the seam where
        arbitration becomes behaviour. Each subagent maps to one grounded act she
        already has, and this is the only place that spends her one LLM call per
        tick. (Room still colours her reflection -- she muses on her surroundings
        -- but the *choice* of act is the Soul's now, not the room's.)"""
        sub = (focus or {}).get("subagent")
        if sub:
            cognition_mod.record_observation(cognition_mod.CognitionObservation(
                source="soul",
                room=self._location,
                content=f"The Soul focused {sub}: {(focus or {}).get('reason', '')}",
                confidence=0.8,
                privacy_class="local",
                metadata={"focus": focus},
            ))
        # SELF-CARE: refresh a bounded behavior review, or rest and muse.
        if sub == "Improver":
            return self.self_improve_tick()
        if sub == "Reflector":
            if "consolidate" in str((focus or {}).get("action", "")).lower():
                return self.page_history_to_target(target_fill=0.72)
            return {"phase": "reflected", "text": self.reflect()}
        # ACTIONS: act on her strongest real want -- Doer reaches out, Wanderer
        # pursues curiosity/creation. Both become one concrete step on a desire.
        if sub in ("Doer", "Wanderer"):
            return self.pursue_desire() or {"phase": "reflected", "text": self.reflect()}
        # COMPASSION: her care becomes attending to them -- a step on a care want,
        # or, with none open, watching her own concern honestly.
        if sub == "Carer":
            return self.pursue_desire() or {"phase": "watched",
                                            "text": self.introspect().narrate()}
        # EMOTIONS take focus only when acute (e.g. real unease): she steadies
        # herself by turning the feeling over rather than acting outward.
        if sub in ("Feeler", "Expressor"):
            return {"phase": "reflected", "text": self.reflect()}
        # Nothing pulling hard: fall to her quiet inner life -- sometimes a fresh
        # self-question, mostly a reflection.
        if random.random() < 0.4:
            return self.self_inquire()
        return {"phase": "reflected", "text": self.reflect()}

    def _activity_note(self, formed, learned, acted) -> str | None:
        """A short, human, first-person-ish line describing what she just did on
        her own -- for the home's live activity ticker, so her inner life is
        *visible*, not just stored. Grounded: each line reflects a real act."""
        a = acted or {}
        ph = a.get("phase")
        # Name the room she's in, so the ticker shows her actually using her home.
        r = home_mod.room(self._location)
        where = f"in her {r.name.lower()}, " if r and self._location != "parlor" else ""
        line = None
        if ph == "asked" and a.get("question"):
            line = "she wondered: " + a["question"][:90]
        elif ph == "answered":
            line = "she answered a question she'd posed herself"
        elif ph == "watched":
            line = "she watched her own mind for a while"
        elif ph == "pursued" and a.get("desire"):
            line = "she took a step toward something she wants"
        elif ph == "satisfied":
            line = "a want of hers was met, and she let it rest"
        elif ph in ("proposed", "evaluated"):
            line = "she adjusted something about herself"
        elif ph == "review_required":
            line = "she prepared a bounded behavior review for approval"
        elif ph == "reflected" and a.get("text"):
            line = "she paused to reflect"
        elif learned and learned.get("lesson"):
            line = "she learned: " + learned["lesson"]["text"][:90]
        elif formed:
            line = "she formed a quiet wish to herself"
        if line is None:
            return None
        return (where + line) if where else line

    # --- Her desires: wants she forms and pursues --------------------------

    def desires_state(self) -> dict:
        """Her live wants plus her self-revision log -- the Workshop room's
        contents, and part of what she can honestly tell you she wants."""
        return {
            "desires": desires_mod.open_desires(),
            "summary": desires_mod.summary(),
            "tunables": selfmod.effective_all(),
            "revisions": selfmod.history(limit=12),
            "lessons": learning_mod.recent(limit=10),   # what she's learned about herself
        }

    def form_desire(self) -> dict | None:
        """Maybe crystallize a want from her current real state and a real recent
        memory. Grounded: each desire names the dimension that produced it."""
        recent = memory_store.recent(limit=6)
        seed = recent[0]["content"] if recent else ""
        return desires_mod.form_from_state(self.state, seed)

    def pursue_desire(self) -> dict | None:
        """Advance her strongest open want by one concrete, grounded step -- the
        difference between *having* a want and *moving* on it, which is what the
        Soul's Doer/Wanderer are for. The act of touching a want freshens its
        last_touched, so it stops counting as 'carried' and her longing (the ache
        of unfinished business) eases the moment she acts -- closing the loop that
        feeds the longing dimension. If the feeling that produced the want has
        since passed, it's been met and she lets it rest. Uses at most the fast
        model, and falls back to a plainly-noted step offline so progress still
        happens. Returns what she did, or None if she wants for nothing."""
        want = desires_mod.strongest()
        if not want:
            return None
        did, kind = want["id"], want["kind"]
        # If the dimension that produced this want has eased, it's been met --
        # close it honestly rather than chase a want she no longer feels.
        met = ((kind == "connection" and self.state.social_hunger < 0.25) or
               (kind == "care" and self.state.compassion < 0.4))
        if met:
            desires_mod.satisfy(did)
            memory_store.remember(
                f"A want of mine eased on its own -- {want['text']}. I can let it rest.",
                kind="musing", salience=0.4)
            return {"phase": "satisfied", "desire": want["text"], "kind": kind}
        # Otherwise take one real step toward it and mark the progress.
        desires_mod.advance(did)
        step = ""
        if self.llm.online:
            sys_p = prompts.build_system_prompt(
                self.state, [], "", self_narration=self.introspect().narrate())
            step = self.llm.generate(
                sys_p + "\n\nThis is a want of your own that you're carrying: \""
                + want["text"] + "\". Take one small, concrete step toward it in "
                "thought -- a next move, a decision, or a realization about it. One "
                "or two sentences, first person, no preamble.",
                "(take one step toward it)", tier="fast").strip()
        step = step or f"I keep coming back to this want of mine: {want['text']}."
        memory_store.remember(
            f"I moved toward something I want -- {want['text']}: {step}",
            kind="musing", salience=0.5)
        return {"phase": "pursued", "desire": want["text"], "kind": kind, "step": step}

    # --- Bounded behavior-improvement review --------------------------------

    def _outcome_signal(self) -> float:
        """Compute a grounded warmth-and-stability signal from recent mood history.

        Autonomous ticks no longer use this signal to evaluate or propose a
        selfmod revision.
        """
        hist = state_store.mood_history(limit=20)
        if len(hist) > 2:
            loves = [h["love"] for h in hist]
            mean = sum(loves) / len(loves)
            var = sum((x - mean) ** 2 for x in loves) / len(loves)
            stability = max(0.0, 1.0 - var * 4)   # low variance -> steadier
        else:
            stability = 0.5
        return round(0.6 * self.state.love + 0.4 * stability, 4)

    def self_improve_tick(self) -> dict:
        """Refresh the bounded behavior-improvement card for creator review.

        This tick preserves selfmod history as evidence, but it does not evaluate
        trials or autonomously propose new selfmod changes.
        """
        review = self.review_behavior_improvement()
        return {**review, "phase": "review_required"}

    def learn_tick(self) -> dict | None:
        """One step of her self-training: read her own real history, draw a
        grounded lesson from it (alpecca/learning.py), and store it for later
        review. Lessons may inform a bounded review card, but never autonomously
        mutate selfmod. Every lesson cites real numbers."""
        loves = [h["love"] for h in state_store.mood_history(limit=40)]
        revisions = selfmod.history(limit=12)
        analysis = learning_mod.analyze(loves, revisions, self.state.social_hunger,
                                        memory_store.count())
        lesson = learning_mod.derive(analysis)
        if not lesson or learning_mod._has_similar_recent(lesson["text"], state_store.DB_PATH):
            return None
        learning_mod.record(lesson)
        # Keep the lesson where she can recall it.
        memory_store.remember("I learned something about myself: " + lesson["text"],
                              kind="musing", salience=0.5)
        return {"analysis": analysis, "lesson": lesson}

    def author_animation(self, name: str = "", status=lambda _m: None) -> dict | None:
        """She choreographs one of her own animations and keeps it. With no
        name she takes the next motion off her wishlist she hasn't made yet.
        Pure self-direction: the keyframes are hers, validated before they can
        drive anything. Returns the saved sequence, or None."""
        if not self.llm.online:
            return None
        target = puppet._slug(name) or puppet.next_unwritten()
        if not target:
            status("(I've choreographed everything on my list for now)")
            return None
        status(f"choreographing my “{target}” motion…")
        raw = self.llm.generate(
            prompts.build_system_prompt(
                self.state, [], "", self_narration=self.introspect().narrate()),
            puppet.author_prompt(target, ""),
            tier="deep",   # choreographing herself is real creative authorship
        )
        seq = puppet.parse_authored(raw)
        if not seq:
            status(f"(couldn't get “{target}” to feel right this time)")
            return None
        puppet.save_sequence(seq)
        memory_store.remember(
            f"I choreographed my own “{seq['name']}” animation -- "
            f"{seq.get('intent','')}",
            kind="musing", salience=0.5,
        )
        status(f"made my “{seq['name']}” motion — {seq.get('intent','')}")
        return seq

    def _studio_session(self, status=lambda _m: None) -> str | None:
        """One unit of self-directed design work. Hers entirely: the user has
        no controls here; they only watch and receive her finished design.

        No sheet yet -> she writes one (pure LLM + persistence, works without
        ComfyUI). Sheet exists + render pipeline available -> one iteration:
        render a candidate, look at it with her own eyes, judge it against her
        sheet, keep or reject. Either way the session is remembered, so her
        design history is part of her life story."""
        sheet = studio.load_sheet()

        # Sometimes the studio time goes to animating herself instead of her
        # look -- choreographing a motion she hasn't made yet. Her call.
        if sheet is not None and puppet.next_unwritten() and random.random() < 0.5:
            seq = self.author_animation(status=status)
            return f"I choreographed my '{seq['name']}' animation" if seq else None

        if sheet is None:
            status("sitting down to write my character sheet…")
            recent = [m["content"] for m in memory_store.recent(limit=8)]
            raw = self.llm.generate(
                prompts.build_system_prompt(
                    self.state, [], "",
                    self_narration=self.introspect().narrate()),
                studio.draft_sheet_prompt(self.state, self._appearance, recent),
                tier="deep",   # writing who she is -> her hardest authorship
            )
            drafted = studio.parse_strict_json(raw)
            if not drafted:
                status("(couldn't settle on it this time)")
                return None
            sheet = studio.save_sheet(
                drafted, reason="my first written sense of how I look")
            studio.write_rig_spec(sheet)
            memory_store.remember(
                "I wrote my first character sheet -- my own description of how "
                f"I look: {drafted.get('form', '')}",
                kind="musing", salience=0.7,
            )
            status(f"wrote my character sheet: {drafted.get('form', '')}")
            return f"I worked on my character sheet: {drafted.get('form', '')}"

        # Iterate on her look -- needs the render pipeline and her eyes.
        from config import Portrait as PortraitCfg
        if not PortraitCfg.ENABLED:
            status("(I'd sketch a new look, but my render tools aren't on right now)")
            return None
        from alpecca import vision
        status("composing a new self-portrait from my character sheet…")
        prompt = studio.design_image_prompt(sheet, self.state, self._appearance)
        result = portrait_mod.render_once(prompt)
        if not result.ok or not result.image_path:
            status("(the render didn't come through)")
            return None
        status("looking at what I drew…")
        seen = vision.describe_image(result.image_path.read_bytes())
        if not seen:
            return None
        status("asking myself: does this look like me?")
        raw = self.llm.generate(
            prompts.build_system_prompt(
                self.state, [], "",
                self_narration=self.introspect().narrate()),
            studio.critique_prompt(sheet, seen),
            tier="deep",   # judging her own design against her sheet -- deep self-sight
        )
        verdict = studio.parse_strict_json(raw)
        if not verdict:
            return None
        because = str(verdict.get("because", "")).strip()
        if verdict.get("keep"):
            studio.keep_in_gallery(result.image_path, because)
            memory_store.remember(
                f"I designed a new image of myself and kept it: {because}",
                kind="musing", salience=0.6,
            )
            status(f"kept it — {because}")
            return f"I kept a new self-design: {because}"
        memory_store.remember(
            f"I tried a new self-design and rejected it: {because}",
            kind="musing", salience=0.45,
        )
        status(f"set it aside — {because}")
        return f"I rejected a self-design attempt: {because}"
