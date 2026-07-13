"""Private Windows runtime for the first Phase 11 Web Push adapter.

Only a fixed connection-test template is supported in this slice. Browser
subscription endpoints and keys live in a dedicated Windows Credential Manager
record. SQLite contains only HMAC identifiers, fixed template names, and sealed
one-use acknowledgement receipt hashes.

Importing this module is inert: credentials, SQLite, VAPID keys, and network
clients are opened only by explicit constructors or methods.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from alpecca import notification_outbox as outbox_mod
from alpecca import web_push_adapter as adapter_mod
from alpecca.db import connect


STORE_VERSION = 1
MAX_SUBSCRIPTIONS = 2
ACK_TTL_SECONDS = 7 * 24 * 60 * 60
TEST_TEMPLATE = "connection_test"
TEST_TITLE = "Alpecca creator alerts"
TEST_BODY = "Creator alerts are connected. Tap to acknowledge this test."

_SUBSCRIPTION_RECORD_KEYS = frozenset(
    {"version", "generation", "subscriptions", "seal"}
)
_LEGACY_SUBSCRIPTION_RECORD_KEYS = frozenset(
    {"version", "subscriptions", "seal"}
)
_SUBSCRIPTION_KEYS = frozenset(
    {"subscription_id", "endpoint", "p256dh", "auth"}
)
_REF_DOMAIN = b"alpecca.notification-push-ref.v1\x00"
_SUBSCRIPTION_DOMAIN = b"alpecca.notification-push-subscription.v1\x00"
_RECEIPT_DOMAIN = b"alpecca.notification-push-receipt.v1\x00"
_TRANSPORT_DOMAIN = b"alpecca.notification-push-transport.v1\x00"
_ROW_DOMAIN = b"alpecca.notification-push-row.v1\x00"
_SUBSCRIPTION_META_DOMAIN = b"alpecca.notification-push-meta.v1\x00"
_SUBSCRIPTION_POLICY_DIGEST = hashlib.sha256(
    b"alpecca.notification-push-subscriptions-policy.v1"
).hexdigest()
_RECEIPT_RE = re.compile(r"^wpa_[A-Za-z0-9_-]{43}$")


class WebPushRuntimeError(RuntimeError):
    """Private Web Push state is unavailable, malformed, or inconsistent."""


@runtime_checkable
class CredentialRecord(Protocol):
    """One atomic protected record in a failure domain outside SQLite."""

    def read(self) -> str | None: ...

    def write(self, value: str) -> None: ...


class WindowsCredentialRecord:
    """Dedicated generic credential record; existing targets are never touched."""

    def __init__(self, target: str, *, comment: str) -> None:
        if type(target) is not str or not target.startswith("Alpecca/"):
            raise ValueError("credential target must use the Alpecca namespace")
        if type(comment) is not str or not comment.strip():
            raise ValueError("credential comment is required")
        self.target = target
        self.comment = comment.strip()[:240]

    @staticmethod
    def _win32cred():
        try:
            import win32cred
        except ImportError as exc:
            raise WebPushRuntimeError(
                "Windows Credential Manager support requires pywin32"
            ) from exc
        return win32cred

    def read(self) -> str | None:
        win32cred = self._win32cred()
        try:
            credential = win32cred.CredRead(
                self.target, win32cred.CRED_TYPE_GENERIC, 0
            )
        except Exception as exc:
            code = getattr(exc, "winerror", None)
            if code is None and exc.args and isinstance(exc.args[0], int):
                code = exc.args[0]
            if code in {2, 1168}:
                return None
            raise WebPushRuntimeError("could not read protected push state") from exc
        blob = credential.get("CredentialBlob")
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        if isinstance(blob, bytes):
            encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
            try:
                value = blob.decode(encoding).rstrip("\x00")
            except UnicodeDecodeError as exc:
                raise WebPushRuntimeError("protected push state is not valid text") from exc
        elif isinstance(blob, str):
            value = blob
        else:
            raise WebPushRuntimeError("protected push state is malformed")
        if not value:
            raise WebPushRuntimeError("protected push state is empty")
        return value

    def write(self, value: str) -> None:
        if type(value) is not str or not value or len(value.encode("utf-8")) > 2400:
            raise WebPushRuntimeError("protected push state exceeds its fixed bound")
        win32cred = self._win32cred()
        try:
            win32cred.CredWrite(
                {
                    "Type": win32cred.CRED_TYPE_GENERIC,
                    "TargetName": self.target,
                    "CredentialBlob": value,
                    "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                    "UserName": "Alpecca",
                    "Comment": self.comment,
                },
                0,
            )
        except Exception as exc:
            raise WebPushRuntimeError("could not write protected push state") from exc
        if self.read() != value:
            raise WebPushRuntimeError("protected push state failed readback")


def _key_bytes(value: object, *, name: str) -> bytes:
    if type(value) is str:
        try:
            result = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(f"{name} is not valid UTF-8") from exc
    elif type(value) is bytes:
        result = value
    else:
        raise TypeError(f"{name} must be str or bytes")
    if len(result) < 32:
        raise ValueError(f"{name} must contain at least 32 bytes")
    return result


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
        raise WebPushRuntimeError("push state is not canonical JSON") from exc


def _record_seal(key: bytes, body: dict[str, object]) -> str:
    return hmac.new(key, _canonical(body).encode("ascii"), hashlib.sha256).hexdigest()


def _domain_hmac(key: bytes, domain: bytes, value: str) -> str:
    return hmac.new(key, domain + value.encode("utf-8"), hashlib.sha256).hexdigest()


def _now(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WebPushRuntimeError("clock returned a non-numeric value")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0:
        raise WebPushRuntimeError("clock returned an invalid value")
    return stamp


def _payload_ref_value(value: object) -> str:
    if not isinstance(value, outbox_mod.OpaquePayloadRef):
        raise TypeError("payload_ref must be OpaquePayloadRef")
    raw = value.value
    if type(raw) is not str or not raw.startswith("pref_") or len(raw) != 70:
        raise WebPushRuntimeError("payload reference is malformed")
    return raw


class WebPushPrivateStore(adapter_mod.WebPushRuntimeStore):
    """Credential-backed subscriptions plus content-free SQLite bindings."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        subscription_record: CredentialRecord,
        seal_key: str | bytes,
        subscription_anchor: outbox_mod.MonotonicAnchor | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(subscription_record, CredentialRecord):
            raise TypeError("subscription_record must implement CredentialRecord")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.db_path = Path(db_path)
        self._record = subscription_record
        self._key = _key_bytes(seal_key, name="seal_key")
        if subscription_anchor is not None and not isinstance(
            subscription_anchor, outbox_mod.MonotonicAnchor
        ):
            raise TypeError("subscription_anchor must implement MonotonicAnchor")
        self._subscription_anchor = subscription_anchor
        self._clock = clock
        self._lock = threading.RLock()
        self._ensure_schema()
        if self._subscription_anchor is not None:
            with self._subscription_guard():
                self._reconcile_subscription_anchor()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notification_push_templates (
                    ref_hmac TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    row_seal TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_push_ack_receipts (
                    receipt_hmac TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    subscription_id TEXT NOT NULL,
                    transport_hmac TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    reserved_at REAL,
                    consumed_at REAL,
                    row_seal TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS notification_push_ack_expiry_idx
                    ON notification_push_ack_receipts(expires_at, consumed_at);
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute(
                    "PRAGMA table_info(notification_push_ack_receipts)"
                ).fetchall()
            }
            if "reserved_at" not in columns:
                conn.execute(
                    "ALTER TABLE notification_push_ack_receipts "
                    "ADD COLUMN reserved_at REAL"
                )

    def _empty_record(self) -> dict[str, object]:
        return self._record_at_generation([], 0)

    def _record_at_generation(
        self,
        subscriptions: list[dict[str, str]],
        generation: int,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "version": STORE_VERSION,
            "generation": generation,
            "subscriptions": subscriptions,
        }
        return {**body, "seal": _record_seal(self._key, body)}

    def _decode_record_with_format(
        self, raw: str | None
    ) -> tuple[dict[str, object], bool]:
        if raw is None:
            return self._empty_record(), False
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, RecursionError) as exc:
            raise WebPushRuntimeError("protected subscription record is invalid") from exc
        if type(parsed) is not dict:
            raise WebPushRuntimeError("protected subscription record has wrong shape")
        keys = frozenset(parsed)
        legacy = keys == _LEGACY_SUBSCRIPTION_RECORD_KEYS
        if not legacy and keys != _SUBSCRIPTION_RECORD_KEYS:
            raise WebPushRuntimeError("protected subscription record has wrong shape")
        if (
            parsed.get("version") != STORE_VERSION
            or type(parsed.get("subscriptions")) is not list
        ):
            raise WebPushRuntimeError("protected subscription record has wrong version")
        if legacy:
            generation = 0
            sealed_body = {
                "version": STORE_VERSION,
                "subscriptions": parsed["subscriptions"],
            }
        else:
            if (
                type(parsed.get("generation")) is not int
                or not 0 <= parsed["generation"] <= (1 << 63) - 1
            ):
                raise WebPushRuntimeError("protected subscription record has wrong version")
            generation = int(parsed["generation"])
            sealed_body = {
                "version": STORE_VERSION,
                "generation": generation,
                "subscriptions": parsed["subscriptions"],
            }
        subscriptions = parsed["subscriptions"]
        if len(subscriptions) > MAX_SUBSCRIPTIONS:
            raise WebPushRuntimeError("protected subscription record exceeds its cap")
        seal = parsed.get("seal")
        if type(seal) is not str or not hmac.compare_digest(
            seal, _record_seal(self._key, sealed_body)
        ):
            raise WebPushRuntimeError("protected subscription record seal is invalid")
        seen: set[str] = set()
        normalized: list[dict[str, str]] = []
        for item in subscriptions:
            if type(item) is not dict or frozenset(item) != _SUBSCRIPTION_KEYS:
                raise WebPushRuntimeError("protected subscription entry is invalid")
            try:
                subscription = adapter_mod.PushSubscription(**item)
            except (TypeError, ValueError) as exc:
                raise WebPushRuntimeError("protected subscription entry is invalid") from exc
            if subscription.subscription_id in seen:
                raise WebPushRuntimeError("protected subscription record has duplicates")
            seen.add(subscription.subscription_id)
            normalized.append(
                {
                    "subscription_id": subscription.subscription_id,
                    "endpoint": subscription.endpoint,
                    "p256dh": subscription.p256dh,
                    "auth": subscription.auth,
                }
            )
        record = self._record_at_generation(normalized, generation)
        return record, legacy

    def _decode_record(self, raw: str | None) -> dict[str, object]:
        record, _legacy = self._decode_record_with_format(raw)
        return record

    @contextmanager
    def _subscription_guard(self) -> Iterator[None]:
        """Serialize credential and anchor transitions across server processes."""
        with self._lock:
            with connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield
                except BaseException:
                    conn.rollback()
                    raise
                else:
                    conn.commit()

    def _write_verified_subscription_record(
        self, record: dict[str, object]
    ) -> dict[str, object]:
        encoded = _canonical(record)
        self._record.write(encoded)
        readback = self._decode_record(self._record.read())
        if readback != record:
            raise WebPushRuntimeError("protected subscription record changed on readback")
        return readback

    def _subscription_checkpoint(
        self, record: dict[str, object]
    ) -> outbox_mod.LedgerCheckpoint:
        generation = int(record["generation"])
        body = {
            "version": STORE_VERSION,
            "generation": generation,
            "subscriptions": record["subscriptions"],
        }
        record_digest = hashlib.sha256(_canonical(body).encode("ascii")).hexdigest()
        ledger_id = "ledger_" + _domain_hmac(
            self._key,
            _SUBSCRIPTION_META_DOMAIN,
            "ledger",
        )[:32]
        metadata = {
            "ledger_id": ledger_id,
            "contract_version": outbox_mod.CONTRACT_VERSION,
            "policy_id": "push_subscriptions",
            "policy_version": 1,
            "policy_digest": _SUBSCRIPTION_POLICY_DIGEST,
            "sequence": generation,
            "event_count": generation,
            "receipt_count": generation,
            "global_head_seal": "" if generation == 0 else record_digest,
        }
        meta_seal = _domain_hmac(
            self._key,
            _SUBSCRIPTION_META_DOMAIN,
            _canonical({"checkpoint": metadata, "record_digest": record_digest}),
        )
        return outbox_mod.LedgerCheckpoint(**metadata, meta_seal=meta_seal)

    def _reconcile_subscription_anchor(self) -> dict[str, object]:
        anchor = self._subscription_anchor
        if anchor is None:
            return self._decode_record(self._record.read())
        raw = self._record.read()
        snapshot = anchor.snapshot()
        if raw is None:
            if snapshot.current is not None or snapshot.pending is not None:
                raise WebPushRuntimeError("protected subscription record is missing")
            record = self._empty_record()
            checkpoint = self._subscription_checkpoint(record)
            anchor.prepare(None, checkpoint)
            try:
                record = self._write_verified_subscription_record(record)
            except Exception:
                anchor.abort(checkpoint)
                raise
            anchor.commit(checkpoint)
            return record
        record, legacy = self._decode_record_with_format(raw)
        if snapshot.current is None and snapshot.pending is None:
            if not legacy:
                raise WebPushRuntimeError(
                    "protected subscription anchor is missing for initialized state"
                )
            record = self._record_at_generation(record["subscriptions"], 0)
            checkpoint = self._subscription_checkpoint(record)
            anchor.prepare(None, checkpoint)
            try:
                record = self._write_verified_subscription_record(record)
            except Exception:
                anchor.abort(checkpoint)
                raise
            anchor.commit(checkpoint)
            return record
        checkpoint = self._subscription_checkpoint(record)
        if snapshot.pending == checkpoint:
            anchor.commit(checkpoint)
            snapshot = anchor.snapshot()
        elif snapshot.pending is not None:
            if snapshot.current != checkpoint:
                raise WebPushRuntimeError(
                    "protected subscription state does not match its monotonic anchor"
                )
            anchor.abort(snapshot.pending)
            snapshot = anchor.snapshot()
        if snapshot.current != checkpoint:
            raise WebPushRuntimeError(
                "protected subscription state does not match its monotonic anchor"
            )
        return record

    def _write_subscriptions(
        self,
        current: dict[str, object],
        subscriptions: list[dict[str, str]],
    ) -> None:
        generation = int(current["generation"]) + 1
        updated = self._record_at_generation(subscriptions, generation)
        anchor = self._subscription_anchor
        if anchor is None:
            self._write_verified_subscription_record(updated)
            return
        expected = self._subscription_checkpoint(current)
        candidate = self._subscription_checkpoint(updated)
        anchor.prepare(expected, candidate)
        try:
            self._write_verified_subscription_record(updated)
        except Exception:
            anchor.abort(candidate)
            raise
        anchor.commit(candidate)
        self._reconcile_subscription_anchor()

    def register_subscription(self, subscription: dict[str, object]) -> dict[str, object]:
        if type(subscription) is not dict or frozenset(subscription) != {
            "endpoint",
            "keys",
        }:
            raise adapter_mod.WebPushAdapterError("subscription has wrong shape")
        keys = subscription.get("keys")
        if type(keys) is not dict or frozenset(keys) != {"p256dh", "auth"}:
            raise adapter_mod.WebPushAdapterError("subscription keys have wrong shape")
        endpoint = adapter_mod._push_endpoint(subscription.get("endpoint"))
        subscription_id = "wps_" + _domain_hmac(
            self._key, _SUBSCRIPTION_DOMAIN, endpoint
        )[:32]
        clean = adapter_mod.PushSubscription(
            subscription_id=subscription_id,
            endpoint=endpoint,
            p256dh=keys.get("p256dh"),
            auth=keys.get("auth"),
        )
        item = {
            "subscription_id": clean.subscription_id,
            "endpoint": clean.endpoint,
            "p256dh": clean.p256dh,
            "auth": clean.auth,
        }
        with self._subscription_guard():
            current = self._reconcile_subscription_anchor()
            rows = [
                row
                for row in current["subscriptions"]
                if row["subscription_id"] != clean.subscription_id
            ]
            rows.append(item)
            if len(rows) > MAX_SUBSCRIPTIONS:
                raise WebPushRuntimeError("creator push subscription cap reached")
            self._write_subscriptions(current, rows)
        return {"subscribed": True, "subscription_id": clean.subscription_id}

    def revoke_endpoint(self, endpoint: str) -> bool:
        clean_endpoint = adapter_mod._push_endpoint(endpoint)
        with self._subscription_guard():
            current = self._reconcile_subscription_anchor()
            rows = [
                row
                for row in current["subscriptions"]
                if row["endpoint"] != clean_endpoint
            ]
            changed = len(rows) != len(current["subscriptions"])
            if changed:
                self._write_subscriptions(current, rows)
            return changed

    def subscriptions(self) -> tuple[adapter_mod.PushSubscription, ...]:
        with self._subscription_guard():
            current = self._reconcile_subscription_anchor()
        return tuple(adapter_mod.PushSubscription(**row) for row in current["subscriptions"])

    def remove_subscription(self, subscription_id: str) -> None:
        clean_id = adapter_mod._subscription_id(subscription_id)
        with self._subscription_guard():
            current = self._reconcile_subscription_anchor()
            rows = [
                row
                for row in current["subscriptions"]
                if row["subscription_id"] != clean_id
            ]
            if len(rows) != len(current["subscriptions"]):
                self._write_subscriptions(current, rows)

    def bind_test_template(self, payload_ref: outbox_mod.OpaquePayloadRef) -> None:
        raw_ref = _payload_ref_value(payload_ref)
        ref_hmac = _domain_hmac(self._key, _REF_DOMAIN, raw_ref)
        created_at = _now(self._clock())
        material = {
            "ref_hmac": ref_hmac,
            "template_id": TEST_TEMPLATE,
            "created_at": created_at,
        }
        row_seal = _domain_hmac(self._key, _ROW_DOMAIN, _canonical(material))
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO notification_push_templates"
                "(ref_hmac,template_id,created_at,row_seal) VALUES(?,?,?,?)",
                (ref_hmac, TEST_TEMPLATE, created_at, row_seal),
            )

    def resolve_template(
        self, payload_ref: outbox_mod.OpaquePayloadRef
    ) -> adapter_mod.PushTemplate | None:
        ref_hmac = _domain_hmac(
            self._key, _REF_DOMAIN, _payload_ref_value(payload_ref)
        )
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM notification_push_templates WHERE ref_hmac=?",
                (ref_hmac,),
            ).fetchone()
        if row is None:
            return None
        material = {
            "ref_hmac": row["ref_hmac"],
            "template_id": row["template_id"],
            "created_at": row["created_at"],
        }
        expected = _domain_hmac(self._key, _ROW_DOMAIN, _canonical(material))
        if not hmac.compare_digest(str(row["row_seal"]), expected):
            raise WebPushRuntimeError("notification template binding is corrupt")
        if row["template_id"] != TEST_TEMPLATE:
            raise WebPushRuntimeError("notification template is not allowlisted")
        return adapter_mod.PushTemplate(TEST_TITLE, TEST_BODY)

    def discard_template(self, payload_ref: outbox_mod.OpaquePayloadRef) -> None:
        ref_hmac = _domain_hmac(
            self._key, _REF_DOMAIN, _payload_ref_value(payload_ref)
        )
        with connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM notification_push_templates WHERE ref_hmac=?",
                (ref_hmac,),
            )

    def issue_ack_receipt(
        self,
        *,
        event_id: str,
        subscription_id: str,
        transport_idempotency_key: str,
    ) -> str:
        clean_event = adapter_mod._event_id(event_id)
        clean_subscription = adapter_mod._subscription_id(subscription_id)
        if type(transport_idempotency_key) is not str or not transport_idempotency_key.startswith("txi_"):
            raise WebPushRuntimeError("transport idempotency key is invalid")
        token = "wpa_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
        receipt_hmac = _domain_hmac(self._key, _RECEIPT_DOMAIN, token)
        transport_hmac = _domain_hmac(
            self._key, _TRANSPORT_DOMAIN, transport_idempotency_key
        )
        expires_at = _now(self._clock()) + ACK_TTL_SECONDS
        material = {
            "receipt_hmac": receipt_hmac,
            "event_id": clean_event,
            "subscription_id": clean_subscription,
            "transport_hmac": transport_hmac,
            "expires_at": expires_at,
            "reserved_at": None,
            "consumed_at": None,
        }
        row_seal = _domain_hmac(self._key, _ROW_DOMAIN, _canonical(material))
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO notification_push_ack_receipts"
                "(receipt_hmac,event_id,subscription_id,transport_hmac,expires_at,reserved_at,consumed_at,row_seal) "
                "VALUES(?,?,?,?,?,NULL,NULL,?)",
                (
                    receipt_hmac,
                    clean_event,
                    clean_subscription,
                    transport_hmac,
                    expires_at,
                    row_seal,
                ),
            )
        return token

    def _receipt_row(self, *, event_id: str, receipt: str) -> sqlite3.Row | None:
        clean_event = adapter_mod._event_id(event_id)
        if type(receipt) is not str or _RECEIPT_RE.fullmatch(receipt) is None:
            return None
        receipt_hmac = _domain_hmac(self._key, _RECEIPT_DOMAIN, receipt)
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM notification_push_ack_receipts WHERE receipt_hmac=?",
                (receipt_hmac,),
            ).fetchone()
        if row is None or row["event_id"] != clean_event:
            return None
        material = {
            "receipt_hmac": row["receipt_hmac"],
            "event_id": row["event_id"],
            "subscription_id": row["subscription_id"],
            "transport_hmac": row["transport_hmac"],
            "expires_at": row["expires_at"],
            "reserved_at": row["reserved_at"],
            "consumed_at": row["consumed_at"],
        }
        expected = _domain_hmac(self._key, _ROW_DOMAIN, _canonical(material))
        if not hmac.compare_digest(str(row["row_seal"]), expected):
            # Rows created before reservation support did not seal a
            # ``reserved_at`` field. Accept only that exact legacy shape; the
            # first reservation upgrades the seal before acknowledgement.
            legacy_material = {
                key: value
                for key, value in material.items()
                if key != "reserved_at"
            }
            legacy_expected = _domain_hmac(
                self._key, _ROW_DOMAIN, _canonical(legacy_material)
            )
            if row["reserved_at"] is not None or not hmac.compare_digest(
                str(row["row_seal"]), legacy_expected
            ):
                raise WebPushRuntimeError("acknowledgement receipt row is corrupt")
        return row

    def verify_ack_receipt(self, *, event_id: str, receipt: str) -> bool:
        row = self._receipt_row(event_id=event_id, receipt=receipt)
        return bool(
            row is not None
            and row["consumed_at"] is None
            and (
                row["reserved_at"] is not None
                or _now(self._clock()) < float(row["expires_at"])
            )
        )

    def reserve_ack_receipt(self, *, event_id: str, receipt: str) -> bool:
        row = self._receipt_row(event_id=event_id, receipt=receipt)
        if row is None:
            return False
        now = _now(self._clock())
        if row["consumed_at"] is not None:
            return False
        if row["reserved_at"] is not None:
            return True
        if now >= float(row["expires_at"]):
            return False
        material = {
            "receipt_hmac": row["receipt_hmac"],
            "event_id": row["event_id"],
            "subscription_id": row["subscription_id"],
            "transport_hmac": row["transport_hmac"],
            "expires_at": row["expires_at"],
            "reserved_at": now,
            "consumed_at": None,
        }
        row_seal = _domain_hmac(self._key, _ROW_DOMAIN, _canonical(material))
        with connect(self.db_path) as conn:
            result = conn.execute(
                "UPDATE notification_push_ack_receipts "
                "SET reserved_at=?,row_seal=? "
                "WHERE receipt_hmac=? AND reserved_at IS NULL "
                "AND consumed_at IS NULL AND expires_at>?",
                (now, row_seal, row["receipt_hmac"], now),
            )
        return bool(result.rowcount == 1)

    def consume_ack_receipt(self, *, event_id: str, receipt: str) -> bool:
        row = self._receipt_row(event_id=event_id, receipt=receipt)
        if row is None:
            return False
        now = _now(self._clock())
        if (
            row["reserved_at"] is None
            or row["consumed_at"] is not None
        ):
            return False
        material = {
            "receipt_hmac": row["receipt_hmac"],
            "event_id": row["event_id"],
            "subscription_id": row["subscription_id"],
            "transport_hmac": row["transport_hmac"],
            "expires_at": row["expires_at"],
            "reserved_at": row["reserved_at"],
            "consumed_at": now,
        }
        row_seal = _domain_hmac(self._key, _ROW_DOMAIN, _canonical(material))
        with connect(self.db_path) as conn:
            result = conn.execute(
                "UPDATE notification_push_ack_receipts SET consumed_at=?,row_seal=? "
                "WHERE receipt_hmac=? AND reserved_at=? AND consumed_at IS NULL",
                (now, row_seal, row["receipt_hmac"], row["reserved_at"]),
            )
        return bool(result.rowcount == 1)

    def public_status(self) -> dict[str, object]:
        return {
            "subscription_count": len(self.subscriptions()),
            "subscription_cap": MAX_SUBSCRIPTIONS,
            "template_scope": TEST_TEMPLATE,
        }


@dataclass(frozen=True, slots=True)
class VapidMaterial:
    private_key: str = field(repr=False)
    public_key: str


def load_or_create_protected_secret(record: CredentialRecord) -> str:
    """Read or create one dedicated credential without touching other targets."""
    if not isinstance(record, CredentialRecord):
        raise TypeError("record must implement CredentialRecord")
    value = record.read()
    if value is None:
        value = secrets.token_urlsafe(48)
        record.write(value)
    if type(value) is not str or len(value.encode("utf-8")) < 32:
        raise WebPushRuntimeError("protected runtime secret is malformed")
    return value


def load_or_create_vapid(record: CredentialRecord) -> VapidMaterial:
    """Load or initialize one raw P-256 private key in a dedicated credential."""
    if not isinstance(record, CredentialRecord):
        raise TypeError("record must implement CredentialRecord")
    raw = record.read()
    if raw is None:
        from cryptography.hazmat.primitives.asymmetric import ec

        private = ec.generate_private_key(ec.SECP256R1())
        value = private.private_numbers().private_value.to_bytes(32, "big")
        raw = base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
        record.write(raw)
    try:
        padded = raw + "=" * (-len(raw) % 4)
        key_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise WebPushRuntimeError("protected VAPID key is malformed") from exc
    if len(key_bytes) != 32:
        raise WebPushRuntimeError("protected VAPID key is malformed")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.derive_private_key(int.from_bytes(key_bytes, "big"), ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_key = base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")
    return VapidMaterial(private_key=raw, public_key=public_key)


class _NoRedirectSession:
    """Lazy requests session that ignores proxy environment and redirects."""

    def __init__(self) -> None:
        import requests

        class Session(requests.Session):
            def post(self, url, *args, **kwargs):
                kwargs["allow_redirects"] = False
                return super().post(url, *args, **kwargs)

        self.session = Session()
        self.session.trust_env = False


def _classify_web_push_response(response: object) -> adapter_mod.PushTransportResult:
    status = getattr(response, "status_code", None)
    if type(status) is not int:
        return adapter_mod.PushTransportResult(adapter_mod.UNKNOWN)
    if status in {201, 202}:
        return adapter_mod.PushTransportResult(adapter_mod.ACCEPTED)
    if 400 <= status <= 499 and status not in {408, 425, 429}:
        return adapter_mod.PushTransportResult(
            adapter_mod.REJECTED,
            stale_subscription=status in {404, 410},
        )
    return adapter_mod.PushTransportResult(adapter_mod.UNKNOWN)


class PyWebPushTransport(adapter_mod.WebPushTransport):
    """Open-source Web Push transport with one fixed no-redirect attempt."""

    def __init__(
        self,
        vapid: VapidMaterial,
        *,
        subject: str = "mailto:creator@alpecca.local",
        timeout_seconds: float = 8.0,
    ) -> None:
        if not isinstance(vapid, VapidMaterial):
            raise TypeError("vapid must be VapidMaterial")
        if type(subject) is not str or not subject.startswith("mailto:"):
            raise ValueError("VAPID subject must be a mailto URI")
        if not isinstance(timeout_seconds, (int, float)) or not 1 <= float(timeout_seconds) <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self._vapid = vapid
        self._subject = subject
        self._timeout = float(timeout_seconds)

    def send(
        self,
        *,
        subscription: adapter_mod.PushSubscription,
        payload: dict[str, object],
        transport_idempotency_key: str,
    ) -> adapter_mod.PushTransportResult:
        if not isinstance(subscription, adapter_mod.PushSubscription):
            raise TypeError("subscription must be PushSubscription")
        encoded = _canonical(payload)
        if len(encoded.encode("utf-8")) > 2048:
            raise WebPushRuntimeError("push payload exceeds its fixed bound")
        topic = base64.urlsafe_b64encode(
            hashlib.sha256(transport_idempotency_key.encode("ascii")).digest()[:18]
        ).rstrip(b"=").decode("ascii")
        try:
            from pywebpush import WebPushException, webpush
        except ImportError as exc:
            raise WebPushRuntimeError("pywebpush is not installed") from exc
        session = _NoRedirectSession().session
        try:
            response = webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=encoded,
                vapid_private_key=self._vapid.private_key,
                vapid_claims={"sub": self._subject},
                timeout=self._timeout,
                ttl=300,
                headers={"Topic": topic, "Urgency": "normal"},
                requests_session=session,
            )
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            if response is None:
                return adapter_mod.PushTransportResult(adapter_mod.UNKNOWN)
            return _classify_web_push_response(response)
        except Exception:
            return adapter_mod.PushTransportResult(adapter_mod.UNKNOWN)
        return _classify_web_push_response(response)


def enqueue_connection_test(
    outbox: outbox_mod.NotificationOutbox,
    store: WebPushPrivateStore,
) -> dict[str, object]:
    """Enqueue the only server-owned template available in this first slice."""
    payload_ref = outbox.mint_payload_ref()
    store.bind_test_template(payload_ref)
    try:
        return outbox.enqueue(
            idempotency_key="idem_" + secrets.token_hex(16),
            category="connection_test",
            adapter_name=adapter_mod.ADAPTER_NAME,
            payload_ref=payload_ref,
        )
    except Exception:
        store.discard_template(payload_ref)
        raise


__all__ = [
    "ACK_TTL_SECONDS",
    "CredentialRecord",
    "MAX_SUBSCRIPTIONS",
    "PyWebPushTransport",
    "TEST_TEMPLATE",
    "VapidMaterial",
    "WebPushPrivateStore",
    "WebPushRuntimeError",
    "WindowsCredentialRecord",
    "enqueue_connection_test",
    "load_or_create_vapid",
    "load_or_create_protected_secret",
]
