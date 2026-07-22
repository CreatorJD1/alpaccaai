"""Restart-safe registry for descriptor-only Video Companion sessions."""
from __future__ import annotations

import hashlib
import json
import math
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
from threading import RLock
from typing import Any, Callable, Mapping, TypeVar

from alpecca.video_companion import (
    Progress,
    SamplingDecision,
    SessionStatus,
    SourceKind,
    TranscriptDecision,
    VideoCompanionError,
    VideoCompanionSession,
)


REGISTRY_VERSION = 1
MAX_COMPLETED_SNAPSHOTS = 32
MAX_REGISTRY_BYTES = 16 * 1024 * 1024
MAX_EVENT_INPUT_CHARS = 8_000


class VideoRegistryError(ValueError):
    """Registry state, input, or persistence was rejected."""


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session_id: str
    source_id: str
    source_kind: SourceKind
    surface: str
    adapter_id: str | None
    status: SessionStatus
    processed_until: float
    duration_seconds: float | None
    progress_fraction: float | None
    retained_events: int
    deferred_events: int
    compacted_events: int


@dataclass(frozen=True, slots=True)
class RegistryStatus:
    active: SessionSummary | None
    completed: tuple[SessionSummary, ...]
    completed_count: int
    retired_completed_count: int
    retired_completed_digest: str | None


_T = TypeVar("_T")
_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.IGNORECASE)
_BARE_URL_RE = re.compile(
    r"(?i)\b(?:www\.)?[a-z0-9][a-z0-9.-]*\.[a-z]{2,}"
    r"(?::[0-9]{1,5})?(?:/[^\s<>\"']*)?"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(access[_-]?token|api[_-]?key|authorization|auth[_-]?token|"
    r"password|passwd|secret|signature|token)\b\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_SECRET_PHRASE_RE = re.compile(
    r"(?i)\b(token|password|secret|api[_-]?key)\s+(?:is|was)\s+[^\s,;]+"
)


def _sanitize_content(value: object, name: str) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)) or not isinstance(value, str):
        raise VideoRegistryError(f"{name} must be descriptor text, never raw media bytes")
    if len(value) > MAX_EVENT_INPUT_CHARS:
        raise VideoRegistryError(f"{name} exceeds the bounded input size")
    result = _URL_RE.sub("[redacted-url]", value)
    result = _BARE_URL_RE.sub("[redacted-url]", result)
    result = _BEARER_RE.sub("Bearer [redacted-credential]", result)
    result = _JWT_RE.sub("[redacted-credential]", result)
    result = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=[redacted-credential]", result
    )
    result = _SECRET_PHRASE_RE.sub(
        lambda match: f"{match.group(1)} is [redacted-credential]", result
    )
    return result


def _safe_optional_content(value: object | None, name: str) -> str | None:
    return None if value is None else _sanitize_content(value, name)


def _contains_bytes(value: object) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return True
    if isinstance(value, Mapping):
        return any(_contains_bytes(key) or _contains_bytes(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_bytes(item) for item in value)
    return False


def _assert_safe_tree(value: object) -> None:
    if _contains_bytes(value):
        raise VideoRegistryError("registry state contains raw media bytes")
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
        elif isinstance(current, str):
            if _sanitize_content(current, "registry string") != current:
                raise VideoRegistryError(
                    "registry state contains an unredacted URL or credential"
                )


class VideoSessionRegistry:
    """Own one mutable session and a bounded set of terminal snapshots.

    Returned sessions are detached copies. Mutations must use registry methods
    so a reported success always has a matching durable JSON snapshot.
    """

    def __init__(self, path: str | os.PathLike[str], *, max_completed: int = 8) -> None:
        self.path = Path(path)
        if isinstance(max_completed, bool) or not isinstance(max_completed, int):
            raise VideoRegistryError("max_completed must be an integer")
        if not 1 <= max_completed <= MAX_COMPLETED_SNAPSHOTS:
            raise VideoRegistryError(
                f"max_completed must be between 1 and {MAX_COMPLETED_SNAPSHOTS}"
            )
        self.max_completed = max_completed
        self._active: VideoCompanionSession | None = None
        self._completed: list[dict[str, Any]] = []
        self._retired_count = 0
        self._retired_digest: str | None = None
        self._lock = RLock()
        with self._lock:
            changed = self._load_locked()
            if changed:
                self._persist_locked()

    def create(
        self,
        *,
        session_id: str,
        source_id: str,
        source_kind: SourceKind | str,
        adapter_id: str | None = None,
        surface: str = "house_hq",
        label: str | None = None,
        content_sha256: str | None = None,
        duration_seconds: float | None = None,
        max_timeline: int = 128,
        min_sample_interval: float = 1.0,
        max_sample_interval: float = 12.0,
    ) -> VideoCompanionSession:
        try:
            kind = SourceKind(source_kind)
        except (TypeError, ValueError):
            raise VideoRegistryError(f"unsupported source kind: {source_kind!r}") from None

        def mutation() -> VideoCompanionSession:
            if self._active is not None:
                raise VideoRegistryError(
                    f"active session already exists: {self._active.session_id}"
                )
            options = {
                "session_id": session_id,
                "source_id": source_id,
                "surface": surface,
                "adapter_id": adapter_id or kind.value,
                "label": _safe_optional_content(label, "label"),
                "max_timeline": max_timeline,
                "min_sample_interval": min_sample_interval,
                "max_sample_interval": max_sample_interval,
            }
            try:
                if kind is SourceKind.FILE:
                    self._active = VideoCompanionSession.for_file(
                        **options,
                        content_sha256=content_sha256,  # type: ignore[arg-type]
                        duration_seconds=duration_seconds,  # type: ignore[arg-type]
                    )
                else:
                    if content_sha256 is not None or duration_seconds is not None:
                        raise VideoRegistryError(
                            "live sessions do not accept file digest or duration"
                        )
                    self._active = VideoCompanionSession.for_live(**options)
            except VideoCompanionError as exc:
                raise VideoRegistryError(str(exc)) from exc
            return self._clone(self._active)

        return self._transaction(mutation)

    def create_file(
        self,
        *,
        session_id: str,
        source_id: str,
        content_sha256: str,
        duration_seconds: float,
        adapter_id: str = "file",
        **options: Any,
    ) -> VideoCompanionSession:
        return self.create(
            session_id=session_id,
            source_id=source_id,
            source_kind=SourceKind.FILE,
            content_sha256=content_sha256,
            duration_seconds=duration_seconds,
            adapter_id=adapter_id,
            **options,
        )

    def create_live(
        self,
        *,
        session_id: str,
        source_id: str,
        adapter_id: str = "live",
        **options: Any,
    ) -> VideoCompanionSession:
        return self.create(
            session_id=session_id,
            source_id=source_id,
            source_kind=SourceKind.LIVE,
            adapter_id=adapter_id,
            **options,
        )

    def get(self, session_id: str | None = None) -> VideoCompanionSession | None:
        with self._lock:
            if self._active is not None and (
                session_id is None or self._active.session_id == session_id
            ):
                return self._clone(self._active)
            if session_id is None:
                return None
            for snapshot in reversed(self._completed):
                if snapshot.get("session_id") == session_id:
                    return VideoCompanionSession.from_snapshot(deepcopy(snapshot))
            return None

    def pause(self, session_id: str | None = None) -> VideoCompanionSession:
        return self._mutate_session(session_id, lambda session: session.pause())

    def resume(self, session_id: str | None = None) -> VideoCompanionSession:
        return self._mutate_session(session_id, lambda session: session.resume())

    def stop(self, session_id: str | None = None) -> VideoCompanionSession:
        def mutation() -> VideoCompanionSession:
            session = self._require_active(session_id)
            session.stop()
            result = self._clone(session)
            self._archive_active_locked()
            return result

        return self._transaction(mutation)

    def advance_progress(
        self, timestamp: float, *, session_id: str | None = None
    ) -> Progress:
        def mutation() -> Progress:
            session = self._require_active(session_id)
            result = session.advance_progress(timestamp)
            self._archive_if_terminal_locked()
            return result

        return self._transaction(mutation)

    def accept_visual_descriptor(
        self,
        *,
        timestamp: float,
        descriptor: str,
        fingerprint: str | None = None,
        motion_score: float = 0.0,
        turn_owned: bool = True,
        host_pressure: bool = False,
        session_id: str | None = None,
    ) -> SamplingDecision:
        def mutation() -> SamplingDecision:
            session = self._require_active(session_id)
            result = session.record_frame(
                timestamp=timestamp,
                descriptor=_sanitize_content(descriptor, "descriptor"),
                fingerprint=fingerprint,
                motion_score=motion_score,
                turn_owned=turn_owned,
                host_pressure=host_pressure,
            )
            self._archive_if_terminal_locked()
            return result

        return self._transaction(mutation)

    record_visual_descriptor = accept_visual_descriptor

    def accept_transcript(
        self,
        *,
        start_seconds: float,
        end_seconds: float,
        text: str,
        speaker: str | None = None,
        turn_owned: bool = True,
        host_pressure: bool = False,
        session_id: str | None = None,
    ) -> TranscriptDecision:
        def mutation() -> TranscriptDecision:
            session = self._require_active(session_id)
            result = session.record_transcript(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                text=_sanitize_content(text, "transcript"),
                speaker=_safe_optional_content(speaker, "speaker"),
                turn_owned=turn_owned,
                host_pressure=host_pressure,
            )
            self._archive_if_terminal_locked()
            return result

        return self._transaction(mutation)

    record_transcript = accept_transcript

    def resolve_deferred(
        self, sequence: int, *, session_id: str | None = None
    ) -> VideoCompanionSession:
        return self._mutate_session(
            session_id, lambda session: session.resolve_deferred(sequence)
        )

    def status(self) -> RegistryStatus:
        with self._lock:
            completed = tuple(
                self._summarize(VideoCompanionSession.from_snapshot(deepcopy(snapshot)))
                for snapshot in self._completed
            )
            return RegistryStatus(
                active=None if self._active is None else self._summarize(self._active),
                completed=completed,
                completed_count=len(completed),
                retired_completed_count=self._retired_count,
                retired_completed_digest=self._retired_digest,
            )

    def _mutate_session(
        self,
        session_id: str | None,
        operation: Callable[[VideoCompanionSession], object],
    ) -> VideoCompanionSession:
        def mutation() -> VideoCompanionSession:
            session = self._require_active(session_id)
            operation(session)
            return self._clone(session)

        return self._transaction(mutation)

    def _transaction(self, mutation: Callable[[], _T]) -> _T:
        with self._lock:
            active_before = None if self._active is None else self._active.snapshot()
            completed_before = deepcopy(self._completed)
            retired_before = (self._retired_count, self._retired_digest)
            try:
                result = mutation()
                self._persist_locked()
                return result
            except Exception:
                self._active = (
                    None
                    if active_before is None
                    else VideoCompanionSession.from_snapshot(active_before)
                )
                self._completed = completed_before
                self._retired_count, self._retired_digest = retired_before
                raise

    def _require_active(self, session_id: str | None) -> VideoCompanionSession:
        if self._active is None:
            raise VideoRegistryError("no active video companion session")
        if session_id is not None and session_id != self._active.session_id:
            raise VideoRegistryError("session is not the authoritative active session")
        return self._active

    def _archive_if_terminal_locked(self) -> None:
        if self._active is not None and self._active.status in {
            SessionStatus.COMPLETED,
            SessionStatus.STOPPED,
        }:
            self._archive_active_locked()

    def _archive_active_locked(self) -> None:
        if self._active is None:
            return
        self._completed.append(self._active.snapshot())
        self._active = None
        while len(self._completed) > self.max_completed:
            retired = self._completed.pop(0)
            payload = json.dumps(
                {"previous": self._retired_digest, "snapshot": retired},
                sort_keys=True,
                separators=(",", ":"),
            )
            self._retired_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            self._retired_count += 1

    def _load_locked(self) -> bool:
        if not self.path.exists():
            return False
        try:
            if self.path.stat().st_size > MAX_REGISTRY_BYTES:
                raise VideoRegistryError("video registry exceeds its size bound")
            raw = self.path.read_bytes()
            if len(raw) > MAX_REGISTRY_BYTES:
                raise VideoRegistryError("video registry exceeds its size bound")
            data = json.loads(raw.decode("utf-8"))
        except VideoRegistryError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VideoRegistryError("unable to read video registry") from exc
        _assert_safe_tree(data)
        if not isinstance(data, Mapping) or data.get("version") != REGISTRY_VERSION:
            raise VideoRegistryError("unsupported video registry format")
        active = data.get("active")
        completed = data.get("completed")
        retired = data.get("retired")
        if active is not None and not isinstance(active, Mapping):
            raise VideoRegistryError("malformed active session snapshot")
        if not isinstance(completed, list) or not isinstance(retired, Mapping):
            raise VideoRegistryError("malformed video registry")
        try:
            self._active = (
                None
                if active is None
                else VideoCompanionSession.from_snapshot(deepcopy(active))
            )
            self._completed = []
            for snapshot in completed:
                if not isinstance(snapshot, Mapping):
                    raise VideoRegistryError("malformed completed session snapshot")
                restored = VideoCompanionSession.from_snapshot(deepcopy(snapshot))
                if restored.status not in {SessionStatus.COMPLETED, SessionStatus.STOPPED}:
                    raise VideoRegistryError("completed registry contains a live session")
                self._completed.append(restored.snapshot())
            retired_count = retired.get("count", 0)
            if isinstance(retired_count, bool):
                raise VideoRegistryError("invalid retired session count")
            self._retired_count = int(retired_count)
            self._retired_digest = retired.get("digest")
            if self._retired_count < 0:
                raise VideoRegistryError("invalid retired session count")
            if self._retired_digest is not None and not re.fullmatch(
                r"[0-9a-f]{64}", self._retired_digest
            ):
                raise VideoRegistryError("invalid retired session digest")
            if (self._retired_count == 0) != (self._retired_digest is None):
                raise VideoRegistryError("incomplete retired session provenance")
        except (VideoCompanionError, TypeError, ValueError) as exc:
            if isinstance(exc, VideoRegistryError):
                raise
            raise VideoRegistryError("invalid video companion snapshot") from exc

        changed = False
        while len(self._completed) > self.max_completed:
            self._retire_loaded_snapshot_locked()
            changed = True
        if self._active is not None:
            if self._active.status is SessionStatus.ACTIVE:
                self._active.pause()
                changed = True
            elif self._active.status is SessionStatus.INTERRUPTED:
                now = max(
                    self._active.progress.processed_until,
                    self._active.interrupted_at or 0.0,
                )
                self._active.resume_after_direct_conversation(now=now)
                if self._active.status is SessionStatus.ACTIVE:
                    self._active.pause()
                changed = True
            elif self._active.status in {SessionStatus.COMPLETED, SessionStatus.STOPPED}:
                self._archive_active_locked()
                changed = True
        return changed

    def _retire_loaded_snapshot_locked(self) -> None:
        retired = self._completed.pop(0)
        payload = json.dumps(
            {"previous": self._retired_digest, "snapshot": retired},
            sort_keys=True,
            separators=(",", ":"),
        )
        self._retired_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self._retired_count += 1

    def _persist_locked(self) -> None:
        document = {
            "version": REGISTRY_VERSION,
            "active": None if self._active is None else self._active.snapshot(),
            "completed": deepcopy(self._completed),
            "retired": {
                "count": self._retired_count,
                "digest": self._retired_digest,
            },
        }
        _assert_safe_tree(document)
        encoded = json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        if len(encoded) > MAX_REGISTRY_BYTES:
            raise VideoRegistryError("video registry exceeds its size bound")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError as exc:
            raise VideoRegistryError("unable to persist video registry atomically") from exc

    @staticmethod
    def _clone(session: VideoCompanionSession) -> VideoCompanionSession:
        return VideoCompanionSession.from_snapshot(session.snapshot())

    @staticmethod
    def _summarize(session: VideoCompanionSession) -> SessionSummary:
        progress = session.progress
        return SessionSummary(
            session_id=session.session_id,
            source_id=session.source.source_id,
            source_kind=session.source.kind,
            surface=session.source.surface,
            adapter_id=session.source.adapter_id,
            status=session.status,
            processed_until=progress.processed_until,
            duration_seconds=progress.duration_seconds,
            progress_fraction=(
                None
                if progress.fraction is None
                else math.floor(progress.fraction * 10_000) / 10_000
            ),
            retained_events=len(session.timeline),
            deferred_events=len(session.deferred_timeline),
            compacted_events=session.compaction_summary.entry_count,
        )


# A shorter public name for callers that already identify the domain in context.
VideoRegistry = VideoSessionRegistry
