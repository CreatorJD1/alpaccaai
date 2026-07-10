"""Pure, bounded conversational cue extraction for one message.

This module deliberately does not decide what Alpecca should do. It only turns
small, explicit textual evidence into a structured envelope that later phases
can use when resolving context, commitments, and actions.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Pattern


CueKind = Literal[
    "correction",
    "confirmation",
    "reference",
    "urgency",
    "distress",
    "question",
    "action_intent",
]

MAX_MESSAGE_CHARS = 4096
MAX_EVIDENCE_PER_CUE = 2
MAX_EVIDENCE_CHARS = 120
MAX_SIGNAL_MATCHES = 8


@dataclass(frozen=True, slots=True)
class CueSignal:
    """One grounded cue and the message fragments that support it."""

    kind: CueKind
    detected: bool
    confidence: float
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "detected": self.detected,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class CueEnvelope:
    """Bounded cue evidence extracted from exactly one input message."""

    text: str
    truncated: bool
    correction: CueSignal
    confirmation: CueSignal
    reference: CueSignal
    urgency: CueSignal
    distress: CueSignal
    question: CueSignal
    action_intent: CueSignal

    @property
    def active_kinds(self) -> tuple[CueKind, ...]:
        return tuple(
            signal.kind
            for signal in self.signals
            if signal.detected
        )

    @property
    def signals(self) -> tuple[CueSignal, ...]:
        return (
            self.correction,
            self.confirmation,
            self.reference,
            self.urgency,
            self.distress,
            self.question,
            self.action_intent,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "truncated": self.truncated,
            "active_kinds": list(self.active_kinds),
            "cues": {signal.kind: signal.as_dict() for signal in self.signals},
        }


PatternSpec = tuple[Pattern[str], float]


def _patterns(*items: tuple[str, float]) -> tuple[PatternSpec, ...]:
    return tuple((re.compile(pattern, re.IGNORECASE), confidence) for pattern, confidence in items)


_CORRECTION = _patterns(
    (r"\b(?:no[,;:]?\s+)?i\s+(?:meant|said|asked for)\b", 0.96),
    (r"\b(?:actually|correction:|to correct that)\b", 0.82),
    (r"\b(?:that|this|it)\s+(?:is|was)(?:n't|\s+not)\s+(?:right|correct)\b", 0.94),
    (r"\bnot\s+[^.!?;]{1,48}\s+but\s+[^.!?;]{1,48}", 0.88),
    (r"^\s*no(?:[,.!]|$)", 0.64),
)

_CONFIRMATION = _patterns(
    (r"(?:^|[.!?]\s*)\s*(?:yes|yeah|yep|exactly|confirmed|agreed|correct)\s*(?:[,.!?]|$)", 0.91),
    (r"\b(?:that's|that is)\s+(?:right|correct)\b", 0.94),
    (r"\b(?:sounds good|go ahead|please proceed)\b", 0.84),
)

_REFERENCE = _patterns(
    (r"\b(?:previous|earlier|above|last)\s+(?:message|reply|one|file|image|photo|plan|request|document)\b", 0.94),
    (r"\b(?:the|that|this)\s+(?:file|image|photo|screenshot|link|plan|document|model|message)\b", 0.82),
    (r"\b(?:same|former|latter)\s+(?:one|thing|file|plan|model)\b", 0.78),
    (r"\b(?:this|that|it|those|these)\b", 0.54),
)

_URGENCY = _patterns(
    (r"\b(?:urgent|urgently|asap|immediately|right now|without delay|time[- ]sensitive)\b", 0.94),
    (r"\b(?:hurry|quickly|as soon as possible)\b", 0.84),
    (r"!{2,}", 0.62),
)

_DISTRESS = _patterns(
    # Generic assistance language remains a detected but low-confidence cue;
    # it becomes a support posture only when stronger distress evidence also
    # appears in the same message.
    (r"\b(?:help me|i need help|please help)\b", 0.55),
    (r"\b(?:i(?:'m| am)\s+(?:scared|afraid|overwhelmed|panicking|unsafe)|i feel unsafe)\b", 0.96),
    (r"\b(?:emergency|in danger|can't breathe|cannot breathe|having a panic attack)\b", 0.99),
    (r"\b(?:i can't cope|i cannot cope|i'm not okay|i am not okay)\b", 0.93),
)

_QUESTION = _patterns(
    (r"\?", 0.98),
    (r"^\s*(?:who|what|when|where|why|how|which|can|could|would|will|is|are|am|do|does|did|should|may)\b", 0.82),
)

_ACTION_INTENT = _patterns(
    (r"\b(?:can|could|would|will)\s+you\b", 0.94),
    (r"\bi\s+(?:need|want|would like)\s+you\s+to\b", 0.95),
    (r"\bplease\s+[a-z][a-z'-]*\b", 0.88),
    (r"(?:^|[.!?]\s*)(?:go ahead|do it|proceed|continue|resume|stop|cancel)\b", 0.91),
    (
        r"^\s*(?:add|remove|update|correct|create|make|build|run|check|review|inspect|open|close|send|upload|download|move|change|fix|implement|test|show|tell|explain|find|search|use|keep|start|stop|continue|resume|delete)\b",
        0.86,
    ),
    (r"\bi(?:'ll|\s+will|\s+am going to)\s+[a-z][a-z'-]*\b", 0.76),
)


def _evidence_snippet(text: str, start: int, end: int) -> str:
    budget = MAX_EVIDENCE_CHARS - 6
    match_midpoint = (start + end) // 2
    left = max(0, match_midpoint - budget // 2)
    right = min(len(text), left + budget)
    left = max(0, right - budget)
    fragment = text[left:right].strip()
    if left > 0:
        fragment = "..." + fragment
    if right < len(text):
        fragment += "..."
    return fragment[:MAX_EVIDENCE_CHARS]


def _extract_signal(kind: CueKind, text: str, specs: tuple[PatternSpec, ...]) -> CueSignal:
    candidates: dict[str, float] = {}
    match_count = 0
    for pattern, confidence in specs:
        for match in pattern.finditer(text):
            snippet = _evidence_snippet(text, match.start(), match.end())
            candidates[snippet] = max(confidence, candidates.get(snippet, 0.0))
            match_count += 1
            if match_count >= MAX_SIGNAL_MATCHES:
                break
        if match_count >= MAX_SIGNAL_MATCHES:
            break
    if not candidates:
        return CueSignal(kind=kind, detected=False, confidence=0.0)
    matches = sorted(
        ((confidence, snippet) for snippet, confidence in candidates.items()),
        key=lambda item: (-item[0], item[1]),
    )[:MAX_EVIDENCE_PER_CUE]
    confidence = min(0.99, matches[0][0] + 0.03 * (len(matches) - 1))
    return CueSignal(
        kind=kind,
        detected=True,
        confidence=round(confidence, 3),
        evidence=tuple(item[1] for item in matches),
    )


def parse_cue_envelope(message: str, *, max_chars: int = MAX_MESSAGE_CHARS) -> CueEnvelope:
    """Parse one message into deterministic cues without I/O or model calls."""

    if not isinstance(message, str):
        raise TypeError("message must be a string")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    limit = min(max_chars, MAX_MESSAGE_CHARS)
    truncated = len(message) > limit
    text = " ".join(message[:limit].split())
    return CueEnvelope(
        text=text,
        truncated=truncated,
        correction=_extract_signal("correction", text, _CORRECTION),
        confirmation=_extract_signal("confirmation", text, _CONFIRMATION),
        reference=_extract_signal("reference", text, _REFERENCE),
        urgency=_extract_signal("urgency", text, _URGENCY),
        distress=_extract_signal("distress", text, _DISTRESS),
        question=_extract_signal("question", text, _QUESTION),
        action_intent=_extract_signal("action_intent", text, _ACTION_INTENT),
    )


def parse_cues(message: str, *, max_chars: int = MAX_MESSAGE_CHARS) -> CueEnvelope:
    """Compatibility-friendly short name for :func:`parse_cue_envelope`."""

    return parse_cue_envelope(message, max_chars=max_chars)


__all__ = [
    "CueEnvelope",
    "CueKind",
    "CueSignal",
    "MAX_EVIDENCE_CHARS",
    "MAX_EVIDENCE_PER_CUE",
    "MAX_MESSAGE_CHARS",
    "parse_cue_envelope",
    "parse_cues",
]
