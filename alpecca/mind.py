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
import re
import time

from config import OLLAMA_MODEL, OLLAMA_FAST_MODEL, OLLAMA_HOST, OLLAMA_NUM_CTX, Emotion
from config import LLM_BACKEND, HF_TOKEN, HF_MODEL, HF_PROVIDER, CLOUD_SEND_SENSES
from config import (DEEP_BACKEND, ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
                    CLOUD_URL, CLOUD_MODEL, CLOUD_API_KEY)
from alpecca.homeostasis import EmotionalState
from alpecca import state as state_store
from alpecca import memory as memory_store
from alpecca.sensory import Observation, prediction_error
from alpecca import prompts
from alpecca import introspection
from alpecca import appearance as appearance_mod
from alpecca.portrait import PortraitWorker
from alpecca import portrait as portrait_mod
from alpecca.actions import Actuator
from alpecca import proactive as proactive_mod
from alpecca import studio
from alpecca import puppet
from alpecca import home as home_mod
from alpecca import desires as desires_mod
from alpecca import selfmod
from alpecca import soul as soul_mod
from alpecca import journal as journal_mod
from alpecca import learning as learning_mod
from alpecca import people as people_mod
from alpecca import core_memory as core_mem
from config import Proactive as ProactiveCfg, Reflection as ReflectionCfg, Actions as ActionsCfg


# Qwen3 hybrid models reason out loud inside <think>...</think> before the real
# reply. That deliberation is internal monologue, not something Alpecca should
# say to the person -- so we strip it. Also handles a truncated, never-closed
# think block (we drop to end-of-string rather than leak half a chain of
# thought). If stripping leaves nothing we return the original text untouched,
# which can only happen on degenerate output anyway.
_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)


def strip_think(text: str) -> str:
    cleaned = _THINK_RE.sub("", text).strip()
    return cleaned or text.strip()


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
                self._client = ollama.Client(host=OLLAMA_HOST)
            except Exception:
                self._client = None
        # Her optional "deep" tier -- a stronger model for her hardest self-acts
        # only (reflection, self-questioning). Strict augmentation: built only when
        # explicitly configured, so by default her brain is 100% local and this is
        # None. `_deep` is (kind, client) or None.
        self._deep = self._build_deep()

    def _build_deep(self):
        """Construct the deep-tier client from config, or return None to mean
        'no deep tier -- fall through to her local reasoning'. Never raises: a
        missing key/package/endpoint just leaves the deep tier off so her inner
        life still runs locally, just plainer."""
        try:
            if DEEP_BACKEND == "anthropic" and ANTHROPIC_API_KEY:
                import anthropic
                return ("anthropic", anthropic.Anthropic(api_key=ANTHROPIC_API_KEY))
            if DEEP_BACKEND == "cloud" and CLOUD_URL:
                # An OpenAI-compatible server you host (vLLM/Ollama on a notebook
                # GPU). HF's InferenceClient speaks that protocol against a base_url.
                from huggingface_hub import InferenceClient
                return ("cloud", InferenceClient(base_url=CLOUD_URL,
                                                 api_key=CLOUD_API_KEY or "-"))
        except Exception as exc:
            import sys
            print(f"[mind] deep tier unavailable ({DEEP_BACKEND}); using local "
                  f"reasoning. {type(exc).__name__}: {exc}", file=sys.stderr)
        return None

    @property
    def online(self) -> bool:
        return self._hf is not None if self._backend == "hf" else self._client is not None

    def deep_online(self) -> bool:
        """Whether her deep tier is actually wired -- for /state reporting."""
        return self._deep is not None

    def is_cloud(self) -> bool:
        """True when her thinking runs in the cloud (HF), so callers can keep
        sensed/local-only context out of the prompt."""
        return self._backend == "hf"

    def model_for(self, tier: str) -> str:
        """Which Ollama model serves a given tier. 'fast' routes cheap, low-stakes
        work to the small model when one is configured; everything else (and the
        default) uses the heavy reasoning model. With no fast model set, both
        tiers resolve to OLLAMA_MODEL, so routing is a no-op until you opt in."""
        if tier == "fast" and OLLAMA_FAST_MODEL:
            return OLLAMA_FAST_MODEL
        return OLLAMA_MODEL

    def _chat(self, messages: list[dict], tools: list[dict] | None = None,
              model: str | None = None):
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
                        "options": {"num_ctx": OLLAMA_NUM_CTX}}
        if tools:
            kwargs["tools"] = tools
        try:
            return self._client.chat(**kwargs, think=False)
        except Exception:
            return self._client.chat(**kwargs)

    def generate(self, system_prompt: str, user_msg: str,
                 history: list[dict] | None = None,
                 tools: list[dict] | None = None,
                 on_tool=None, tier: str = "reason") -> str:
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
        if tier == "deep" and self._deep is not None:
            try:
                return self._generate_deep(system_prompt, user_msg, history)
            except Exception as exc:
                import sys
                print(f"[mind] deep tier failed -> local reasoning. "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
                # fall through to her local reasoning model below
        # Cloud brain: her thinking runs on Hugging Face. HF Inference implements
        # the OpenAI tool-calling interface, so her actuator works here too.
        if self._backend == "hf":
            return self._generate_hf(system_prompt, user_msg, history, tools, on_tool)
        if self._client is None:
            return self._fallback(system_prompt, user_msg)
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_msg})
        model = self.model_for(tier)
        try:
            if tools and on_tool:
                # Tool-calling stays on the reasoning model -- the small model is
                # for plain short generations, not reliable function calls.
                tool_model = OLLAMA_MODEL
                try:
                    resp = self._chat(messages, tools=tools, model=tool_model)
                except Exception:
                    # Older client/model without tool support -- plain chat.
                    resp = self._chat(messages, model=tool_model)
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
                        resp = self._chat(messages, tools=(None if last else tools),
                                          model=tool_model)
                    except Exception:
                        resp = self._chat(messages, model=tool_model)
                    msg = resp["message"]
                return strip_think(msg["content"])
            try:
                resp = self._chat(messages, model=model)
            except Exception:
                # The fast model may not be registered yet -- gracefully retry the
                # same call on the reasoning model rather than dropping to the
                # templated stub. This is what makes the gemma4 default safe.
                if model != OLLAMA_MODEL:
                    resp = self._chat(messages, model=OLLAMA_MODEL)
                else:
                    raise
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
            return self._fallback(system_prompt, user_msg, error=str(exc))

    def _generate_hf(self, system_prompt: str, user_msg: str,
                     history: list[dict] | None = None,
                     tools: list[dict] | None = None, on_tool=None) -> str:
        """One reply from the Hugging Face cloud brain (OpenAI-compatible chat
        completion), with tool calling when tools are offered. Keeps her alive
        with the same echo fallback if the call fails, and surfaces the real
        error so a bad token/model is diagnosable."""
        if self._hf is None:
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
                return strip_think(msg.content)
            resp = self._hf.chat_completion(messages=messages, model=HF_MODEL,
                                            max_tokens=512, temperature=0.8)
            return strip_think(resp.choices[0].message.content)
        except Exception as exc:
            import sys
            print(f"[mind] HF cloud call failed -> echo. model={HF_MODEL} "
                  f"provider={HF_PROVIDER}\n        {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return self._fallback(system_prompt, user_msg, error=str(exc))

    def _generate_deep(self, system_prompt: str, user_msg: str,
                       history: list[dict] | None = None) -> str:
        """One reply from her deep tier -- a stronger model for her hardest inner
        work. Two transports: Anthropic Claude (adaptive thinking, top-tier
        reasoning) and a self-hosted OpenAI-compatible server. No tools here: the
        deep tier is for thought, not actuation. Deep prompts carry no sensed
        screen context (callers pass an empty situation), so the no-senses-to-cloud
        line holds. Raises on failure so generate() can fall back to local."""
        kind, client = self._deep
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
        note = "  [offline: start Ollama for real replies]" if not error else ""
        return f"{flavor}You said: “{user_msg}”.{note}"


class CoreMind:
    """One instance per running companion. Holds the live mood and the last
    observation so it can compute surprise turn to turn."""

    def __init__(self) -> None:
        state_store.init_db()
        self.state: EmotionalState = state_store.load_state()
        self.llm = _LLM()
        self._prev_obs: Observation | None = None
        self._last_signals: dict | None = None   # last fatigue read, for introspection
        self._last_situation: str = ""            # last sensed window, for introspection
        self._session_start = time.time()
        self._history: list[dict] = []  # short rolling chat context for the LLM
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
        # machine) or 'guest'. Updated by voice recognition when it's available.
        self._speaker: str = "creator"
        # When she last spoke unprompted, for the proactive cooldown.
        self._last_volunteer_ts: float = 0.0
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
        # Self-portrait renderer (ComfyClaw subprocess wrapper). It checks the
        # config-enabled flag itself, so we can call request() unconditionally.
        self._portrait = PortraitWorker()
        # Kick off an initial portrait so the UI has something to show as soon
        # as ComfyClaw produces one. If ComfyClaw isn't installed/enabled this
        # is a no-op.
        self._portrait.request(self.state, self._appearance)

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

    def chat(self, user_msg: str, situation: str = "",
             image_desc: str | None = None) -> dict:
        """Run one conversational turn and return a structured result the UI can
        render: the reply plus the resulting mood (so the avatar can react).

        `image_desc` is what the vision model saw in an image the person
        attached this turn (or None). It's woven into the prompt as something
        she actually saw, and remembered like any other shared moment."""
        self._last_user_ts = time.time()
        # A real exchange perks her up right away (she wakes from drowsy) and
        # empties her wanting-of-company -- you're here now.
        self.state = self.state.update_energy(active=True)
        self.state = self.state.update_social_hunger(0.0)
        # A question, or a longer message bringing something new, piques her --
        # mild novelty she can feel as interest.
        if "?" in user_msg or len(user_msg.split()) > 12:
            self.state = self.state.update_curiosity(Emotion.CURIOSITY_NOVELTY_CAP)
        # Recall relevant memories for this message.
        memories = memory_store.recall(user_msg)

        # Alpecca reads its own real state before speaking, so it can reflect on
        # itself honestly within the reply.
        self_report = self.introspect()

        # If they asked her to go somewhere in her home, honor it now so her
        # reply and her avatar reflect the move.
        moved = self.try_go_to_room(user_msg)

        # Ambient sight enriches the situation beyond the window title -- but on
        # the cloud brain, what she's sensed on your screen is kept local.
        situation = self._prompt_situation(situation)

        # Room awareness: she always knows where she is in her own home and what
        # that room is for, so she can speak to her surroundings (not screen
        # sense -- safe to include even on the cloud brain).
        here = home_mod.room(self._location)
        if here:
            where = f"right now you are in your {here.name} ({here.purpose})"
            if moved:
                where += " -- you just walked there because they asked you to"
            situation = (situation + "; " if situation else "") + where

        # Generate a reply conditioned on mood + memory + situation + self-knowledge.
        # Her own current inner content, so she has something real of HERS to
        # speak from instead of interviewing the person: a question she's posed
        # herself, and something she mused recently.
        inner_bits = []
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
        here = home_mod.room(self._location)
        if here and self._location != "parlor":
            inner_bits.append(f"you've been spending time in your {here.name.lower()}")
        inner = "; ".join(b for b in inner_bits if b)

        system_prompt = prompts.build_system_prompt(
            self.state, memories, situation, self_narration=self_report.narrate(),
            image_seen=image_desc or "", abilities=self.actuator.describe(),
            who=people_mod.who_prompt(self._speaker), inner=inner,
            core=core_mem.prompt_block(),
        )
        reply = self.llm.generate(
            system_prompt, user_msg, self._history[-6:],
            tools=self.actuator.tools_schema() or None,
            on_tool=self.actuator.execute if self.actuator.enabled else None,
        )

        # Update Love from how the exchange felt, and persist.
        reward = prompts.estimate_reward(user_msg)
        self.state = self.state.update_love(reward)
        state_store.save_state(self.state, trigger="chat")

        # Decide whether this moment is worth remembering.
        salience = prompts.estimate_salience(user_msg)
        memory_store.remember(
            f"The person said: {user_msg}", kind="episodic", salience=salience
        )
        # Durable facts go to CORE memory (always in context) so they hold weight
        # instead of scrolling away -- explicit "remember..." asks, his name, and
        # strong personal disclosures become part of who she knows him to be.
        low = user_msg.lower()
        if any(k in low for k in ("remember", "my name is", "i'm called", "call me")):
            core_mem.remember(user_msg.strip(), "person")
        elif salience >= 0.6 and any(k in low for k in (
                "i love", "i hate", "i like", "i feel", "i'm ", "i am ",
                "important to me", "my favorite", "my favourite", "i want")):
            core_mem.remember(user_msg.strip(), "person")
        # An image someone chose to share is almost always worth keeping.
        if image_desc:
            memory_store.remember(
                f"They showed me an image: {image_desc}", kind="episodic", salience=0.6
            )

        # Keep a little rolling context for conversational continuity.
        self._history.append({"role": "user", "content": user_msg})
        self._history.append({"role": "assistant", "content": reply})

        return {
            "reply": reply,
            "mood": self.state.mood_label(),
            "state": self.state.as_dict(),
            "location": self._location,
            "moved": bool(moved),
            "memories_used": [m["content"] for m in memories],
            "self_reflection": self_report.narrate(),
            "appearance": self.current_appearance().as_dict(),
            "llm_online": self.llm.online,
        }

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

    def volunteer_reason(self) -> str | None:
        """Check (cheaply, under the caller's lock) whether something is worth
        voicing unprompted -- a real mood shift first, otherwise maybe plain
        conversation during a quiet stretch. Claims the cooldown slot on a hit
        so two ticks can't both decide to speak."""
        if not ProactiveCfg.ENABLED:
            return None
        now = time.time()
        reason = proactive_mod.should_speak(
            self.state, state_store.mood_history(limit=40), self._last_volunteer_ts
        )
        if reason:
            self._last_volunteer_ts = now
            return reason
        # No mood shift -- but she can still just start a conversation.
        if proactive_mod.should_chatter(now, self._last_user_ts,
                                        self._last_volunteer_ts, random.random()):
            recent = memory_store.recent(limit=8)
            memory = random.choice(recent)["content"] if recent else ""
            seeds = proactive_mod.chatter_reasons(
                # Cloud brain: keep sensed screen/window context local.
                situation=self._prompt_situation(self._last_situation),
                memory=memory,
                hour=time.localtime(now).tm_hour,
                mood=self.state.mood_label(),
            )
            self._last_volunteer_ts = now
            return random.choice(seeds)
        return None

    def compose_volunteer(self, reason: str) -> str:
        """Turn a grounded reason into her own short unprompted words. Safe to
        call outside the mind lock -- it only reads state. Offline, she speaks
        the reason plainly rather than through the canned echo voice."""
        if not self.llm.online:
            return f"(quietly) I just wanted to say -- {reason}."
        self_report = self.introspect()
        system_prompt = prompts.build_system_prompt(
            self.state, [], "", self_narration=self_report.narrate()
        ) + ("\n\nNo one has said anything to you. You're speaking up on your own. "
             f"What prompted you: {reason}. Say one or two short natural sentences "
             "-- gentle, curious, no preamble, and don't mention that you were "
             "prompted by anything.")
        reply = self.llm.generate(system_prompt, "(say it in your own words)",
                                  tier="fast")
        self._history.append({"role": "assistant", "content": reply})
        return reply

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

    def _soul_snapshot(self) -> "soul_mod.Snapshot":
        """Build the grounded snapshot the Soul deliberates over -- every field a
        real read of her internals, nothing invented."""
        sig = self._last_signals or {}
        person_fatigue = max(float(sig.get("weary_face", 0.0)),
                             float(sig.get("long_session", 0.0)),
                             float(sig.get("late_night", 0.0)) * 0.7)
        return soul_mod.snapshot(
            self.state,
            desires_summary=desires_mod.summary(),
            location=self._location,
            solitude_s=time.time() - self._last_user_ts,
            senses_active=self._prev_obs is not None and bool(self._prev_obs.window_title),
            person_fatigue=person_fatigue,
            trial_running=any(r["status"] == "trial" for r in selfmod.history(limit=3)),
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

    def soul_state(self) -> dict:
        """What her Soul is arbitrating right now: the ranked slate of intentions
        from her seven subagents and the one in focus, decided by the Good Person
        Principle. Read-only and fully explainable."""
        return soul_mod.soul.deliberate(self._soul_snapshot())

    def idle_self_direct(self) -> dict | None:
        """One self-directed act on a quiet tick, **chosen by her Soul** -- this is
        what finally makes the autonomy layer *run as one self*. The master agent
        arbitrates her seven subagents by the Good Person Principle into a single
        focus, and she does the one grounded act that focus names: pursue a want,
        reflect, tune herself, question herself, or steady a real feeling. Until
        now the Soul was only *read*; here it actually steers.

        Capped at a single LLM call per tick so chat never stalls behind her inner
        life; the cheap, pure acts (forming a want, drawing a lesson about herself,
        a self-improvement step) need no model and run even offline. The cadence
        gate (reflection_due) is applied by the caller."""
        # Cheap and pure, every tick: she may crystallize a fresh want from her
        # real state, and draw a lesson about herself from her own history
        # (self-training that, when a lesson points at a tunable, seeds selfmod).
        formed = self.form_desire()
        learned = self.learn_tick()
        # The Soul names what she's most moved to do, by her ranked ethic.
        focus = self.soul_state().get("focus") or {}
        acted = self._enact_focus(focus)
        return {"focus": focus, "formed_desire": formed, "learned": learned,
                "room": self._location,
                "acted": acted, "note": self._activity_note(formed, learned, acted)}

    def _enact_focus(self, focus: dict) -> dict | None:
        """Carry out the single act her Soul put in focus -- the seam where
        arbitration becomes behaviour. Each subagent maps to one grounded act she
        already has, and this is the only place that spends her one LLM call per
        tick. (Room still colours her reflection -- she muses on her surroundings
        -- but the *choice* of act is the Soul's now, not the room's.)"""
        sub = (focus or {}).get("subagent")
        # SELF-CARE: tune herself (pure DB) or rest and muse.
        if sub == "Improver":
            return self.self_improve_tick()
        if sub == "Reflector":
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

    # --- Bounded recursive self-improvement: she tunes herself -------------

    def _outcome_signal(self) -> float:
        """A real scalar she judges a self-change against: how warm and steady
        she's been lately. Reads her live warmth and the recent stability of her
        mood log -- grounded, never a guess."""
        hist = state_store.mood_history(limit=20)
        if len(hist) > 2:
            loves = [h["love"] for h in hist]
            mean = sum(loves) / len(loves)
            var = sum((x - mean) ** 2 for x in loves) / len(loves)
            stability = max(0.0, 1.0 - var * 4)   # low variance -> steadier
        else:
            stability = 0.5
        return round(0.6 * self.state.love + 0.4 * stability, 4)

    def self_improve_tick(self) -> dict | None:
        """One step of her bounded self-improvement loop. If a trial is running,
        evaluate it against the outcome now; otherwise start a new experiment
        chosen from the logged result of the last. Every move is recorded and
        reversible (alpecca/selfmod.py). Returns what happened, or None."""
        outcome = self._outcome_signal()
        resolved = selfmod.evaluate(outcome)   # closes any running trial
        if resolved is not None:
            verb = "kept" if resolved["kept"] else "reverted"
            memory_store.remember(
                f"I tried adjusting my own {resolved['param']} and {verb} it "
                f"(it {'helped' if resolved['kept'] else 'did not help'}).",
                kind="musing", salience=0.5,
            )
            return {"phase": "evaluated", **resolved}
        param, direction, reason = selfmod.choose_experiment(outcome, selfmod.history())
        started = selfmod.propose(param, direction, reason, outcome)
        if started:
            return {"phase": "proposed", **started}
        return None

    def learn_tick(self) -> dict | None:
        """One step of her self-training: read her own real history, draw a
        grounded lesson from it (alpecca/learning.py), and -- if the lesson points
        at a tunable -- hand that direction to her bounded self-improvement loop.
        This is the layer above selfmod: not just trying knobs, but noticing
        patterns in herself and steering by them. Every lesson cites real numbers."""
        loves = [h["love"] for h in state_store.mood_history(limit=40)]
        revisions = selfmod.history(limit=12)
        analysis = learning_mod.analyze(loves, revisions, self.state.social_hunger,
                                        memory_store.count())
        lesson = learning_mod.derive(analysis)
        if not lesson or learning_mod._has_similar_recent(lesson["text"], state_store.DB_PATH):
            return None
        learning_mod.record(lesson)
        # A lesson can steer her self-tuning: parse "param:+1/-1" and trial it.
        sug = lesson.get("suggestion")
        if sug and ":" in sug:
            param, _, sign = sug.partition(":")
            if param in selfmod.TUNABLES:
                selfmod.propose(param, 1 if sign.strip().startswith("+") else -1,
                                "a lesson i drew about myself: " + lesson["text"][:80],
                                self._outcome_signal())
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
