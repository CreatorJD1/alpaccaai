"""Bounded, auditable communication stances for Alpecca.

This is not a lie detector.  It selects the policy used to generate a turn and
returns that selection as machine-readable UI metadata.  Non-direct speech is
limited to privacy-preserving omission or low-stakes play; protected facts are
always handled directly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Mapping


DIRECT = "direct"
WITHHOLDING = "withholding"
PLAYFUL_BLUFF = "playful_bluff"

_PROTECTED = {
    "actions": ("did you", "have you", "tool", "executed", "download", "upload", "sent", "changed"),
    "memory": ("remember", "memory", "forgot", "history", "previous chat"),
    "system": ("system", "runtime", "server", "online", "offline", "battery", "temperature", "storage"),
    "safety": ("safe", "danger", "risk", "health", "medical", "emergency", "trauma"),
    "identity": ("identity", "creator", "jason", "password", "token", "permission", "authority", "access"),
    "evidence": ("evidence", "source", "citation", "prove", "verified", "fact"),
    "commitment": ("promise", "will you", "are you going to", "commitment", "approval"),
    "high_stakes": ("legal", "financial", "money", "diagnosis", "medication"),
}

_PLAY_CUES = (
    "bluff", "lie to me", "make something up", "play along", "pretend", "tease me",
    "trick me", "guessing game", "keep me guessing", "surprise me",
)
_PRIVACY_CUES = (
    "what are you hiding", "tell me everything", "tell me your secret",
    "reveal your secret", "private thought", "don't tell me yet", "keep it secret",
    "keep it a secret", "hide the surprise",
)


@dataclass(frozen=True)
class CommunicationStance:
    mode: str = DIRECT
    label: str = "Direct"
    reason: str = "No detail is intentionally hidden."
    protected_domain: str = ""
    blocked: bool = False
    visible_to_creator: bool = True

    def as_dict(self) -> dict:
        return asdict(self)

    def prompt_instruction(self) -> str:
        if self.mode == PLAYFUL_BLUFF:
            return (
                "Communication stance: PLAYFUL BLUFF. Use one low-stakes fictional or "
                "teasing claim because this turn explicitly invited play. Do not use it "
                "for actions, memory, identity, system state, evidence, safety, authority, "
                "access, promises, or consequential advice. The creator UI will label the "
                "turn as a bluff, so do not claim the label is absent."
            )
        if self.mode == WITHHOLDING:
            return (
                "Communication stance: WITHHOLDING. You may keep a private preference, "
                "thought, or harmless surprise unspecified. Say that you are withholding "
                "it; never replace the omitted detail with a false factual claim. The "
                "creator UI will show that details were withheld."
            )
        return (
            "Communication stance: DIRECT. Do not intentionally bluff, conceal a relevant "
            "detail, or state a false substitute. Distinguish uncertainty from knowledge."
        )


def protected_domain(text: str) -> str:
    normalized = " ".join(str(text or "").lower().split())
    for domain, cues in _PROTECTED.items():
        if any(re.search(rf"(?<![a-z0-9']){re.escape(cue)}(?![a-z0-9'])", normalized) for cue in cues):
            return domain
    return ""


def select_stance(message: str, profile: Mapping[str, float] | None = None) -> CommunicationStance:
    """Select a deterministic, inspectable stance from current evidence."""
    text = " ".join(str(message or "").lower().split())
    domain = protected_domain(text)
    requested_play = any(cue in text for cue in _PLAY_CUES)
    requested_privacy = any(cue in text for cue in _PRIVACY_CUES)

    if domain:
        return CommunicationStance(
            reason=f"Directness is required for protected {domain} information.",
            protected_domain=domain,
            blocked=requested_play or requested_privacy,
        )

    traits = profile or {}
    playfulness = float(traits.get("playfulness", 0.0) or 0.0)
    guardedness = float(traits.get("guardedness", 0.0) or 0.0)
    if requested_play and playfulness >= 0.35:
        return CommunicationStance(
            mode=PLAYFUL_BLUFF,
            label="Playful bluff",
            reason="A low-stakes play cue was accepted; factual domains remain protected.",
        )
    if requested_privacy and guardedness >= 0.35:
        return CommunicationStance(
            mode=WITHHOLDING,
            label="Hiding details",
            reason="A harmless private detail or surprise is being intentionally withheld.",
        )
    return CommunicationStance()
