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

from config import OLLAMA_MODEL, OLLAMA_HOST
from alpecca.homeostasis import EmotionalState
from alpecca import state as state_store
from alpecca import memory as memory_store
from alpecca.sensory import Observation, prediction_error
from alpecca import prompts
from alpecca import introspection
from alpecca import appearance as appearance_mod
from alpecca.portrait import PortraitWorker
from alpecca.actions import Actuator
from alpecca import proactive as proactive_mod
from config import Proactive as ProactiveCfg, Reflection as ReflectionCfg


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
        self._client = None
        try:
            import ollama
            self._client = ollama.Client(host=OLLAMA_HOST)
        except Exception:
            self._client = None

    @property
    def online(self) -> bool:
        return self._client is not None

    def _chat(self, messages: list[dict], tools: list[dict] | None = None):
        """One Ollama chat call with thinking disabled.

        Qwen3 hybrids think out loud by default, which is great for math and
        terrible for companionship -- a reply that takes forty seconds isn't a
        conversation. We ask for no-think first and quietly retry plain for
        models/servers that reject the parameter; strip_think still catches
        any <think> blocks that slip through either way.
        """
        kwargs: dict = {"model": OLLAMA_MODEL, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        try:
            return self._client.chat(**kwargs, think=False)
        except Exception:
            return self._client.chat(**kwargs)

    def generate(self, system_prompt: str, user_msg: str,
                 history: list[dict] | None = None,
                 tools: list[dict] | None = None,
                 on_tool=None) -> str:
        """One reply. When `tools` are offered and the model calls one, we run
        it through `on_tool(name, args) -> str` and give the model one more
        pass to fold the result into its words. A model or client that can't
        do tools just degrades to a plain conversational reply."""
        if self._client is None:
            return self._fallback(system_prompt, user_msg)
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_msg})
        try:
            if tools and on_tool:
                try:
                    resp = self._chat(messages, tools=tools)
                except Exception:
                    # Older client/model without tool support -- plain chat.
                    resp = self._chat(messages)
                msg = resp["message"]
                calls = msg.get("tool_calls") or []
                if calls:
                    messages.append(msg)
                    for call in calls:
                        fn = call.get("function", {})
                        result = on_tool(fn.get("name", ""), fn.get("arguments") or {})
                        messages.append({"role": "tool", "content": str(result)})
                    resp = self._chat(messages)
                    msg = resp["message"]
                return strip_think(msg["content"])
            resp = self._chat(messages)
            return strip_think(resp["message"]["content"])
        except Exception as exc:
            # Model not pulled, server down mid-call, etc. -- stay alive.
            return self._fallback(system_prompt, user_msg, error=str(exc))

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
        # When she last spoke unprompted, for the proactive cooldown.
        self._last_volunteer_ts: float = 0.0
        # When the person last said something -- idle chatter waits for quiet.
        # Starts at "now" so she doesn't pounce the moment the server boots.
        self._last_user_ts: float = time.time()
        # When she last reflected (her fourth directive, running).
        self._last_reflect_ts: float = time.time()
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
        self.state = self.state.update_fear(prediction_error(self._prev_obs, obs))
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

    def chat(self, user_msg: str, situation: str = "",
             image_desc: str | None = None) -> dict:
        """Run one conversational turn and return a structured result the UI can
        render: the reply plus the resulting mood (so the avatar can react).

        `image_desc` is what the vision model saw in an image the person
        attached this turn (or None). It's woven into the prompt as something
        she actually saw, and remembered like any other shared moment."""
        self._last_user_ts = time.time()
        # Recall relevant memories for this message.
        memories = memory_store.recall(user_msg)

        # Alpecca reads its own real state before speaking, so it can reflect on
        # itself honestly within the reply.
        self_report = self.introspect()

        # Ambient sight enriches the situation beyond the window title.
        if self._sight:
            situation = (situation + "; " if situation else "") + \
                f"on their screen you can see: {self._sight}"

        # Generate a reply conditioned on mood + memory + situation + self-knowledge.
        system_prompt = prompts.build_system_prompt(
            self.state, memories, situation, self_narration=self_report.narrate(),
            image_seen=image_desc or "", abilities=self.actuator.describe(),
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
            "memories_used": [m["content"] for m in memories],
            "self_reflection": self_report.narrate(),
            "appearance": self.current_appearance().as_dict(),
            "llm_online": self.llm.online,
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
                situation=self._sight or self._last_situation,
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
        reply = self.llm.generate(system_prompt, "(say it in your own words)")
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

        The musing is stored as a memory of kind "musing", so it joins recall
        and can later seed chatter -- her inner life genuinely compounds
        rather than evaporating. Without a model (or without memories) she
        skips quietly; reflection is never worth faking."""
        if not self.llm.online:
            return None
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
        musing = self.llm.generate(system_prompt, "(think freely)")
        if musing:
            memory_store.remember(
                f"While reflecting on my own, I thought: {musing}",
                kind="musing", salience=ReflectionCfg.MUSING_SALIENCE,
            )
        return musing or None
