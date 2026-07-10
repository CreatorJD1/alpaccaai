from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import capture_alpecca_baseline as baseline


TEST_PASSPHRASE = "stage0 fixture passphrase 2026"
WRONG_TEST_PASSPHRASE = "wrong stage0 fixture passphrase 2026"


def _fixture_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "data" / "avatar" / "vrm").mkdir(parents=True)
    (root / "data" / "alpecca_art_source" / "vrm_experiments").mkdir(
        parents=True
    )
    db_path = root / "data" / "alpecca.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, content TEXT)")
        conn.execute("INSERT INTO memories(content) VALUES (?)", ("private memory",))
    (root / "data" / "avatar" / "vrm" / "alpecca.vrm").write_bytes(
        b"private-vrm-payload"
    )
    (root / "server.py").write_text(
        "@app.get('/health')\ndef health():\n    return {}\n",
        encoding="utf-8",
    )
    (root / "START_HERE.bat").write_text(
        'set "ALPECCA_MODEL=qwen3.5:9b"\n'
        'set "ALPECCA_ACCESS_TOKEN=not-a-real-secret-token-value"\n',
        encoding="utf-8",
    )
    return root


def _write_test_zip(
    path: Path,
    files: dict[str, bytes],
    *,
    archive_id: str = "stage0-test-archive",
    sha_overrides: dict[str, str] | None = None,
) -> str:
    inventory = {
        "project": "Alpecca",
        "schema": "alpecca.stage0.inventory.v1",
    }
    overrides = sha_overrides or {}
    records = [
        {
            "archive_path": name,
            "bytes": len(payload),
            "sha256": overrides.get(name, hashlib.sha256(payload).hexdigest()),
            "source_path": name,
        }
        for name, payload in files.items()
    ]
    manifest = {
        "archive_id": archive_id,
        "files": records,
        "inventory_sha256": hashlib.sha256(
            baseline._canonical_json(inventory)
        ).hexdigest(),
        "project": "Alpecca",
        "schema": "alpecca.stage0.manifest.v1",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", baseline._canonical_json(manifest))
        archive.writestr("inventory.json", baseline._canonical_json(inventory))
        for name, payload in files.items():
            archive.writestr(name, payload)
    return archive_id


def _encrypt_test_payload(
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    destination: Path,
    *,
    archive_id: str = "stage0-test-archive",
) -> str:
    key = b"K" * 32
    salt = b"S" * 16
    monkeypatch.setattr(
        baseline,
        "_derive_passphrase_key",
        lambda passphrase, supplied_salt, params: key,
    )
    header = {
        "archive_id": archive_id,
        "created_at": "2026-07-10T00:00:00+00:00",
        "kdf": {
            **baseline.NEW_SCRYPT_PARAMS,
            "name": "scrypt",
            "salt": base64.b64encode(salt).decode("ascii"),
        },
        "key_mode": "passphrase",
        "plaintext_sha256": baseline._sha256_file(source),
        "project": "Alpecca",
        "schema": "alpecca.stage0.envelope.v1",
    }
    baseline._encrypt_file(source, destination, key, header)
    return TEST_PASSPHRASE


def test_passphrase_capture_verify_and_restore(tmp_path: Path):
    root = _fixture_repo(tmp_path)
    result = baseline.capture_baseline(
        root,
        tmp_path / "baselines",
        passphrase="correct horse battery staple",
        include_runtime=False,
    )

    archive = Path(result["archive"])
    assert archive.is_file()
    assert result["key_mode"] == "passphrase"
    assert result["database_integrity"] == "ok"
    assert result["restore_drill"] is True
    assert result["key_file"] is None
    assert b"private memory" not in archive.read_bytes()
    assert b"private-vrm-payload" not in archive.read_bytes()

    run_dir = Path(result["run_dir"])
    capture_record = json.loads((run_dir / "capture.json").read_text(encoding="utf-8"))
    verification_record = json.loads(
        (run_dir / "verification.json").read_text(encoding="utf-8")
    )
    latest_record = json.loads(
        (run_dir.parent / "latest.json").read_text(encoding="utf-8")
    )
    assert capture_record["archive_id"] == result["archive_id"]
    assert verification_record["archive_id"] == result["archive_id"]
    inventory_record = json.loads(
        Path(result["inventory"]).read_text(encoding="utf-8")
    )
    assert inventory_record["database"]["source"] == "archived_snapshot"
    assert inventory_record["database"]["path"] == "data/alpecca.db"
    assert inventory_record["database"]["integrity_check"] == "ok"
    assert inventory_record["database"]["table_counts"] == {"memories": 1}
    archived_avatar = next(
        item
        for item in inventory_record["assets"]
        if item["path"] == "data/avatar/vrm/alpecca.vrm"
    )
    assert archived_avatar["present"] is True
    assert archived_avatar["bytes"] == len(b"private-vrm-payload")
    assert archived_avatar["sha256"] == hashlib.sha256(
        b"private-vrm-payload"
    ).hexdigest()
    assert archived_avatar["vrm"] == {"error": "not_glb"}
    assert latest_record == {
        "archive": archive.name,
        "key_file": None,
        "run_dir": run_dir.name,
        "schema": "alpecca.stage0.latest.v1",
        "updated_at": latest_record["updated_at"],
    }

    restore = tmp_path / "restored"
    verified = baseline.verify_archive(
        archive,
        passphrase="correct horse battery staple",
        restore_to=restore,
    )
    assert verified["database_integrity"] == "ok"
    assert (restore / "data" / "avatar" / "vrm" / "alpecca.vrm").read_bytes() == (
        b"private-vrm-payload"
    )
    with sqlite3.connect(restore / "data" / "alpecca.db") as conn:
        assert conn.execute("SELECT content FROM memories").fetchone()[0] == (
            "private memory"
        )


def test_tampered_archive_is_rejected(tmp_path: Path):
    root = _fixture_repo(tmp_path)
    result = baseline.capture_baseline(
        root,
        tmp_path / "baselines",
        passphrase=TEST_PASSPHRASE,
        include_runtime=False,
    )
    archive = Path(result["archive"])

    with pytest.raises(baseline.BaselineError, match="requires its passphrase"):
        baseline.verify_archive(archive)
    with pytest.raises(baseline.BaselineError, match="authentication failed"):
        baseline.verify_archive(archive, passphrase=WRONG_TEST_PASSPHRASE)

    payload = bytearray(archive.read_bytes())
    payload[-baseline.TAG_SIZE - 3] ^= 0x01
    archive.write_bytes(payload)

    with pytest.raises(baseline.BaselineError, match="authentication failed"):
        baseline.verify_archive(archive, passphrase=TEST_PASSPHRASE)


def test_failed_authentication_never_writes_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    plaintext = tmp_path / "private.zip"
    plaintext.write_bytes(b"private baseline plaintext")
    archive = tmp_path / "baseline.apb"
    passphrase = _encrypt_test_payload(monkeypatch, plaintext, archive)
    _, _, ciphertext_offset = baseline._read_encrypted_header(archive)
    payload = bytearray(archive.read_bytes())
    payload[ciphertext_offset] ^= 0x01
    archive.write_bytes(payload)
    destination = tmp_path / "decrypted.zip"

    with pytest.raises(baseline.BaselineError, match="authentication failed"):
        baseline._decrypt_file(
            archive,
            destination,
            key_file=None,
            passphrase=passphrase,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(f".{destination.name}.*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is a Windows-only key wrapper")
def test_dpapi_key_wrap_round_trip():
    key = os.urandom(32)

    wrapped = baseline._dpapi_wrap(key)

    assert wrapped != key
    assert baseline._dpapi_unwrap(wrapped) == key


def test_stale_candidates_are_reported_without_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    stale_scratch = temp_root / "alpecca-stage0-capture-stale"
    stale_scratch.mkdir()
    recent_scratch = temp_root / "alpecca-stage0-capture-recent"
    recent_scratch.mkdir()
    os.utime(stale_scratch, (1, 1))
    monkeypatch.setattr(baseline.tempfile, "gettempdir", lambda: str(temp_root))

    assert baseline._stale_scratch_candidates() == [stale_scratch.name]
    assert stale_scratch.is_dir()
    assert recent_scratch.is_dir()

    restore_destination = tmp_path / "restored"
    stale_restore = tmp_path / ".restored.staging-stale"
    stale_restore.mkdir()
    os.utime(stale_restore, (1, 1))

    assert baseline._stale_restore_candidates(restore_destination) == [
        stale_restore.name
    ]
    assert stale_restore.is_dir()


def test_inventory_redacts_secret_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _fixture_repo(tmp_path)
    environment_token = "hf_" + "A" * 32
    launcher_token = "sk-" + "B" * 32
    dotted_environment_token = "A" * 24 + "." + "B" * 8 + "." + "C" * 24
    dotted_launcher_token = "D" * 24 + "." + "E" * 8 + "." + "F" * 24
    monkeypatch.setenv("ALPECCA_API_KEY", "environment-secret-value")
    monkeypatch.setenv("ALPECCA_FAST_MODEL", environment_token)
    monkeypatch.setenv("ALPECCA_REFLECT_MODEL", "https://private/model?token=secret")
    monkeypatch.setenv("ALPECCA_VISION_CLOUD_MODEL", dotted_environment_token)
    monkeypatch.setenv("ALPECCA_NUM_CTX", "32768")
    with (root / "START_HERE.bat").open("a", encoding="utf-8") as launcher:
        launcher.write(
            'set "ALPECCA_DEEP_LOCAL_MODEL=../../private-model-token"\n'
            f'set "ALPECCA_VISION_MODEL={launcher_token}"\n'
            f'set "ALPECCA_CHAT_CLOUD_MODEL={dotted_launcher_token}"\n'
        )
    inventory = baseline.collect_inventory(root, include_runtime=False)
    encoded = json.dumps(inventory)

    assert "not-a-real-secret-token-value" not in encoded
    assert "environment-secret-value" not in encoded
    assert "https://private/model?token=secret" not in encoded
    assert "../../private-model-token" not in encoded
    assert environment_token not in encoded
    assert launcher_token not in encoded
    assert dotted_environment_token not in encoded
    assert dotted_launcher_token not in encoded
    assert inventory["environment"]["ALPECCA_API_KEY"] == {
        "set": True,
        "value": "<redacted>",
    }
    assert inventory["environment"]["ALPECCA_NUM_CTX"] == {
        "set": True,
        "value": "32768",
    }
    assert inventory["environment"]["ALPECCA_REFLECT_MODEL"] == {
        "set": True,
        "value": "<redacted>",
    }
    assert inventory["environment"]["ALPECCA_FAST_MODEL"] == {
        "set": True,
        "value": "<redacted>",
    }
    assert inventory["environment"]["ALPECCA_VISION_CLOUD_MODEL"] == {
        "set": True,
        "value": "<redacted>",
    }
    assert inventory["launcher"]["assignments"]["ALPECCA_MODEL"]["value"] == (
        "qwen3.5:9b"
    )
    token = inventory["launcher"]["assignments"]["ALPECCA_ACCESS_TOKEN"]
    assert token == {"set": True, "value": "<redacted>"}
    deep_model = inventory["launcher"]["assignments"]["ALPECCA_DEEP_LOCAL_MODEL"]
    assert deep_model == {"set": True, "value": "<redacted>"}
    vision_model = inventory["launcher"]["assignments"]["ALPECCA_VISION_MODEL"]
    assert vision_model == {"set": True, "value": "<redacted>"}
    cloud_model = inventory["launcher"]["assignments"]["ALPECCA_CHAT_CLOUD_MODEL"]
    assert cloud_model == {"set": True, "value": "<redacted>"}
    assert any(
        finding["rule"] == "named_secret_assignment"
        for finding in inventory["secret_findings"]
    )
    assert inventory["database"]["integrity_check"] == "ok"
    assert inventory["database"]["table_counts"] == {"memories": 1}
    assert inventory["routes"] == [
        {"handler": "health", "method": "GET", "path": "/health"}
    ]


def test_restore_refuses_nonempty_destination(tmp_path: Path):
    root = _fixture_repo(tmp_path)
    result = baseline.capture_baseline(
        root,
        tmp_path / "baselines",
        passphrase=TEST_PASSPHRASE,
        include_runtime=False,
    )
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep.txt").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(baseline.BaselineError, match="not empty"):
        baseline.verify_archive(
            Path(result["archive"]),
            passphrase=TEST_PASSPHRASE,
            restore_to=destination,
        )


@pytest.mark.parametrize(
    "member_name",
    (
        "../outside.txt",
        "/absolute.txt",
        r"..\outside.txt",
        r"C:\outside.txt",
        "data/CON/file.txt",
        "data/NUL.txt",
        "data/COM1.log",
        "data/CONIN$/device.txt",
        "data/CONOUT$.txt",
        "data/COM\u00b9.txt",
        "data/COM\u00b2/file.txt",
        "data/LPT\u00b3.txt",
        "data/file.txt:stream",
        "data/file.",
        "data/folder /file.txt",
    ),
)
def test_restore_rejects_unsafe_member_paths(member_name: str):
    with pytest.raises(baseline.BaselineError, match="unsafe archive path"):
        baseline._safe_member_path(member_name)


def test_restore_failure_is_transactional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _fixture_repo(tmp_path)
    zip_path = tmp_path / "bad-payload.zip"
    avatar_path = "data/avatar/vrm/alpecca.vrm"
    archive_id = _write_test_zip(
        zip_path,
        {
            "data/alpecca.db": (root / "data" / "alpecca.db").read_bytes(),
            avatar_path: b"invalid avatar checksum",
        },
        sha_overrides={avatar_path: "0" * 64},
    )
    archive = tmp_path / "bad-payload.apb"
    passphrase = _encrypt_test_payload(
        monkeypatch,
        zip_path,
        archive,
        archive_id=archive_id,
    )
    destination = tmp_path / "restored"

    with pytest.raises(baseline.BaselineError, match="payload checksum mismatch"):
        baseline.verify_archive(
            archive,
            passphrase=passphrase,
            restore_to=destination,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(f".{destination.name}.staging-*"))


def test_manifest_envelope_id_mismatch_leaves_no_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _fixture_repo(tmp_path)
    zip_path = tmp_path / "mismatched-id.zip"
    _write_test_zip(
        zip_path,
        {"data/alpecca.db": (root / "data" / "alpecca.db").read_bytes()},
        archive_id="manifest-archive-id",
    )
    archive = tmp_path / "mismatched-id.apb"
    passphrase = _encrypt_test_payload(
        monkeypatch,
        zip_path,
        archive,
        archive_id="envelope-archive-id",
    )
    destination = tmp_path / "restored"

    with pytest.raises(baseline.BaselineError, match="IDs do not match"):
        baseline.verify_archive(
            archive,
            passphrase=passphrase,
            restore_to=destination,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(f".{destination.name}.staging-*"))


def test_kdf_policy_rejects_expensive_parameters_before_derivation(
    monkeypatch: pytest.MonkeyPatch,
):
    derivation_called = False

    def fail_if_called(*args, **kwargs):
        nonlocal derivation_called
        derivation_called = True
        raise AssertionError("oversized KDF reached key derivation")

    monkeypatch.setattr(baseline, "_derive_passphrase_key", fail_if_called)
    header = {
        "key_mode": "passphrase",
        "kdf": {
            "name": "scrypt",
            "n": 2**30,
            "r": 8,
            "p": 1,
            "salt": base64.b64encode(b"S" * 16).decode("ascii"),
        },
    }

    with pytest.raises(baseline.BaselineError, match="exceed the allowed policy"):
        baseline._resolve_archive_key(
            header,
            key_file=None,
            passphrase=TEST_PASSPHRASE,
        )

    assert derivation_called is False


def test_kdf_policy_rejects_non_object_metadata():
    with pytest.raises(baseline.BaselineError, match="invalid KDF parameters"):
        baseline._resolve_archive_key(
            {"key_mode": "passphrase", "kdf": []},
            key_file=None,
            passphrase=TEST_PASSPHRASE,
        )


@pytest.mark.parametrize("weak_passphrase", ("short-pass-123", "a" * 16))
def test_new_capture_rejects_weak_passphrase(
    tmp_path: Path, weak_passphrase: str
):
    root = _fixture_repo(tmp_path)
    output_root = tmp_path / "baselines"

    with pytest.raises(baseline.BaselineError, match="at least 16 characters"):
        baseline.capture_baseline(
            root,
            output_root,
            passphrase=weak_passphrase,
            include_runtime=False,
        )

    assert not output_root.exists()


def test_zip_policy_rejects_high_compression_ratio(tmp_path: Path):
    zip_path = tmp_path / "compression-bomb.zip"
    _write_test_zip(zip_path, {"data/alpecca.db": b"\0" * (1024 * 1024)})

    with pytest.raises(baseline.BaselineError, match="compression ratio"):
        baseline._verify_zip(zip_path)


def test_encrypted_envelope_size_is_rejected_before_decryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive = tmp_path / "oversized.apb"
    archive.write_bytes(b"X" * 33)
    monkeypatch.setattr(baseline, "MAX_ENCRYPTED_BYTES", 32)

    def fail_if_decrypted(*args, **kwargs):
        raise AssertionError("oversized envelope reached decryption")

    monkeypatch.setattr(baseline, "_decrypt_file", fail_if_decrypted)

    with pytest.raises(baseline.BaselineError, match="encrypted baseline exceeds"):
        baseline.verify_archive(archive, passphrase=TEST_PASSPHRASE)


def test_zip_entry_count_and_directory_entries_are_bounded(tmp_path: Path):
    too_many = tmp_path / "too-many.zip"
    with zipfile.ZipFile(too_many, "w") as archive:
        for index in range(baseline.MAX_PAYLOAD_FILES + 3):
            archive.writestr(f"entry-{index}.txt", b"x")

    with pytest.raises(baseline.BaselineError, match="entry count exceeds policy"):
        baseline._verify_zip(too_many)

    directory_entry = tmp_path / "directory-entry.zip"
    with zipfile.ZipFile(directory_entry, "w") as archive:
        archive.writestr("payload/", b"")

    with pytest.raises(baseline.BaselineError, match="entry count or type"):
        baseline._verify_zip(directory_entry)


def test_zip_eocd_and_zip64_preflight_rejects_malformed_records(tmp_path: Path):
    missing_eocd = tmp_path / "missing-eocd.zip"
    missing_eocd.write_bytes(b"not-a-zip-without-an-eocd")

    with pytest.raises(baseline.BaselineError, match="end-of-central-directory"):
        baseline._preflight_zip_entry_count(missing_eocd)

    missing_zip64_locator = tmp_path / "missing-zip64-locator.zip"
    missing_zip64_locator.write_bytes(
        struct.pack(
            "<4sHHHHIIH",
            b"PK\x05\x06",
            0,
            0,
            0xFFFF,
            0xFFFF,
            0,
            0,
            0,
        )
    )

    with pytest.raises(baseline.BaselineError, match="ZIP64 locator is missing"):
        baseline._preflight_zip_entry_count(missing_zip64_locator)


def test_zip_preflight_bounds_central_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    zip_path = tmp_path / "bounded-central-directory.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("entry.txt", b"x")
    monkeypatch.setattr(baseline, "MAX_CENTRAL_DIRECTORY_BYTES", 1)

    with pytest.raises(baseline.BaselineError, match="central directory exceeds"):
        baseline._preflight_zip_entry_count(zip_path)


def test_subprocess_environment_excludes_secrets_and_remote_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured_environments: list[dict[str, str]] = []

    def fake_run(command, **kwargs):
        captured_environments.append(dict(kwargs["env"]))
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setenv("ALPECCA_ACCESS_TOKEN", "must-not-reach-child")
    monkeypatch.setenv("HF_TOKEN", "must-not-reach-child-either")
    monkeypatch.setenv("OLLAMA_HOST", "https://remote.example.invalid")
    trusted_executable = tmp_path / "trusted" / "inventory-probe.exe"
    monkeypatch.setattr(
        baseline,
        "_resolve_trusted_executable",
        lambda name, cwd, environ: trusted_executable,
    )
    monkeypatch.setattr(baseline.subprocess, "run", fake_run)

    assert baseline._run(["inventory-probe"], tmp_path)["ok"] is True
    child_env = captured_environments[-1]
    assert "ALPECCA_ACCESS_TOKEN" not in child_env
    assert "HF_TOKEN" not in child_env
    assert "OLLAMA_HOST" not in child_env

    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    assert baseline._run(["inventory-probe"], tmp_path)["ok"] is True
    assert captured_environments[-1]["OLLAMA_HOST"] == "http://localhost:11434"


@pytest.mark.skipif(os.name != "nt", reason="Windows known-folder trust test")
def test_resolver_ignores_spoofed_roots_and_selects_real_git(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    cwd_hijack = root / "git.exe"
    cwd_hijack.write_bytes(b"not a trusted executable")
    spoofed_program_files = root / "spoofed-program-files"
    spoofed_git = spoofed_program_files / "Git" / "cmd" / "git.exe"
    spoofed_git.parent.mkdir(parents=True)
    spoofed_git.write_bytes(b"also not a trusted executable")
    environ = {
        "LOCALAPPDATA": str(root / "spoofed-local-appdata"),
        "PATH": str(root),
        "PROGRAMFILES": str(spoofed_program_files),
        "PROGRAMW6432": str(spoofed_program_files),
        "SYSTEMROOT": str(root / "spoofed-windows"),
    }

    resolved = baseline._resolve_trusted_executable("git", root, environ)
    _, registry_program_files, _ = baseline._windows_known_paths()

    assert resolved.is_file()
    assert not resolved.is_relative_to(root.resolve())
    assert resolved not in {cwd_hijack.resolve(), spoofed_git.resolve()}
    assert any(resolved.is_relative_to(path) for path in registry_program_files)

    with pytest.raises(baseline.BaselineError, match="unqualified name"):
        baseline._resolve_trusted_executable(str(cwd_hijack), root, environ)


def test_remote_ollama_host_is_not_queried(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://remote.example.invalid")

    def fail_if_queried(*args, **kwargs):
        raise AssertionError("remote Ollama host was queried")

    monkeypatch.setattr(baseline.urllib.request, "urlopen", fail_if_queried)

    assert baseline._ollama_show("qwen3.5:9b") == {
        "model": "qwen3.5:9b",
        "error": "non_local_ollama_host_not_queried",
    }


def test_failed_capture_is_not_published_and_uses_os_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _fixture_repo(tmp_path)
    output_root = tmp_path / "baselines"
    plaintext_workdirs: list[Path] = []
    original_prepare = baseline._prepare_payload

    def record_plaintext_workdir(repo_root, work, inventory):
        plaintext_workdirs.append(work.resolve())
        return original_prepare(repo_root, work, inventory)

    def fail_encryption(*args, **kwargs):
        raise baseline.BaselineError("injected encryption failure")

    monkeypatch.setattr(baseline, "_prepare_payload", record_plaintext_workdir)
    monkeypatch.setattr(baseline, "_encrypt_file", fail_encryption)
    monkeypatch.setattr(
        baseline,
        "_derive_passphrase_key",
        lambda passphrase, supplied_salt, params: b"K" * 32,
    )

    with pytest.raises(baseline.BaselineError, match="injected encryption failure"):
        baseline.capture_baseline(
            root,
            output_root,
            passphrase=TEST_PASSPHRASE,
            include_runtime=False,
        )

    assert plaintext_workdirs
    assert all(
        not workdir.is_relative_to(output_root.resolve())
        for workdir in plaintext_workdirs
    )
    assert list(output_root.iterdir()) == []


def test_vrm_inventory_counts_spring_bones(tmp_path: Path):
    document = {
        "extensions": {
            "VRMC_springBone": {
                "colliders": [{}, {}],
                "springs": [
                    {"joints": [{"node": 1}, {"node": 2}]},
                    {"joints": [{"node": 3}]},
                ],
            }
        },
        "nodes": [{}, {}, {}, {}],
    }
    encoded = baseline._canonical_json(document)
    encoded += b" " * (-len(encoded) % 4)
    total_size = 12 + 8 + len(encoded)
    vrm = tmp_path / "alpecca.vrm"
    vrm.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total_size)
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
    )

    assert baseline._glb_inventory(vrm) == {
        "collider_count": 2,
        "declared_bytes": total_size,
        "glb_version": 2,
        "node_count": 4,
        "spring_count": 2,
        "spring_joint_count": 1,
        "spring_joint_references": 3,
    }


def test_glb_json_chunk_size_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    encoded = b'{"nodes":[]}'
    encoded += b" " * (-len(encoded) % 4)
    total_size = 12 + 8 + len(encoded)
    vrm = tmp_path / "oversized-json.vrm"
    vrm.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total_size)
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
    )
    monkeypatch.setattr(baseline, "MAX_GLB_JSON_BYTES", len(encoded) - 1)

    assert baseline._glb_inventory(vrm) == {
        "declared_bytes": total_size,
        "error": "json_chunk_too_large",
        "glb_version": 2,
    }


def test_payload_inventory_uses_archived_asset_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _fixture_repo(tmp_path)
    source_avatar = root / "data" / "avatar" / "vrm" / "alpecca.vrm"
    original_payload = source_avatar.read_bytes()
    original_copy = baseline._copy_stable

    def copy_then_change_live_source(source: Path, destination: Path):
        original_copy(source, destination)
        if source.resolve() == source_avatar.resolve():
            source.write_bytes(b"live source changed after archive copy")

    monkeypatch.setattr(baseline, "_copy_stable", copy_then_change_live_source)
    inventory: dict[str, object] = {}
    baseline._prepare_payload(root, tmp_path / "work", inventory)
    archived_avatar = next(
        item
        for item in inventory["assets"]
        if item["path"] == "data/avatar/vrm/alpecca.vrm"
    )

    assert source_avatar.read_bytes() != original_payload
    assert archived_avatar["bytes"] == len(original_payload)
    assert archived_avatar["sha256"] == hashlib.sha256(original_payload).hexdigest()
    assert archived_avatar["vrm"] == {"error": "not_glb"}


def test_capture_requires_source_database(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    output_root = tmp_path / "baselines"

    with pytest.raises(baseline.BaselineError, match="required database is missing"):
        baseline.capture_baseline(
            root,
            output_root,
            passphrase=TEST_PASSPHRASE,
            include_runtime=False,
        )

    assert not (output_root / "latest.json").exists()
