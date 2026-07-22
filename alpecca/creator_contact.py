"""Private, bounded outbound contact with CreatorJD.

Alpecca can reach her creator through three independent transports: an app
notification (Web Push), a Discord DM, and SMS. Destinations and provider
credentials are resolved here, outside the model. No caller receives the phone
number, bot token, push keys, or provider credentials.

Delivery is deliberately an alert path, not a second copy of Alpecca. Replies
still enter the single CoreMind through the normal authenticated app/Discord
bridges. Every delivery is rate-limited, locally audited, and redacted.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

from config import DB_PATH, HOME, CreatorContact as ContactCfg

_DISCORD_SECRET = HOME / "secrets" / "alpecca_discord.env"
_VAPID_PRIVATE = HOME / "secrets" / "alpecca_vapid_private.pem"
_PRIORITIES = {"social", "important", "critical"}
_CHANNELS = {"app", "discord", "sms"}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _settings() -> dict[str, str]:
    values = _read_env_file(ContactCfg.SECRET_FILE)
    # Discord already has a separate established secret file; reuse it without
    # copying its bot token into the new contact file.
    for key, value in _read_env_file(_DISCORD_SECRET).items():
        values.setdefault(key, value)
    for key, value in os.environ.items():
        if value:
            values[key] = value
    return values


def _creator_discord_id(values: dict[str, str]) -> str:
    explicit = values.get("ALPECCA_DISCORD_CREATOR_ID", "").strip()
    if explicit.isdigit():
        return explicit
    allow = values.get("ALPECCA_DISCORD_DM_ALLOW", "")
    for candidate in allow.split(","):
        candidate = candidate.strip()
        if candidate.isdigit():
            return candidate
    return ""


def _connect(db_path: Path):
    from alpecca.db import connect
    return connect(db_path)


def init_db(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS creator_push_subscriptions (
                endpoint TEXT PRIMARY KEY,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                user_agent TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                last_seen REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS creator_contact_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                priority TEXT NOT NULL,
                reason TEXT NOT NULL,
                message_hash TEXT NOT NULL,
                channels TEXT NOT NULL,
                results TEXT NOT NULL,
                acknowledged_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_creator_contact_recent
                ON creator_contact_events(reason, message_hash, ts DESC);
            """
        )


def save_push_subscription(subscription: dict, user_agent: str = "",
                           db_path: Path = DB_PATH) -> dict:
    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") if isinstance(subscription.get("keys"), dict) else {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not endpoint.startswith("https://") or not p256dh or not auth:
        raise ValueError("invalid Web Push subscription")
    now = time.time()
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO creator_push_subscriptions(endpoint,p256dh,auth,user_agent,created_at,last_seen) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET "
            "p256dh=excluded.p256dh,auth=excluded.auth,user_agent=excluded.user_agent,last_seen=excluded.last_seen",
            (endpoint, p256dh, auth, (user_agent or "")[:300], now, now),
        )
    return {"ok": True, "channel": "app", "subscribed": True}


def remove_push_subscription(endpoint: str, db_path: Path = DB_PATH) -> bool:
    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM creator_push_subscriptions WHERE endpoint=?", (endpoint,))
        return bool(cur.rowcount)


def _push_rows(db_path: Path = DB_PATH) -> list[dict]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT endpoint,p256dh,auth,user_agent,created_at,last_seen "
            "FROM creator_push_subscriptions ORDER BY last_seen DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def _ensure_vapid_key() -> tuple[Path | None, str]:
    """Return the local private-key path and browser-safe public key.

    The key is generated once in data/secrets. Failure is a clean disabled
    state so an optional push dependency can never break chat startup.
    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except Exception:
        return None, ""
    try:
        _VAPID_PRIVATE.parent.mkdir(parents=True, exist_ok=True)
        if _VAPID_PRIVATE.exists():
            private = serialization.load_pem_private_key(
                _VAPID_PRIVATE.read_bytes(), password=None,
            )
        else:
            private = ec.generate_private_key(ec.SECP256R1())
            pem = private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            _VAPID_PRIVATE.write_bytes(pem)
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        return _VAPID_PRIVATE, base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")
    except Exception:
        return None, ""


def public_push_key() -> str:
    return _ensure_vapid_key()[1]


def configured_channels(db_path: Path = DB_PATH) -> dict[str, bool]:
    values = _settings()
    private_key, public_key = _ensure_vapid_key()
    try:
        import pywebpush  # noqa: F401
        push_library = True
    except Exception:
        push_library = False
    sms_backend = (values.get("ALPECCA_SMS_BACKEND") or ContactCfg.SMS_BACKEND).lower()
    if sms_backend == "openclaw":
        sms_ready = bool(values.get("ALPECCA_CREATOR_PHONE"))
    else:
        sms_ready = all(values.get(k) for k in (
            "ALPECCA_CREATOR_PHONE", "ALPECCA_TWILIO_ACCOUNT_SID",
            "ALPECCA_TWILIO_AUTH_TOKEN", "ALPECCA_TWILIO_FROM_NUMBER",
        ))
    return {
        "app": bool(private_key and public_key and push_library and _push_rows(db_path)),
        "discord": bool(values.get("DISCORD_BOT_TOKEN") and _creator_discord_id(values)),
        "sms": bool(sms_ready),
    }


def status(db_path: Path = DB_PATH) -> dict:
    channels = configured_channels(db_path)
    return {
        "enabled": bool(ContactCfg.ENABLED),
        "channels": channels,
        "configured_count": sum(1 for ready in channels.values() if ready),
        "push_subscriptions": len(_push_rows(db_path)),
        "privacy": "destinations are private and excluded from model prompts and delivery logs",
    }


def _send_app(message: str, title: str, event_id: int,
              db_path: Path = DB_PATH) -> dict:
    private_key, _public = _ensure_vapid_key()
    rows = _push_rows(db_path)
    if not private_key or not rows:
        return {"ok": False, "reason": "no subscribed phone app"}
    try:
        from pywebpush import WebPushException, webpush
    except Exception:
        return {"ok": False, "reason": "pywebpush is not installed"}
    values = _settings()
    payload = json.dumps({
        "title": title[:80],
        "body": message[:ContactCfg.MAX_MESSAGE_CHARS],
        "url": f"/?contact_event={event_id}",
        "tag": f"alpecca-contact-{event_id}",
        "event_id": event_id,
    })
    sent = 0
    stale: list[str] = []
    errors: list[str] = []
    for row in rows:
        sub = {
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
        }
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=str(private_key),
                vapid_claims={
                    "sub": values.get("ALPECCA_VAPID_SUBJECT", "mailto:creator@alpecca.local"),
                },
                timeout=ContactCfg.HTTP_TIMEOUT_S,
            )
            sent += 1
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in {404, 410}:
                stale.append(row["endpoint"])
            else:
                errors.append(f"HTTP {code}" if code else type(exc).__name__)
        except Exception as exc:
            errors.append(type(exc).__name__)
    for endpoint in stale:
        remove_push_subscription(endpoint, db_path)
    return {
        "ok": sent > 0,
        "sent": sent,
        "stale_removed": len(stale),
        "errors": errors[:3],
        "destination": "creator_phone_app",
    }


def _json_request(url: str, *, method: str, body: dict, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=ContactCfg.HTTP_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _send_discord(message: str) -> dict:
    values = _settings()
    token = values.get("DISCORD_BOT_TOKEN", "").strip()
    creator_id = _creator_discord_id(values)
    if not token or not creator_id:
        return {"ok": False, "reason": "creator Discord DM is not configured"}
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "AlpeccaCreatorContact/1.0",
    }
    try:
        dm = _json_request(
            "https://discord.com/api/v10/users/@me/channels",
            method="POST", body={"recipient_id": creator_id}, headers=headers,
        )
        channel_id = str(dm.get("id") or "")
        if not channel_id:
            return {"ok": False, "reason": "Discord did not create a DM channel"}
        _json_request(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            method="POST", body={"content": message[:2000]}, headers=headers,
        )
        return {"ok": True, "destination": "creator_discord_dm"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reason": f"Discord HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "reason": f"Discord {type(exc).__name__}"}


def _send_sms(message: str) -> dict:
    values = _settings()
    phone = values.get("ALPECCA_CREATOR_PHONE", "").strip()
    backend = (values.get("ALPECCA_SMS_BACKEND") or ContactCfg.SMS_BACKEND).lower()
    if not phone:
        return {"ok": False, "reason": "creator phone is not configured"}
    if backend == "openclaw":
        try:
            from alpecca import openclaw_bridge
            result = openclaw_bridge.try_deliver(message, reply_target=f"sms:{phone}")
            return {
                "ok": bool(result.get("ok")),
                "queued": bool(result.get("queued")),
                "reason": result.get("reason", ""),
                "destination": "creator_phone",
            }
        except Exception as exc:
            return {"ok": False, "reason": f"OpenClaw {type(exc).__name__}"}
    sid = values.get("ALPECCA_TWILIO_ACCOUNT_SID", "").strip()
    auth = values.get("ALPECCA_TWILIO_AUTH_TOKEN", "").strip()
    from_number = values.get("ALPECCA_TWILIO_FROM_NUMBER", "").strip()
    if not (sid and auth and from_number):
        return {"ok": False, "reason": "Twilio SMS credentials are not configured"}
    form = urllib.parse.urlencode({
        "To": phone,
        "From": from_number,
        "Body": message[:1600],
    }).encode("utf-8")
    basic = base64.b64encode(f"{sid}:{auth}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=form,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=ContactCfg.HTTP_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
        return {
            "ok": bool(payload.get("sid")),
            "provider_status": str(payload.get("status") or "queued"),
            "destination": "creator_phone",
        }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reason": f"SMS provider HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "reason": f"SMS provider {type(exc).__name__}"}


def _cooldown(priority: str) -> float:
    if priority == "critical":
        return ContactCfg.CRITICAL_COOLDOWN_S
    if priority == "important":
        return ContactCfg.IMPORTANT_COOLDOWN_S
    return ContactCfg.SOCIAL_COOLDOWN_S


def _recent_duplicate(reason: str, message_hash: str, priority: str,
                      db_path: Path) -> dict | None:
    cutoff = time.time() - _cooldown(priority)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM creator_contact_events WHERE reason=? AND message_hash=? "
            "AND ts>=? ORDER BY id DESC LIMIT 1",
            (reason, message_hash, cutoff),
        ).fetchone()
    return dict(row) if row else None


def notify_creator(message: str, *, reason: str, priority: str = "important",
                   channels: Iterable[str] | None = None, force: bool = False,
                   db_path: Path = DB_PATH) -> dict:
    """Deliver one redacted/audited creator alert through configured channels."""
    if not ContactCfg.ENABLED:
        return {"ok": False, "attempted": False, "reason": "creator contact disabled"}
    clean = " ".join(str(message or "").split())[:ContactCfg.MAX_MESSAGE_CHARS]
    clean_reason = "_".join(str(reason or "contact").lower().split())[:80] or "contact"
    priority = str(priority or "important").lower()
    if priority not in _PRIORITIES:
        raise ValueError("priority must be social, important, or critical")
    if not clean:
        raise ValueError("contact message is empty")
    init_db(db_path)
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    duplicate = None if force else _recent_duplicate(clean_reason, digest, priority, db_path)
    if duplicate:
        return {
            "ok": False,
            "attempted": False,
            "rate_limited": True,
            "event_id": int(duplicate["id"]),
        }
    requested = [str(c).lower() for c in (channels or []) if str(c).lower() in _CHANNELS]
    if not requested:
        requested = ["app"] if priority == "social" else (
            ["app", "discord"] if priority == "important" else ["app", "discord", "sms"]
        )
    requested = list(dict.fromkeys(requested))
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO creator_contact_events(ts,priority,reason,message_hash,channels,results) "
            "VALUES(?,?,?,?,?,?)",
            (time.time(), priority, clean_reason, digest, json.dumps(requested), "{}"),
        )
        event_id = int(cur.lastrowid)
    title = "Alpecca needs you" if priority == "critical" else "Alpecca"
    senders = {
        "app": lambda: _send_app(clean, title, event_id, db_path),
        "discord": lambda: _send_discord(clean),
        "sms": lambda: _send_sms(clean),
    }
    results: dict[str, dict] = {}
    for channel in requested:
        try:
            results[channel] = senders[channel]()
        except Exception as exc:
            results[channel] = {"ok": False, "reason": type(exc).__name__}
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE creator_contact_events SET results=? WHERE id=?",
            (json.dumps(results, sort_keys=True), event_id),
        )
    try:
        from alpecca import cognition as cognition_mod
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="creator_contact",
            room="system",
            content=f"Creator contact event {event_id}: {clean_reason} ({priority}).",
            confidence=1.0,
            privacy_class="private",
            metadata={
                "event_id": event_id,
                "reason": clean_reason,
                "priority": priority,
                "channels": requested,
                "delivery": {name: bool(result.get("ok")) for name, result in results.items()},
            },
        ))
    except Exception:
        pass
    return {
        "ok": any(result.get("ok") for result in results.values()),
        "attempted": True,
        "event_id": event_id,
        "priority": priority,
        "results": results,
    }


def acknowledge(event_id: int, db_path: Path = DB_PATH) -> bool:
    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE creator_contact_events SET acknowledged_at=? "
            "WHERE id=? AND acknowledged_at IS NULL",
            (time.time(), int(event_id)),
        )
    return bool(cur.rowcount)


def recent_events(limit: int = 20, db_path: Path = DB_PATH) -> list[dict]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id,ts,priority,reason,channels,results,acknowledged_at "
            "FROM creator_contact_events ORDER BY id DESC LIMIT ?",
            (max(1, min(100, int(limit))),),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        for key in ("channels", "results"):
            try:
                item[key] = json.loads(item[key])
            except Exception:
                item[key] = [] if key == "channels" else {}
        out.append(item)
    return out
