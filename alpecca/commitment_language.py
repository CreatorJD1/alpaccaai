"""Pure enforcement for action and completion language.

Phase 4 callers can use this module after reply generation and before delivery.
It never creates commitments or receipts; it only keeps language aligned with a
supplied, already-grounded commitment and receipt state.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Mapping


CommitmentStatus = Literal[
    "proposed",
    "approved",
    "approval-pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "unavailable",
]
ClaimKind = Literal["completion", "future-action"]

MAX_REPLY_CHARS = 8_000
MAX_CLAIMS = 24
MAX_ACTION_CHARS = 160
_STATUSES = frozenset({
    "proposed",
    "approved",
    "approval-pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "unavailable",
})

_SENTENCE = re.compile(r"[^.!?]+(?:[.!?]+|$)")
_INTRINSIC_EXTERNAL_COMPLETION_VERBS = (
    r"uploaded|downloaded|deleted|installed|restarted|deployed|launched|"
    r"published|pushed|merged|scheduled"
)
_TARGETED_COMPLETION_VERBS = (
    r"completed|finished|sent|created|saved|updated|opened|closed|fixed|"
    r"implemented|deployed|ran|executed|uploaded|downloaded|deleted|moved|"
    r"wrote|changed|installed|started|stopped|restarted|launched|published|"
    r"committed|pushed|merged|scheduled"
)
_TARGETED_COMPLETION_BASE_VERBS = (
    r"complete|finish|send|create|save|update|open|close|fix|implement|"
    r"deploy|run|execute|upload|download|delete|move|write|change|install|"
    r"start|stop|restart|launch|publish|commit|push|merge|schedule"
)
_EXTERNAL_ACTION_TARGETS = (
    r"file|document|report|upload|download|export|import|archive|app|"
    r"application|program|server|service|process|task|job|terminal|window|"
    r"browser|page|link|folder|directory|repository|repo|project|connection|"
    r"channel|session|deployment|build|test|update|installation|install|"
    r"database|record|message|email|request|issue|ticket|commit|merge|"
    r"pipeline|workflow|configuration|config|settings?|port|tunnel|stream|"
    r"recording|image|video|audio|model|asset|package|launcher"
)
_COMPLETION = re.compile(
    rf"\b(?:"
    rf"i\s+(?:have\s+)?(?:{_INTRINSIC_EXTERNAL_COMPLETION_VERBS})"
    rf"|i\s+did\s+(?:upload|download|delete|install|restart|deploy|launch|"
    rf"publish|push|merge|schedule)"
    rf"|i(?:'|\u2019)ve\s+(?:{_INTRINSIC_EXTERNAL_COMPLETION_VERBS})"
    rf"|(?:it|this|that)\s+(?:is|was)\s+(?:complete|completed|done|finished)"
    rf")\b",
    re.IGNORECASE,
)
_TARGETED_COMPLETION = re.compile(
    rf"\b(?:"
    rf"i\s+(?:have\s+)?(?:{_TARGETED_COMPLETION_VERBS})"
    rf"|i\s+did\s+(?:{_TARGETED_COMPLETION_BASE_VERBS})"
    rf"|i(?:'|\u2019)ve\s+(?:{_TARGETED_COMPLETION_VERBS}|done)"
    rf")\s+(?:"
    rf"it|them|(?:(?:the|a|an|this|that|your|my|our)\s+)?"
    rf"(?:{_EXTERNAL_ACTION_TARGETS})s?"
    rf")\b",
    re.IGNORECASE,
)
_BARE_COMPLETION = re.compile(r"^\s*(?:done|complete|completed|finished)\s*[.!?]*\s*$", re.IGNORECASE)
_FUTURE_ACTION_VERBS = (
    rf"{_TARGETED_COMPLETION_BASE_VERBS}|prepare|inspect|check|review|read|"
    rf"archive|export|import|build|test|configure|connect|disconnect|do"
)
_FUTURE_INTRINSIC_EXTERNAL_VERBS = (
    r"upload|download|delete|install|restart|deploy|launch|publish|"
    r"push|merge|schedule"
)
_FUTURE_ACTION = re.compile(
    rf"\b(?:i\s+will|i(?:'|\u2019)ll|i\s+am\s+going\s+to|"
    rf"i(?:'|\u2019)m\s+going\s+to)\s+(?:"
    rf"(?:{_FUTURE_INTRINSIC_EXTERNAL_VERBS})\b"
    rf"|(?:{_FUTURE_ACTION_VERBS})\s+"
    rf"(?:(?:you|him|her)\s+)?(?:"
    rf"it|them|this|that|(?:(?:the|a|an|this|that|your|my|our)\s+)?"
    rf"(?:{_EXTERNAL_ACTION_TARGETS})s?"
    rf"))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CommitmentReceiptState:
    """The bounded evidence needed to permit completion wording."""

    status: CommitmentStatus = "unavailable"
    receipt_status: str = "unavailable"
    receipt_id: str = ""
    action: str = ""

    @property
    def has_successful_receipt(self) -> bool:
        return (
            self.status == "succeeded"
            and self.receipt_status == "succeeded"
            and bool(self.receipt_id)
        )


@dataclass(frozen=True, slots=True)
class ActionClaim:
    """One bounded action-language classification from an assistant reply."""

    kind: ClaimKind
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ClaimAnalysis:
    text: str
    truncated: bool
    claims: tuple[ActionClaim, ...]


@dataclass(frozen=True, slots=True)
class CommitmentLanguageResult:
    """The classified reply and any status-grounded rewrite."""

    reply: str
    original: str
    truncated: bool
    claims: tuple[ActionClaim, ...]
    state: CommitmentReceiptState
    rewritten: bool


def _clean_text(value: object, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _normalize_status(value: object) -> CommitmentStatus:
    status = str(value or "").strip().lower().replace("_", "-")
    return status if status in _STATUSES else "unavailable"


def coerce_commitment_receipt_state(
    state: CommitmentReceiptState | Mapping[str, object] | None,
) -> CommitmentReceiptState:
    """Normalize an in-memory state object without any storage access."""

    if isinstance(state, CommitmentReceiptState):
        source: Mapping[str, object] = {
            "status": state.status,
            "receipt_status": state.receipt_status,
            "receipt_id": state.receipt_id,
            "action": state.action,
        }
    elif isinstance(state, Mapping):
        source = state
    else:
        source = {}
    receipt = source.get("receipt")
    receipt_data = receipt if isinstance(receipt, Mapping) else {}
    return CommitmentReceiptState(
        status=_normalize_status(source.get("status")),
        receipt_status=_normalize_status(
            source.get("receipt_status", receipt_data.get("status"))
        ),
        receipt_id=_clean_text(
            source.get("receipt_id", receipt_data.get("id", "")), MAX_ACTION_CHARS
        ),
        action=_clean_text(source.get("action", source.get("name", "")), MAX_ACTION_CHARS),
    )


def classify_action_claims(reply: str, *, max_chars: int = MAX_REPLY_CHARS) -> ClaimAnalysis:
    """Classify bounded completion and future-action claims in one reply."""

    if not isinstance(reply, str):
        raise TypeError("reply must be a string")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    limit = min(max_chars, MAX_REPLY_CHARS)
    truncated = len(reply) > limit
    text = reply[:limit]
    claims: list[ActionClaim] = []
    for match in _SENTENCE.finditer(text):
        if len(claims) >= MAX_CLAIMS:
            break
        sentence = match.group(0)
        leading = len(sentence) - len(sentence.lstrip())
        start = match.start() + leading
        end = match.end()
        candidate = sentence.strip()
        if (
            _COMPLETION.search(candidate)
            or _TARGETED_COMPLETION.search(candidate)
            or _BARE_COMPLETION.fullmatch(candidate)
        ):
            kind: ClaimKind = "completion"
        elif _FUTURE_ACTION.search(candidate):
            kind = "future-action"
        else:
            continue
        claims.append(ActionClaim(
            kind=kind,
            text=candidate[:MAX_ACTION_CHARS],
            start=start,
            end=end,
        ))
    return ClaimAnalysis(text=text, truncated=truncated, claims=tuple(claims))


def _action_label(state: CommitmentReceiptState) -> str:
    return state.action or "this action"


def _status_rewrite(state: CommitmentReceiptState) -> str:
    action = _action_label(state)
    subject = action[:1].upper() + action[1:]
    if state.status == "proposed":
        return f"I have proposed {action}, but it has not been approved or run."
    if state.status == "approved":
        return f"{subject} is approved, but no successful receipt confirms completion."
    if state.status == "approval-pending":
        return f"{subject} is pending approval, so I cannot confirm it is complete."
    if state.status == "running":
        return f"{subject} is running, so I cannot confirm it is complete yet."
    if state.status == "succeeded":
        return f"I cannot confirm {action} is complete because no successful receipt is available."
    if state.status == "failed":
        return f"{subject} failed, so I cannot confirm it is complete."
    if state.status == "cancelled":
        return f"{subject} was cancelled, so I cannot confirm it is complete."
    return f"{subject} is unavailable, so I cannot confirm it is complete."


def enforce_commitment_language(
    reply: str,
    state: CommitmentReceiptState | Mapping[str, object] | None,
    *,
    max_chars: int = MAX_REPLY_CHARS,
) -> CommitmentLanguageResult:
    """Rewrite completion claims that lack a successful receipt.

    Future-action claims remain valid for approved or running commitments. A
    proposal is pending rather than immediate, so its future claim is rewritten
    to proposal wording. Terminally unavailable claims are grounded as before.
    """

    analysis = classify_action_claims(reply, max_chars=max_chars)
    normalized = coerce_commitment_receipt_state(state)
    pieces: list[str] = []
    cursor = 0
    rewritten = False
    for claim in analysis.claims:
        unsupported_completion = (
            claim.kind == "completion" and not normalized.has_successful_receipt
        )
        unsupported_future_action = (
            claim.kind == "future-action"
            and normalized.status in {
                "proposed", "failed", "cancelled", "unavailable",
            }
        )
        if not (unsupported_completion or unsupported_future_action):
            continue
        pieces.append(analysis.text[cursor:claim.start])
        pieces.append(_status_rewrite(normalized))
        cursor = claim.end
        rewritten = True
    rewritten_reply = "".join([*pieces, analysis.text[cursor:]]) if rewritten else analysis.text
    return CommitmentLanguageResult(
        reply=rewritten_reply,
        original=analysis.text,
        truncated=analysis.truncated,
        claims=analysis.claims,
        state=normalized,
        rewritten=rewritten,
    )


def rewrite_unsupported_completion_language(
    reply: str,
    state: CommitmentReceiptState | Mapping[str, object] | None,
    *,
    max_chars: int = MAX_REPLY_CHARS,
) -> CommitmentLanguageResult:
    """Explicit alias for callers that only need completion-language enforcement."""

    return enforce_commitment_language(reply, state, max_chars=max_chars)


__all__ = [
    "ActionClaim",
    "ClaimAnalysis",
    "ClaimKind",
    "CommitmentLanguageResult",
    "CommitmentReceiptState",
    "CommitmentStatus",
    "MAX_ACTION_CHARS",
    "MAX_CLAIMS",
    "MAX_REPLY_CHARS",
    "classify_action_claims",
    "coerce_commitment_receipt_state",
    "enforce_commitment_language",
    "rewrite_unsupported_completion_language",
]
