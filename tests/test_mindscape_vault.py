from __future__ import annotations

import json
import sqlite3
import tempfile
import urllib.error
from pathlib import Path

import pytest

from alpecca import mindscape_vault as vault


_SECRET = b"mindscape-vault-test-key-material-32-bytes-minimum"


def _snapshot(marker: str = "continuity marker") -> dict:
    return {
        "name": "Alpecca Mindscape",
        "version": 1,
        "enabled": True,
        "ts": 123.0,
        "self": {"mood": "curious", "intent": {"name": "remembering"}},
        "memory": {"recent": [{"kind": "relationship", "content": marker}]},
        "journal": {"recent": [], "open_questions": []},
        "observations": [],
        "chat_turns": [],
        "proposals": [],
    }


def test_seal_snapshot_is_opaque_and_round_trips():
    snapshot = _snapshot("Jason continuity marker should stay private")
    first = vault.seal_snapshot(snapshot, _SECRET, writer_id="a" * 32, sequence=1, created_at=123.0)
    second = vault.seal_snapshot(snapshot, _SECRET, writer_id="a" * 32, sequence=2, created_at=124.0)

    serialized = json.dumps(first)
    assert "Jason continuity marker" not in serialized
    assert first["nonce"] != second["nonce"]
    assert vault.unseal_snapshot(first, _SECRET) == snapshot

    tampered = dict(first)
    tampered["ciphertext"] = tampered["ciphertext"][:-1] + (
        "A" if tampered["ciphertext"][-1] != "A" else "B"
    )
    with pytest.raises(vault.VaultError):
        vault.unseal_snapshot(tampered, _SECRET)
    with pytest.raises(vault.VaultError):
        vault.unseal_snapshot(first, b"different-mindscape-vault-test-key-material-32")


def test_transport_token_accepts_an_explicit_recovery_environment_value():
    token, source = vault.load_or_create_transport_token(
        {vault.VAULT_TOKEN_ENV: "t" * 48},
    )
    assert token == "t" * 48
    assert source == "environment"
    with pytest.raises(vault.VaultError):
        vault.load_or_create_transport_token({vault.VAULT_TOKEN_ENV: "short"})


class _Response:
    def __init__(self, status: int = 201, body: dict | None = None, *, raw: bytes | None = None,
                 headers: dict[str, str] | None = None):
        self.status = status
        self._body = raw if raw is not None else json.dumps(body or {"ok": True, "status": "stored"}).encode("utf-8")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1):
        return self._body


def test_snapshot_outbox_retains_failure_then_uploads_opaque_payload():
    with tempfile.TemporaryDirectory() as directory:
        db = Path(directory) / "state.sqlite3"
        captured: dict[str, object] = {}

        def offline(_request, timeout=0):
            raise urllib.error.URLError("offline")

        first = vault.sync_snapshot(
            _snapshot("outbox private marker"),
            "https://vault.example",
            "v" * 32,
            _SECRET,
            db_path=db,
            opener=offline,
        )
        assert first["ok"] is False
        assert vault.local_status(db)["pending_snapshots"] == 1

        def online(request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = request.data
            return _Response()

        result = vault.flush_snapshots(
            "https://vault.example",
            "v" * 32,
            db_path=db,
            opener=online,
        )
        assert result["ok"] is True
        assert result["accepted"] == 1
        assert vault.local_status(db)["pending_snapshots"] == 0
        assert captured["url"] == "https://vault.example/v1/snapshot"
        assert captured["headers"]["Authorization"] == f"Bearer {'v' * 32}"
        assert b"outbox private marker" not in captured["body"]
        assert b'"envelope"' in captured["body"]


def test_archive_queue_encrypts_sqlite_and_flushes_it_without_plaintext():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.sqlite3"
        state = root / "state.sqlite3"
        conn = sqlite3.connect(source)
        try:
            conn.execute("CREATE TABLE memories (content TEXT NOT NULL)")
            conn.execute("INSERT INTO memories VALUES (?)", ("full database private marker",))
            conn.commit()
        finally:
            conn.close()

        metadata = vault.queue_database_archive(
            _SECRET,
            source_db=source,
            state_db=state,
            outbox_dir=root / "outbox",
            max_bytes=4 * 1024 * 1024,
        )
        assert metadata["kind"] == vault.ARCHIVE_KIND
        status = vault.local_status(state)
        assert status["pending_archives"] == 1

        captured: dict[str, object] = {}

        def online(request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = request.data
            return _Response()

        result = vault.flush_archives(
            "https://vault.example",
            "v" * 32,
            state_db=state,
            opener=online,
            max_bytes=4 * 1024 * 1024,
        )
        assert result["ok"] is True
        assert vault.local_status(state)["pending_archives"] == 0
        assert captured["url"] == "https://vault.example/v1/archive"
        assert captured["headers"]["Content-type"] == "application/octet-stream"
        assert b"full database private marker" not in captured["body"]


def test_archive_queue_removes_files_evicted_from_bounded_outbox():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.sqlite3"
        state = root / "state.sqlite3"
        conn = sqlite3.connect(source)
        try:
            conn.execute("CREATE TABLE memories (content TEXT NOT NULL)")
            conn.execute("INSERT INTO memories VALUES ('bounded archive')")
            conn.commit()
        finally:
            conn.close()

        for _ in range(vault.DEFAULT_ARCHIVE_OUTBOX_LIMIT + 2):
            vault.queue_database_archive(
                _SECRET,
                source_db=source,
                state_db=state,
                outbox_dir=root / "outbox",
                max_bytes=4 * 1024 * 1024,
            )

        assert vault.local_status(state)["pending_archives"] == vault.DEFAULT_ARCHIVE_OUTBOX_LIMIT
        assert len(tuple((root / "outbox").glob("archive-*.bin"))) == vault.DEFAULT_ARCHIVE_OUTBOX_LIMIT


def test_archive_orphan_prune_is_strict_and_dry_run_by_default():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state.sqlite3"
        outbox = root / "outbox"
        outbox.mkdir()
        vault.init_db(state)
        orphan = outbox / "archive-00000000000000000001-0123456789abcdef.bin"
        unrelated = outbox / "notes.bin"
        orphan.write_bytes(b"orphan ciphertext")
        unrelated.write_bytes(b"keep me")

        preview = vault.prune_local_archive_files(state_db=state, outbox_dir=outbox)
        assert preview["dry_run"] is True
        assert preview["eligible"] == 1
        assert preview["removed"] == 0
        assert orphan.exists()

        result = vault.prune_local_archive_files(
            state_db=state,
            outbox_dir=outbox,
            dry_run=False,
        )
        assert result["ok"] is True
        assert result["removed"] == 1
        assert not orphan.exists()
        assert unrelated.read_bytes() == b"keep me"


def test_archive_recovery_writes_a_verified_new_sqlite_file():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.sqlite3"
        state = root / "state.sqlite3"
        conn = sqlite3.connect(source)
        try:
            conn.execute("CREATE TABLE memories (content TEXT NOT NULL)")
            conn.execute("INSERT INTO memories VALUES (?)", ("recoverable private marker",))
            conn.commit()
        finally:
            conn.close()

        metadata = vault.queue_database_archive(
            _SECRET,
            source_db=source,
            state_db=state,
            outbox_dir=root / "outbox",
            max_bytes=4 * 1024 * 1024,
        )
        encrypted = next((root / "outbox").glob("archive-*.bin")).read_bytes()

        def archive_response(request, timeout=0):
            assert request.full_url == "https://vault.example/v1/archive/latest"
            return _Response(
                raw=encrypted,
                headers={"X-Alpecca-Mindscape-Vault-Metadata": vault._metadata_header(metadata)},
            )

        destination = root / "recovery" / "recovered.sqlite3"
        result = vault.fetch_latest_archive(
            "https://vault.example",
            "v" * 32,
            _SECRET,
            destination,
            opener=archive_response,
            max_bytes=4 * 1024 * 1024,
        )
        assert result["ok"] is True
        recovered = sqlite3.connect(destination)
        try:
            assert recovered.execute("SELECT content FROM memories").fetchone()[0] == "recoverable private marker"
        finally:
            recovered.close()


def test_vault_worker_contract_is_opaque_r2_only():
    root = Path(__file__).resolve().parent.parent
    worker = (root / "deploy" / "mindscape-vault-worker" / "worker.js").read_text(encoding="utf-8")
    config = (root / "deploy" / "mindscape-vault-worker" / "wrangler.toml").read_text(encoding="utf-8")

    assert "MINDSCAPE_VAULT_ARCHIVE" in worker
    assert "if-none-match" in worker
    assert "/v1/snapshot" in worker and "/v1/archive" in worker
    assert "MINDSCAPE_VAULT_TOKEN" in worker
    assert "plaintext_bytes" in worker and "ciphertext_bytes" in worker and "nonce" in worker
    assert "algorithm: metadata.algorithm" in worker
    assert "customMetadata?.created_at" in worker
    assert "late network retry" in worker
    assert "MINDSCAPE_VAULT_ARCHIVE" in config
    assert "r2_buckets" in config


def test_server_prefers_encrypted_vault_over_legacy_mirror(monkeypatch):
    import server

    legacy = (server.MINDSCAPE_ENABLED, server.MINDSCAPE_CLOUD_URL)
    vault_config = (server.MINDSCAPE_VAULT_ENABLED, server.MINDSCAPE_VAULT_URL, server.MINDSCAPE_VAULT_TOKEN)
    prior_status = dict(server._mindscape_vault_status)
    captured: dict[str, object] = {}
    try:
        server.MINDSCAPE_ENABLED = True
        server.MINDSCAPE_CLOUD_URL = "https://legacy.example/sync"
        server.MINDSCAPE_VAULT_ENABLED = True
        server.MINDSCAPE_VAULT_URL = "https://vault.example"
        server.MINDSCAPE_VAULT_TOKEN = "v" * 32
        monkeypatch.setattr(server.mindscape_vault_mod, "load_or_create_encryption_key", lambda: (_SECRET, "test"))

        def sync(snapshot, url, token, key, **_kwargs):
            captured.update(snapshot=snapshot, url=url, token=token, key=key)
            return {"ok": True, "status": "synced", "sequence": 4}

        monkeypatch.setattr(server.mindscape_vault_mod, "sync_snapshot", sync)
        result = server._mindscape_vault_mirror_snapshot(_snapshot())
        assert result["ok"] is True
        assert captured["url"] == "https://vault.example"
        assert captured["key"] == _SECRET
        assert server._legacy_mindscape_sync_configured() is False
        assert server._mindscape_sync_status_view()["active_cloud_target"] == "vault"
    finally:
        server.MINDSCAPE_ENABLED, server.MINDSCAPE_CLOUD_URL = legacy
        server.MINDSCAPE_VAULT_ENABLED, server.MINDSCAPE_VAULT_URL, server.MINDSCAPE_VAULT_TOKEN = vault_config
        server._mindscape_vault_status.clear()
        server._mindscape_vault_status.update(prior_status)


def test_server_vault_event_sync_uses_the_vault_attempt_clock():
    import server

    vault_config = (server.MINDSCAPE_VAULT_ENABLED, server.MINDSCAPE_VAULT_URL, server.MINDSCAPE_VAULT_TOKEN)
    prior_vault = dict(server._mindscape_vault_status)
    prior_legacy = dict(server._mindscape_sync_status)
    try:
        server.MINDSCAPE_VAULT_ENABLED = True
        server.MINDSCAPE_VAULT_URL = "https://vault.example"
        server.MINDSCAPE_VAULT_TOKEN = "v" * 32
        server._mindscape_sync_status["last_attempt"] = 0.0
        server._mindscape_vault_status["last_attempt"] = server._time.time()

        assert server._mindscape_request_event_sync("test") is False
        assert server._mindscape_vault_status["last_status"] == "event_sync_throttled"
    finally:
        server.MINDSCAPE_VAULT_ENABLED, server.MINDSCAPE_VAULT_URL, server.MINDSCAPE_VAULT_TOKEN = vault_config
        server._mindscape_vault_status.clear()
        server._mindscape_vault_status.update(prior_vault)
        server._mindscape_sync_status.clear()
        server._mindscape_sync_status.update(prior_legacy)
