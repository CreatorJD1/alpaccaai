"""Mindscape continuity snapshots for Alpecca.

Mindscape is the phone/cloud shell for continuity when the local machine is
unavailable. The snapshot is intentionally compact: enough identity, state,
memory, intent, and runtime health to let an online shell continue the thread,
without uploading raw private sensor data by default.
"""
from __future__ import annotations

import time
import json
import hashlib
import re
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from config import DB_PATH

KV_PLACEHOLDER = "replace-with-your-kv-namespace-id"
KV_NAMESPACE_ID_RE = re.compile(r"^[a-f0-9]{16,64}$", re.I)


@contextmanager
def _connect(db_path: Path):
    # Delegates to alpecca.db.connect -- the one hardened opener
    # (busy_timeout, commit-on-exit, always-close). See alpecca/db.py.
    from alpecca.db import connect as _db_connect
    with _db_connect(db_path) as conn:
        yield conn


def init_restore_db(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mindscape_restores (
                fingerprint TEXT PRIMARY KEY,
                ts          REAL NOT NULL,
                snapshot_ts REAL,
                source      TEXT,
                summary     TEXT
            )
            """
        )


def continuity_snapshot(*, state: dict, cognition: dict, memories: list[dict],
                        journal: dict, runtime: dict, home: dict,
                        cloud_url: str = "", enabled: bool = True) -> dict:
    intent = cognition.get("intent") or {}
    models = runtime.get("models") or {}
    voice = runtime.get("voice") or {}
    issues = runtime.get("issues") or []
    chat_turns = []
    for turn in (cognition.get("recent_chat_turns") or [])[:8]:
        chat_turns.append({
            "ts": turn.get("ts", 0),
            "room": str(turn.get("room", ""))[:80],
            "mood": str(turn.get("mood", ""))[:80],
            "intent": str(turn.get("intent", ""))[:80],
            "user_text": str(turn.get("user_text", ""))[:600],
            "reply": str(turn.get("reply", ""))[:900],
            "model_use": turn.get("model_use") or {},
            "memory_evidence": (turn.get("memory_evidence") or [])[:6],
        })
    return {
        "name": "Alpecca Mindscape",
        "version": 1,
        "enabled": bool(enabled),
        "ts": time.time(),
        "continuity": {
            "mode": "cloud-ready" if cloud_url else "local-mobile",
            "cloud_url": cloud_url,
            "local_chat_ready": bool(models.get("chat_ready")),
            "runtime_level": runtime.get("level", "unknown"),
            "can_fallback_online": bool(cloud_url),
            "note": (
                "Mindscape preserves continuity data for fallback; it is not a "
                "claim of literal consciousness or immortality."
            ),
        },
        "self": {
            "mood": state.get("mood") or cognition.get("mood") or "",
            "emotion": state.get("state") or cognition.get("emotion") or {},
            "location": cognition.get("location") or home.get("location") or "",
            "intent": intent,
            "voice": {
                "name": voice.get("voice", ""),
                "tone": voice.get("tone", ""),
                "server_ready": bool(voice.get("server_voice_ready")),
            },
        },
        "memory": {
            "counts": cognition.get("memory_counts") or {},
            "recent": [
                {
                    "kind": m.get("kind", "memory"),
                    "content": str(m.get("content", ""))[:600],
                    "salience": m.get("salience", 0),
                }
                for m in (memories or [])[:20]
            ],
        },
        "journal": {
            "open_questions": (journal.get("open_questions") or [])[:12],
            "recent": (journal.get("recent") or [])[:12],
        },
        "observations": (cognition.get("recent_observations") or [])[:12],
        "chat_turns": chat_turns,
        "proposals": (cognition.get("action_proposals") or [])[:12],
        "proposal_evaluations": (cognition.get("proposal_evaluations")
                                 or cognition.get("evaluations") or [])[:12],
        "improvement_summary": cognition.get("improvement_summary") or {},
        "home": {
            "location": home.get("location", ""),
            "rooms": home.get("rooms", []),
        },
        "runtime": {
            "level": runtime.get("level", "unknown"),
            "models": models,
            "senses": runtime.get("senses", {}),
            "issues": issues,
        },
    }


def summary(snapshot: dict[str, Any]) -> dict:
    """Small status card for health checks and mobile headers."""
    continuity = snapshot.get("continuity") or {}
    self_state = snapshot.get("self") or {}
    runtime = snapshot.get("runtime") or {}
    return {
        "ok": bool(snapshot.get("enabled")),
        "mode": continuity.get("mode", "local-mobile"),
        "cloud_ready": bool(continuity.get("cloud_url")),
        "runtime_level": runtime.get("level", "unknown"),
        "mood": self_state.get("mood", ""),
        "location": self_state.get("location", ""),
        "intent": (self_state.get("intent") or {}).get("name", "waiting"),
        "issues": runtime.get("issues", []),
        "ts": snapshot.get("ts", 0),
    }


def cloud_setup_plan(worker_dir: Path, *, cloud_url: str = "",
                     token_configured: bool = False) -> dict:
    """Return a concrete setup checklist for hosted Mindscape continuity.

    This is intentionally deterministic and side-effect free. It does not run
    Wrangler or create secrets; it gives the app and doctor one authoritative
    way to explain the remaining Cloudflare Worker steps.
    """
    worker_dir = Path(worker_dir)
    wrangler = worker_dir / "wrangler.toml"
    worker = worker_dir / "worker.js"
    readme = worker_dir / "README.md"
    wrangler_text = wrangler.read_text(encoding="utf-8") if wrangler.exists() else ""
    kv_placeholder = KV_PLACEHOLDER in wrangler_text or 'id = ""' in wrangler_text
    worker_ready = worker.exists() and "MINDSCAPE_KV" in worker.read_text(encoding="utf-8")
    template_ready = worker_dir.exists() and worker_ready and wrangler.exists() and readme.exists()
    cloud_configured = bool((cloud_url or "").strip())
    token_ready = bool(token_configured)
    steps = [
        {
            "id": "create_kv",
            "done": template_ready and not kv_placeholder,
            "label": "Create and bind the Mindscape KV namespace.",
            "command": "npx wrangler kv namespace create MINDSCAPE_KV",
            "helper": "python ..\\..\\scripts\\setup_mindscape_worker.py --from-clipboard",
        },
        {
            "id": "set_secret",
            "done": token_ready,
            "label": "Set the private Mindscape sync token in Cloudflare.",
            "command": "npx wrangler secret put MINDSCAPE_TOKEN",
        },
        {
            "id": "deploy_worker",
            "done": cloud_configured,
            "label": "Deploy the Mindscape Worker and copy its /sync URL.",
            "command": "npx wrangler deploy",
        },
        {
            "id": "connect_local",
            "done": cloud_configured and token_ready,
            "label": "Point local Alpecca at the hosted Mindscape.",
            "command": (
                '$env:ALPECCA_MINDSCAPE_URL="https://alpecca-mindscape.<your-subdomain>.workers.dev/sync"; '
                '$env:ALPECCA_MINDSCAPE_TOKEN="same-secret-as-cloudflare"'
            ),
        },
    ]
    if not template_ready:
        status = "missing_template"
    elif kv_placeholder:
        status = "needs_kv"
    elif not token_ready:
        status = "needs_token"
    elif not cloud_configured:
        status = "needs_cloud_url"
    else:
        status = "configured"
    return {
        "ok": status == "configured",
        "status": status,
        "worker_dir": str(worker_dir),
        "template_ready": template_ready,
        "worker_ready": worker_ready,
        "wrangler_ready": wrangler.exists(),
        "kv_placeholder": kv_placeholder,
        "cloud_configured": cloud_configured,
        "token_configured": token_ready,
        "cloud_url": cloud_url,
        "steps": steps,
        "commands": {
            "open_worker_dir": f"cd {worker_dir}",
            "create_kv": "npx wrangler kv namespace create MINDSCAPE_KV",
            "apply_kv": "python ..\\..\\scripts\\setup_mindscape_worker.py --kv-id <namespace-id>",
            "set_secret": "npx wrangler secret put MINDSCAPE_TOKEN",
            "deploy": "npx wrangler deploy",
            "local_env": (
                '$env:ALPECCA_MINDSCAPE_URL="https://alpecca-mindscape.<your-subdomain>.workers.dev/sync"; '
                '$env:ALPECCA_MINDSCAPE_TOKEN="same-secret-as-cloudflare"'
            ),
        },
    }


def extract_kv_namespace_id(text: str) -> str:
    """Extract a Cloudflare KV namespace id from pasted Wrangler output.

    Wrangler has changed its printed shape over time: sometimes it returns JSON,
    sometimes a TOML snippet, sometimes a sentence with the id. This helper keeps
    the setup script forgiving while still rejecting obvious placeholders.
    """
    text = (text or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
        candidates: list[str] = []
        if isinstance(parsed, dict):
            for key in ("id", "namespace_id", "namespaceId"):
                value = parsed.get(key)
                if isinstance(value, str):
                    candidates.append(value)
            result = parsed.get("result")
            if isinstance(result, dict):
                for key in ("id", "namespace_id", "namespaceId"):
                    value = result.get(key)
                    if isinstance(value, str):
                        candidates.append(value)
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    value = item.get("id") or item.get("namespace_id") or item.get("namespaceId")
                    if isinstance(value, str):
                        candidates.append(value)
        for value in candidates:
            cleaned = value.strip().strip('"')
            if cleaned and cleaned != KV_PLACEHOLDER and KV_NAMESPACE_ID_RE.match(cleaned):
                return cleaned
    except Exception:
        pass
    for pattern in (
        r'id\s*=\s*"([^"]+)"',
        r'"id"\s*:\s*"([^"]+)"',
        r"namespace(?:\s+id)?[:\s]+([a-f0-9]{16,64})",
        r"\b([a-f0-9]{16,64})\b",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            candidate = match.group(1).strip()
            if candidate and candidate != KV_PLACEHOLDER and KV_NAMESPACE_ID_RE.match(candidate):
                return candidate
    return ""


def bind_worker_kv_namespace(wrangler_path: Path, namespace_id: str) -> dict:
    """Patch the Mindscape Worker wrangler.toml with a concrete KV id."""
    wrangler_path = Path(wrangler_path)
    namespace_id = extract_kv_namespace_id(namespace_id) or (namespace_id or "").strip()
    if not KV_NAMESPACE_ID_RE.match(namespace_id):
        return {"ok": False, "status": "invalid_namespace_id", "path": str(wrangler_path)}
    if not wrangler_path.exists():
        return {"ok": False, "status": "missing_wrangler", "path": str(wrangler_path)}
    text = wrangler_path.read_text(encoding="utf-8")
    if 'binding = "MINDSCAPE_KV"' not in text:
        return {"ok": False, "status": "missing_binding", "path": str(wrangler_path)}
    next_text = re.sub(
        r'(\[\[kv_namespaces\]\]\s+binding\s*=\s*"MINDSCAPE_KV"\s+id\s*=\s*")[^"]*(")',
        rf"\g<1>{namespace_id}\2",
        text,
        count=1,
        flags=re.S,
    )
    if next_text == text:
        return {"ok": False, "status": "binding_not_updated", "path": str(wrangler_path)}
    wrangler_path.write_text(next_text, encoding="utf-8")
    return {
        "ok": True,
        "status": "bound",
        "path": str(wrangler_path),
        "namespace_id": namespace_id,
    }


def snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
    """Stable id for restore idempotency."""
    stable = json.dumps(snapshot or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def restore_seen(fingerprint: str, db_path: Path = DB_PATH) -> dict | None:
    init_restore_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM mindscape_restores WHERE fingerprint=?",
            (fingerprint,),
        ).fetchone()
    return dict(row) if row else None


def mark_restored(snapshot: dict[str, Any], source: str = "",
                  summary_text: str = "", db_path: Path = DB_PATH) -> str:
    init_restore_db(db_path)
    fp = snapshot_fingerprint(snapshot)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO mindscape_restores "
            "(fingerprint, ts, snapshot_ts, source, summary) VALUES (?, ?, ?, ?, ?)",
            (fp, time.time(), float(snapshot.get("ts") or 0), source, summary_text[:1000]),
        )
    return fp


def mirror_snapshot(snapshot: dict[str, Any], cloud_url: str, token: str = "",
                    timeout: float = 8.0, opener=None) -> dict:
    """POST a continuity snapshot to a hosted Mindscape endpoint.

    The remote endpoint contract is intentionally tiny: accept JSON and return
    any 2xx response. Tokens are optional and sent in both a specific header and
    a standard bearer header so a simple Worker, Space, or small API can verify
    the mirror without custom client code.
    """
    cloud_url = (cloud_url or "").strip()
    if not cloud_url:
        return {
            "ok": False,
            "configured": False,
            "status": "not_configured",
            "message": "ALPECCA_MINDSCAPE_URL is not set.",
        }
    if not (cloud_url.startswith("https://") or cloud_url.startswith("http://127.0.0.1")
            or cloud_url.startswith("http://localhost")):
        return {
            "ok": False,
            "configured": True,
            "status": "blocked_url",
            "message": "Mindscape cloud URLs must use https, except localhost for testing.",
        }
    payload = json.dumps({
        "type": "alpecca.mindscape.snapshot",
        "snapshot": snapshot,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Alpecca-Mindscape/1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Alpecca-Mindscape-Token"] = token
    req = urllib.request.Request(cloud_url, data=payload, headers=headers, method="POST")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=timeout) as resp:
            body = resp.read(2048).decode("utf-8", errors="replace")
            code = int(getattr(resp, "status", 200))
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return {
            "ok": False,
            "configured": True,
            "status": "sync_failed",
            "message": f"{type(exc).__name__}: {exc}",
        }
    return {
        "ok": 200 <= code < 300,
        "configured": True,
        "status": "synced" if 200 <= code < 300 else "rejected",
        "http_status": code,
        "message": body[:500],
    }


def snapshot_url_from_sync(cloud_url: str) -> str:
    cloud_url = (cloud_url or "").strip()
    if cloud_url.endswith("/sync"):
        return cloud_url[:-5] + "/snapshot"
    return cloud_url.rstrip("/") + "/snapshot"


def fetch_snapshot(cloud_url: str, token: str = "", timeout: float = 8.0,
                   opener=None) -> dict:
    """Fetch the latest hosted Mindscape snapshot."""
    url = snapshot_url_from_sync(cloud_url)
    if not cloud_url:
        return {"ok": False, "status": "not_configured", "message": "ALPECCA_MINDSCAPE_URL is not set."}
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1")
            or url.startswith("http://localhost")):
        return {"ok": False, "status": "blocked_url", "message": "Mindscape cloud URLs must use https, except localhost for testing."}
    headers = {"User-Agent": "Alpecca-Mindscape/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Alpecca-Mindscape-Token"] = token
    req = urllib.request.Request(url, headers=headers, method="GET")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
            code = int(getattr(resp, "status", 200))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": "fetch_failed", "message": f"{type(exc).__name__}: {exc}"}
    if not (200 <= code < 300):
        return {"ok": False, "status": "rejected", "http_status": code, "message": "remote snapshot request was rejected"}
    if data.get("name") == "Alpecca Mindscape":
        return {"ok": True, "status": "fetched", "snapshot": data}
    if data.get("snapshot", {}).get("name") == "Alpecca Mindscape":
        return {"ok": True, "status": "fetched", "snapshot": data["snapshot"]}
    return {"ok": False, "status": "invalid_snapshot", "message": "remote did not return an Alpecca Mindscape snapshot"}


def restore_preview(snapshot: dict[str, Any]) -> dict:
    """Summarize what a restore would merge, without mutating local state."""
    if not snapshot or snapshot.get("name") != "Alpecca Mindscape":
        return {"ok": False, "status": "invalid_snapshot", "message": "not an Alpecca Mindscape snapshot"}
    memory = snapshot.get("memory") or {}
    journal = snapshot.get("journal") or {}
    self_state = snapshot.get("self") or {}
    return {
        "ok": True,
        "status": "preview",
        "fingerprint": snapshot_fingerprint(snapshot),
        "snapshot_ts": snapshot.get("ts", 0),
        "location": self_state.get("location", ""),
        "mood": self_state.get("mood", ""),
        "intent": (self_state.get("intent") or {}).get("name", "waiting"),
        "memory_count": len(memory.get("recent") or []),
        "journal_recent_count": len(journal.get("recent") or []),
        "open_question_count": len(journal.get("open_questions") or []),
        "observation_count": len(snapshot.get("observations") or []),
        "chat_turn_count": len(snapshot.get("chat_turns") or []),
        "proposal_count": len(snapshot.get("proposals") or []),
        "proposal_evaluation_count": len(snapshot.get("proposal_evaluations") or []),
    }
