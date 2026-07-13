"""Credential-backed monotonic anchor for the notification outbox.

Importing this module does not import Windows modules, acquire a mutex, or
touch credential storage.  Deployment constructs an explicit backend for one
dedicated, caller-supplied credential target and injects a separate HMAC key.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import re
import threading
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from types import ModuleType
from typing import Protocol, runtime_checkable

from alpecca.notification_outbox import (
    CONTRACT_VERSION,
    AnchorSnapshot,
    LedgerCheckpoint,
    OutboxAnchorError,
)


ANCHOR_FORMAT_VERSION = 1
_ANCHOR_DOMAIN = "alpecca.notification-outbox-credential-anchor.v1"
_CHECKPOINT_FIELDS = (
    "ledger_id",
    "contract_version",
    "policy_id",
    "policy_version",
    "policy_digest",
    "sequence",
    "event_count",
    "receipt_count",
    "global_head_seal",
    "meta_seal",
)
_CHECKPOINT_FIELD_SET = frozenset(_CHECKPOINT_FIELDS)
_RECORD_FIELD_SET = frozenset(
    {"format_version", "current", "pending", "seal"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LEDGER_ID_RE = re.compile(r"^ledger_[0-9a-f]{32}$")
_POLICY_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_MAX_SQLITE_INTEGER = 2**63 - 1
_MAX_RECORD_CHARS = 1280
_WINDOWS_CREDENTIAL_BLOB_BYTES = 5 * 512
_MISSING_ERROR_CODES = frozenset({2, 1168})
_UNSET = object()


class CredentialRecordBackendError(OutboxAnchorError):
    """The credential record or its atomic lock is unavailable."""


class NotificationAnchorUnavailable(OutboxAnchorError):
    """The credential anchor has failed closed for this process."""


class CrossProcessMutexError(RuntimeError):
    """A required cross-process mutex could not be acquired or released."""


class CrossProcessMutexTimeout(CrossProcessMutexError):
    """A cross-process mutex was not acquired within its fixed timeout."""


@runtime_checkable
class CrossProcessMutex(Protocol):
    """Named lock shared by all participating operating-system processes."""

    def locked(
        self, *, timeout_ms: int | None = None
    ) -> AbstractContextManager[None]: ...


@runtime_checkable
class LockedCredentialRecord(Protocol):
    """One credential record accessed while its backend lock is held."""

    def read(self) -> str | None: ...

    def write(self, value: str) -> None: ...


@runtime_checkable
class AtomicCredentialRecordBackend(Protocol):
    """Backend that serializes record access across all participating writers.

    The yielded lock must cover every read and write until the context exits.
    Implementations must not normalize record text because canonical byte-for-
    byte readback is part of the anchor's durability contract.
    """

    def locked(self) -> AbstractContextManager[LockedCredentialRecord]: ...


@dataclass(frozen=True, slots=True)
class _StoredAnchorState:
    current: LedgerCheckpoint | None
    pending: LedgerCheckpoint | None


class _RecordFormatError(ValueError):
    pass


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise _RecordFormatError("anchor record is not canonical JSON") from exc


def _reject_constant(value: str) -> object:
    raise _RecordFormatError(f"invalid JSON constant {value!r}")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _RecordFormatError("anchor record contains a duplicate key")
        result[key] = value
    return result


def _exact_nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_SQLITE_INTEGER:
        raise _RecordFormatError(f"{name} is not a nonnegative SQLite integer")
    return value


def _checkpoint_to_mapping(checkpoint: LedgerCheckpoint) -> dict[str, object]:
    _validate_checkpoint(checkpoint)
    return {name: getattr(checkpoint, name) for name in _CHECKPOINT_FIELDS}


def _checkpoint_from_mapping(value: object) -> LedgerCheckpoint | None:
    if value is None:
        return None
    if type(value) is not dict or frozenset(value) != _CHECKPOINT_FIELD_SET:
        raise _RecordFormatError("checkpoint keys do not match the outbox contract")
    string_fields = (
        "ledger_id",
        "policy_id",
        "policy_digest",
        "global_head_seal",
        "meta_seal",
    )
    if any(type(value[name]) is not str for name in string_fields):
        raise _RecordFormatError("checkpoint text fields have invalid JSON types")
    checkpoint = LedgerCheckpoint(
        ledger_id=value["ledger_id"],
        contract_version=_exact_nonnegative_int(
            value["contract_version"], "contract_version"
        ),
        policy_id=value["policy_id"],
        policy_version=_exact_nonnegative_int(
            value["policy_version"], "policy_version"
        ),
        policy_digest=value["policy_digest"],
        sequence=_exact_nonnegative_int(value["sequence"], "sequence"),
        event_count=_exact_nonnegative_int(value["event_count"], "event_count"),
        receipt_count=_exact_nonnegative_int(
            value["receipt_count"], "receipt_count"
        ),
        global_head_seal=value["global_head_seal"],
        meta_seal=value["meta_seal"],
    )
    _validate_checkpoint(checkpoint)
    return checkpoint


def _validate_checkpoint(checkpoint: object) -> LedgerCheckpoint:
    if type(checkpoint) is not LedgerCheckpoint:
        raise OutboxAnchorError("anchor checkpoint must be an exact LedgerCheckpoint")
    for name in (
        "ledger_id",
        "policy_id",
        "policy_digest",
        "global_head_seal",
        "meta_seal",
    ):
        if type(getattr(checkpoint, name)) is not str:
            raise OutboxAnchorError(f"anchor {name} must be exact text")
    if (
        type(checkpoint.contract_version) is not int
        or checkpoint.contract_version != CONTRACT_VERSION
    ):
        raise OutboxAnchorError("anchor checkpoint contract version differs")
    if not _LEDGER_ID_RE.fullmatch(checkpoint.ledger_id):
        raise OutboxAnchorError("anchor ledger identity is invalid")
    if not _POLICY_ID_RE.fullmatch(checkpoint.policy_id):
        raise OutboxAnchorError("anchor policy identity is invalid")
    if (
        type(checkpoint.policy_version) is not int
        or not 1 <= checkpoint.policy_version <= 2**31 - 1
    ):
        raise OutboxAnchorError("anchor policy version is invalid")
    for name in ("sequence", "event_count", "receipt_count"):
        value = getattr(checkpoint, name)
        if type(value) is not int or not 0 <= value <= _MAX_SQLITE_INTEGER:
            raise OutboxAnchorError(f"anchor {name} is invalid")
    if checkpoint.sequence != checkpoint.receipt_count:
        raise OutboxAnchorError("anchor sequence and receipt count differ")
    if checkpoint.event_count > checkpoint.receipt_count:
        raise OutboxAnchorError("anchor event count exceeds receipt count")
    if not _SHA256_RE.fullmatch(checkpoint.policy_digest):
        raise OutboxAnchorError("anchor policy digest is invalid")
    if not _SHA256_RE.fullmatch(checkpoint.meta_seal):
        raise OutboxAnchorError("anchor metadata seal is invalid")
    if checkpoint.sequence == 0:
        if checkpoint.global_head_seal != "":
            raise OutboxAnchorError("empty anchor checkpoint has a receipt head")
    elif not _SHA256_RE.fullmatch(checkpoint.global_head_seal):
        raise OutboxAnchorError("anchor receipt head is invalid")
    return checkpoint


def _validate_progress(
    expected: LedgerCheckpoint | None,
    candidate: LedgerCheckpoint,
) -> None:
    if expected is not None:
        _validate_checkpoint(expected)
    _validate_checkpoint(candidate)
    if expected is None:
        if candidate.sequence != 0 or candidate.event_count != 0:
            raise OutboxAnchorError("initial anchor checkpoint is not empty")
        return
    immutable = (
        "ledger_id",
        "contract_version",
        "policy_id",
        "policy_version",
        "policy_digest",
    )
    if any(getattr(candidate, name) != getattr(expected, name) for name in immutable):
        raise OutboxAnchorError("anchor identity or policy changed")
    if (
        candidate.sequence <= expected.sequence
        or candidate.receipt_count <= expected.receipt_count
        or candidate.event_count < expected.event_count
    ):
        raise OutboxAnchorError("anchor checkpoint did not advance monotonically")


class CredentialMonotonicAnchor:
    """HMAC-sealed notification anchor in one atomic credential record.

    A missing record is initialized to a sealed ``current=None, pending=None``
    state while the backend lock is held.  Once this object has initialized,
    missing, malformed, non-canonical, unsealed, unavailable, or non-durable
    state permanently fails the instance closed.
    """

    def __init__(
        self,
        backend: AtomicCredentialRecordBackend,
        *,
        anchor_key: bytes | bytearray | memoryview | str | None = None,
        seal_key: bytes | bytearray | memoryview | str | None = None,
    ) -> None:
        if not callable(getattr(backend, "locked", None)):
            raise TypeError("backend must implement AtomicCredentialRecordBackend")
        if anchor_key is not None and seal_key is not None:
            raise TypeError("supply anchor_key or seal_key, not both")
        key = anchor_key if anchor_key is not None else seal_key
        if isinstance(key, str):
            key = key.encode("utf-8")
        if not isinstance(key, (bytes, bytearray, memoryview)):
            raise TypeError("anchor_key must be bytes or text")
        self._key = bytes(key)
        if len(self._key) < 32:
            raise ValueError("anchor_key must contain at least 32 bytes")
        self._backend = backend
        self._process_lock = threading.RLock()
        self._initialized = False
        self._failed_reason: str | None = None
        self._observed_current: object | LedgerCheckpoint | None = _UNSET
        self._initialize_record()

    def _require_available(self) -> None:
        if self._failed_reason is not None:
            raise NotificationAnchorUnavailable(
                "notification credential anchor is unavailable: "
                + self._failed_reason
            )

    def _fail_closed(
        self,
        reason: str,
        cause: BaseException | None = None,
    ) -> None:
        self._failed_reason = reason
        error = NotificationAnchorUnavailable(
            "notification credential anchor failed closed: " + reason
        )
        if cause is None:
            raise error
        raise error from cause

    @contextmanager
    def _locked_record(self) -> Iterator[LockedCredentialRecord]:
        self._require_available()
        try:
            with self._backend.locked() as record:
                if not callable(getattr(record, "read", None)) or not callable(
                    getattr(record, "write", None)
                ):
                    self._fail_closed("backend returned an invalid locked record")
                yield record
        except CredentialRecordBackendError as exc:
            self._fail_closed("credential backend is unavailable", exc)
        except NotificationAnchorUnavailable:
            raise
        except OutboxAnchorError:
            raise
        except Exception as exc:
            self._fail_closed("credential backend operation failed", exc)

    def _read_raw(
        self,
        record: LockedCredentialRecord,
        *,
        allow_missing: bool,
    ) -> str | None:
        try:
            raw = record.read()
        except Exception as exc:
            self._fail_closed("credential record read failed", exc)
        if raw is None:
            if allow_missing and not self._initialized:
                return None
            self._fail_closed("credential record is missing after initialization")
        if type(raw) is not str:
            self._fail_closed("credential record has an invalid storage type")
        if not raw or len(raw) > _MAX_RECORD_CHARS:
            self._fail_closed("credential record length is invalid")
        return raw

    def _seal(self, material: Mapping[str, object]) -> str:
        encoded = _canonical(
            {"domain": _ANCHOR_DOMAIN, **dict(material)}
        ).encode("utf-8")
        return hmac.new(self._key, encoded, hashlib.sha256).hexdigest()

    def _encode_state(self, state: _StoredAnchorState) -> str:
        self._validate_state(state)
        material = {
            "format_version": ANCHOR_FORMAT_VERSION,
            "current": (
                None
                if state.current is None
                else _checkpoint_to_mapping(state.current)
            ),
            "pending": (
                None
                if state.pending is None
                else _checkpoint_to_mapping(state.pending)
            ),
        }
        encoded = _canonical({**material, "seal": self._seal(material)})
        if len(encoded) > _MAX_RECORD_CHARS:
            raise OutboxAnchorError("anchor record exceeds credential capacity")
        return encoded

    def _decode_state(self, raw: str) -> _StoredAnchorState:
        try:
            value = json.loads(
                raw,
                object_pairs_hook=_object_without_duplicates,
                parse_constant=_reject_constant,
            )
            if type(value) is not dict or frozenset(value) != _RECORD_FIELD_SET:
                raise _RecordFormatError("anchor record keys are invalid")
            if _canonical(value) != raw:
                raise _RecordFormatError("anchor record is not exact canonical JSON")
            if type(value["format_version"]) is not int or (
                value["format_version"] != ANCHOR_FORMAT_VERSION
            ):
                raise _RecordFormatError("anchor format version differs")
            if type(value["seal"]) is not str or not _SHA256_RE.fullmatch(
                value["seal"]
            ):
                raise _RecordFormatError("anchor seal has an invalid type or shape")
            material = {
                "format_version": value["format_version"],
                "current": value["current"],
                "pending": value["pending"],
            }
            expected_seal = self._seal(material)
            if not hmac.compare_digest(expected_seal, value["seal"]):
                raise _RecordFormatError("anchor seal does not verify")
            state = _StoredAnchorState(
                current=_checkpoint_from_mapping(value["current"]),
                pending=_checkpoint_from_mapping(value["pending"]),
            )
            self._validate_state(state)
            return state
        except OutboxAnchorError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise _RecordFormatError("anchor record is malformed") from exc

    @staticmethod
    def _validate_state(state: _StoredAnchorState) -> None:
        if state.current is not None:
            _validate_checkpoint(state.current)
        if state.pending is not None:
            _validate_progress(state.current, state.pending)

    def _observe(self, state: _StoredAnchorState) -> None:
        previous = self._observed_current
        current = state.current
        if previous is _UNSET:
            self._observed_current = current
            return
        if previous is None:
            if current is not None:
                try:
                    _validate_progress(None, current)
                except OutboxAnchorError as exc:
                    self._fail_closed("credential record current value was replaced", exc)
        elif current is None:
            self._fail_closed("credential record rolled back to an empty state")
        elif current != previous:
            try:
                _validate_progress(previous, current)
            except OutboxAnchorError as exc:
                self._fail_closed("credential record current value rolled back", exc)
        self._observed_current = current

    def _load_state(self, record: LockedCredentialRecord) -> _StoredAnchorState:
        raw = self._read_raw(record, allow_missing=False)
        assert raw is not None
        try:
            state = self._decode_state(raw)
        except (OutboxAnchorError, _RecordFormatError) as exc:
            self._fail_closed("credential record is corrupt", exc)
        self._observe(state)
        return state

    def _write_state(
        self,
        record: LockedCredentialRecord,
        state: _StoredAnchorState,
    ) -> None:
        encoded = self._encode_state(state)
        try:
            record.write(encoded)
        except Exception as exc:
            self._fail_closed("credential record write failed", exc)
        readback = self._read_raw(record, allow_missing=False)
        if readback != encoded:
            self._fail_closed("credential record readback did not match the write")
        try:
            decoded = self._decode_state(readback)
        except (OutboxAnchorError, _RecordFormatError) as exc:
            self._fail_closed("credential record readback is corrupt", exc)
        if decoded != state:
            self._fail_closed("credential record readback changed anchor state")
        self._observe(decoded)

    def _initialize_record(self) -> None:
        with self._process_lock:
            with self._locked_record() as record:
                raw = self._read_raw(record, allow_missing=True)
                if raw is None:
                    self._write_state(record, _StoredAnchorState(None, None))
                else:
                    try:
                        state = self._decode_state(raw)
                    except (OutboxAnchorError, _RecordFormatError) as exc:
                        self._fail_closed(
                            "existing credential record is corrupt; refusing overwrite",
                            exc,
                        )
                    self._observe(state)
                self._initialized = True

    def snapshot(self) -> AnchorSnapshot:
        with self._process_lock:
            self._require_available()
            with self._locked_record() as record:
                state = self._load_state(record)
                return AnchorSnapshot(state.current, state.pending)

    def prepare(
        self,
        expected: LedgerCheckpoint | None,
        candidate: LedgerCheckpoint,
    ) -> None:
        if expected is not None:
            _validate_checkpoint(expected)
        _validate_checkpoint(candidate)
        with self._process_lock:
            self._require_available()
            with self._locked_record() as record:
                state = self._load_state(record)
                if state.pending is not None:
                    raise OutboxAnchorError("anchor already has a pending checkpoint")
                if state.current != expected:
                    raise OutboxAnchorError("anchor current checkpoint changed")
                _validate_progress(expected, candidate)
                self._write_state(
                    record,
                    _StoredAnchorState(current=state.current, pending=candidate),
                )

    def commit(self, candidate: LedgerCheckpoint) -> None:
        _validate_checkpoint(candidate)
        with self._process_lock:
            self._require_available()
            with self._locked_record() as record:
                state = self._load_state(record)
                if state.pending is None and state.current == candidate:
                    return
                if state.pending != candidate:
                    raise OutboxAnchorError(
                        "anchor pending checkpoint does not match"
                    )
                self._write_state(
                    record,
                    _StoredAnchorState(current=candidate, pending=None),
                )

    def abort(self, candidate: LedgerCheckpoint) -> None:
        _validate_checkpoint(candidate)
        with self._process_lock:
            self._require_available()
            with self._locked_record() as record:
                state = self._load_state(record)
                if state.pending == candidate:
                    self._write_state(
                        record,
                        _StoredAnchorState(current=state.current, pending=None),
                    )
                elif state.pending is not None:
                    raise OutboxAnchorError(
                        "cannot abort a different anchor checkpoint"
                    )


def _credential_error_code(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    if isinstance(value, int):
        return value
    if exc.args and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def _decode_windows_blob(blob: object) -> str:
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if type(blob) is bytes:
        encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
        try:
            value = blob.decode(encoding).rstrip("\x00")
        except UnicodeDecodeError as exc:
            raise CredentialRecordBackendError(
                "credential blob encoding is invalid"
            ) from exc
    elif type(blob) is str:
        value = blob
    else:
        raise CredentialRecordBackendError(
            "credential blob has an unsupported storage type"
        )
    if not value:
        raise CredentialRecordBackendError("credential blob is empty")
    return value


class _WindowsLockedCredentialRecord:
    __slots__ = ("_backend", "_active")

    def __init__(self, backend: WindowsCredentialManagerBackend) -> None:
        self._backend = backend
        self._active = True

    def _require_active(self) -> None:
        if not self._active:
            raise CredentialRecordBackendError(
                "credential record used outside its mutex"
            )

    def read(self) -> str | None:
        self._require_active()
        return self._backend._read_unlocked()

    def write(self, value: str) -> None:
        self._require_active()
        self._backend._write_unlocked(value)


class WindowsNamedMutex:
    """Reusable Windows named mutex with bounded acquisition.

    Optional module injection is intentionally explicit so tests can exercise
    the Windows ownership contract without substituting a production fallback.
    """

    def __init__(
        self,
        name: str,
        *,
        timeout_ms: int = 30_000,
        win32event_module: ModuleType | object | None = None,
        win32api_module: ModuleType | object | None = None,
    ) -> None:
        if type(name) is not str or not name or len(name) > 32_767:
            raise ValueError("mutex name must be nonempty caller-supplied text")
        if any(ord(character) < 32 for character in name):
            raise ValueError("mutex name contains control characters")
        if (
            type(timeout_ms) is not int
            or not 0 <= timeout_ms <= 2**31 - 1
        ):
            raise ValueError("timeout_ms must be a nonnegative integer")
        try:
            self._win32event = win32event_module or importlib.import_module(
                "win32event"
            )
            self._win32api = win32api_module or importlib.import_module("win32api")
        except ImportError as exc:
            raise CrossProcessMutexError(
                "Windows named mutex requires pywin32"
            ) from exc
        self._name = name
        self._timeout_ms = timeout_ms

    @property
    def name(self) -> str:
        return self._name

    @contextmanager
    def locked(self, *, timeout_ms: int | None = None) -> Iterator[None]:
        wait_ms = self._timeout_ms if timeout_ms is None else timeout_ms
        if (
            type(wait_ms) is not int
            or not 0 <= wait_ms <= 2**31 - 1
        ):
            raise ValueError("timeout_ms must be a nonnegative integer")
        handle: object | None = None
        acquired = False
        try:
            try:
                handle = self._win32event.CreateMutex(None, False, self._name)
            except Exception as exc:
                raise CrossProcessMutexError(
                    "could not create Windows named mutex"
                ) from exc
            if handle is None:
                raise CrossProcessMutexError(
                    "could not create Windows named mutex"
                )
            try:
                result = self._win32event.WaitForSingleObject(handle, wait_ms)
            except Exception as exc:
                raise CrossProcessMutexError(
                    "Windows named mutex wait failed"
                ) from exc
            wait_object = getattr(self._win32event, "WAIT_OBJECT_0", 0)
            wait_abandoned = getattr(self._win32event, "WAIT_ABANDONED", 0x80)
            wait_timeout = getattr(self._win32event, "WAIT_TIMEOUT", 0x102)
            if result == wait_timeout:
                raise CrossProcessMutexTimeout(
                    "Windows named mutex acquisition timed out"
                )
            if result not in (wait_object, wait_abandoned):
                raise CrossProcessMutexError("Windows named mutex wait failed")
            acquired = True
            yield
        finally:
            release_error: BaseException | None = None
            if acquired and handle is not None:
                try:
                    self._win32event.ReleaseMutex(handle)
                except Exception as exc:
                    release_error = exc
            if handle is not None:
                try:
                    self._win32api.CloseHandle(handle)
                except Exception as exc:
                    if release_error is None:
                        release_error = exc
            if release_error is not None:
                raise CrossProcessMutexError(
                    "could not release Windows named mutex"
                ) from release_error


class WindowsCredentialManagerBackend:
    """Atomic generic-credential record protected by a named Windows mutex.

    ``target`` has no default.  Only that exact target is passed to CredRead and
    CredWrite.  This class has no credential enumeration or deletion operation.
    Optional module injection exists for deterministic tests; otherwise pywin32
    is imported lazily when this backend is constructed.
    """

    def __init__(
        self,
        target: str,
        *,
        mutex_timeout_ms: int = 30_000,
        win32cred_module: ModuleType | object | None = None,
        win32event_module: ModuleType | object | None = None,
        win32api_module: ModuleType | object | None = None,
    ) -> None:
        if type(target) is not str or not target or len(target) > 32_767:
            raise ValueError("credential target must be caller-supplied text")
        if any(ord(character) < 32 for character in target):
            raise ValueError("credential target contains control characters")
        if type(mutex_timeout_ms) is not int or not 1 <= mutex_timeout_ms <= 2**31 - 1:
            raise ValueError("mutex_timeout_ms must be a positive integer")
        try:
            self._win32cred = win32cred_module or importlib.import_module("win32cred")
        except ImportError as exc:
            raise CredentialRecordBackendError(
                "Windows Credential Manager backend requires pywin32"
            ) from exc
        self._target = target
        target_digest = hashlib.sha256(target.casefold().encode("utf-8")).hexdigest()
        self._mutex_name = "Local\\Alpecca.NotificationAnchor." + target_digest
        try:
            self._mutex = WindowsNamedMutex(
                self._mutex_name,
                timeout_ms=mutex_timeout_ms,
                win32event_module=win32event_module,
                win32api_module=win32api_module,
            )
        except CrossProcessMutexError as exc:
            raise CredentialRecordBackendError(
                "Windows Credential Manager backend requires pywin32"
            ) from exc

    @property
    def target(self) -> str:
        return self._target

    @property
    def mutex_name(self) -> str:
        return self._mutex_name

    def _read_unlocked(self) -> str | None:
        try:
            credential = self._win32cred.CredRead(
                self._target,
                self._win32cred.CRED_TYPE_GENERIC,
                0,
            )
        except Exception as exc:
            if _credential_error_code(exc) in _MISSING_ERROR_CODES:
                return None
            raise CredentialRecordBackendError(
                "could not read notification anchor credential"
            ) from exc
        if not isinstance(credential, Mapping) or "CredentialBlob" not in credential:
            raise CredentialRecordBackendError(
                "credential manager returned a malformed record"
            )
        return _decode_windows_blob(credential["CredentialBlob"])

    def _write_unlocked(self, value: str) -> None:
        if type(value) is not str or not value:
            raise CredentialRecordBackendError(
                "credential record write requires nonempty text"
            )
        if len(value.encode("utf-16-le")) > _WINDOWS_CREDENTIAL_BLOB_BYTES:
            raise CredentialRecordBackendError(
                "credential record exceeds Windows Credential Manager capacity"
            )
        try:
            self._win32cred.CredWrite(
                {
                    "Type": self._win32cred.CRED_TYPE_GENERIC,
                    "TargetName": self._target,
                    "CredentialBlob": value,
                    "Persist": self._win32cred.CRED_PERSIST_LOCAL_MACHINE,
                    "UserName": "Alpecca",
                    "Comment": "Alpecca notification outbox monotonic anchor",
                },
                0,
            )
        except Exception as exc:
            raise CredentialRecordBackendError(
                "could not write notification anchor credential"
            ) from exc

    @contextmanager
    def locked(self) -> Iterator[LockedCredentialRecord]:
        record: _WindowsLockedCredentialRecord | None = None
        try:
            with self._mutex.locked():
                record = _WindowsLockedCredentialRecord(self)
                try:
                    yield record
                finally:
                    record._active = False
        except CrossProcessMutexError as exc:
            raise CredentialRecordBackendError(
                "notification anchor mutex failed or timed out"
            ) from exc


# Descriptive aliases retained for callers that name the storage boundary.
CredentialRecordMonotonicAnchor = CredentialMonotonicAnchor
WindowsCredentialRecordBackend = WindowsCredentialManagerBackend


__all__ = [
    "ANCHOR_FORMAT_VERSION",
    "AtomicCredentialRecordBackend",
    "CrossProcessMutex",
    "CrossProcessMutexError",
    "CrossProcessMutexTimeout",
    "CredentialMonotonicAnchor",
    "CredentialRecordBackendError",
    "CredentialRecordMonotonicAnchor",
    "LockedCredentialRecord",
    "NotificationAnchorUnavailable",
    "WindowsCredentialManagerBackend",
    "WindowsCredentialRecordBackend",
    "WindowsNamedMutex",
]
