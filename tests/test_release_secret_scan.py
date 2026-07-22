from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts import release_secret_scan as scan


NOW = datetime(2026, 7, 15, 18, 30, tzinfo=timezone.utc)


def _fixture(
    tmp_path: Path,
    *,
    source: bytes = b"print('clean')\n",
    dist_index: bytes | None = b"<!doctype html><title>Alpecca</title>\n",
) -> tuple[Path, list[str]]:
    root = tmp_path / "repo"
    root.mkdir()
    source_path = root / "source.py"
    source_path.write_bytes(source)
    dist = root / "apps" / "house-hq" / "dist"
    dist.mkdir(parents=True)
    if dist_index is not None:
        (dist / "index.html").write_bytes(dist_index)
    return root, ["source.py"]


def _git_fixture(tmp_path: Path) -> Path:
    root, _ = _fixture(tmp_path)
    commands = (
        ["git", "init", "-q"],
        ["git", "config", "user.name", "Alpecca Release Test"],
        ["git", "config", "user.email", "release-test@invalid.example"],
        ["git", "add", "source.py"],
        ["git", "commit", "-qm", "fixture"],
    )
    for command in commands:
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    return root


def _codes(receipt: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in receipt["errors"]}  # type: ignore[index]


def test_clean_fixture_passes_but_cannot_claim_release_readiness(tmp_path: Path) -> None:
    root, tracked = _fixture(tmp_path)

    receipt = scan.scan_release(root, tracked_paths=tracked, now=NOW)

    assert receipt["result"] == "pass"
    assert receipt["mode"] == "fixture"
    assert receipt["finding_count"] == 0
    assert receipt["error_count"] == 0
    assert receipt["release_ready"] is False
    assert receipt["claim"] == "not_release_ready"
    assert receipt["generated_at"] == "2026-07-15T18:30:00Z"


def test_git_defined_clean_scope_can_claim_release_readiness(tmp_path: Path) -> None:
    root = _git_fixture(tmp_path)

    receipt = scan.scan_release(root, now=NOW)

    assert receipt["mode"] == "git"
    assert receipt["result"] == "pass"
    assert receipt["release_ready"] is True
    assert receipt["claim"] == "release_secret_scan_passed"
    assert len(str(receipt["repository_head"])) == 40
    assert receipt["scopes"]["tracked_source"]["file_count"] == 1  # type: ignore[index]
    assert receipt["scopes"]["house_hq_dist"]["file_count"] == 1  # type: ignore[index]


def test_source_finding_fails_without_serializing_secret_or_path(tmp_path: Path) -> None:
    secret = "hf" + "_" + ("A" * 28)
    root, tracked = _fixture(tmp_path, source=f"value = '{secret}'\n".encode())

    receipt = scan.scan_release(root, tracked_paths=tracked, now=NOW)
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt["result"] == "fail"
    assert receipt["release_ready"] is False
    assert receipt["finding_count"] == 1
    assert receipt["findings"][0]["rule"] == "hugging_face_token"  # type: ignore[index]
    assert secret not in serialized
    assert "source.py" not in serialized
    assert len(receipt["findings"][0]["path_sha256"]) == 64  # type: ignore[index]


def test_dist_finding_is_included_in_release_gate(tmp_path: Path) -> None:
    secret = "sk" + "-proj-" + ("Z9" * 18)
    root, tracked = _fixture(tmp_path, dist_index=f"window.key='{secret}'".encode())

    receipt = scan.scan_release(root, tracked_paths=tracked, now=NOW)

    assert receipt["result"] == "fail"
    assert receipt["finding_count"] == 1
    finding = receipt["findings"][0]  # type: ignore[index]
    assert finding["scope"] == "house_hq_dist"
    assert finding["rule"] == "openai_key"
    assert secret not in json.dumps(receipt)


def test_absent_dist_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "source.py").write_text("clean = True\n", encoding="utf-8")

    receipt = scan.scan_release(root, tracked_paths=["source.py"], now=NOW)

    assert receipt["result"] == "fail"
    assert receipt["release_ready"] is False
    assert "dist_absent" in _codes(receipt)


def test_dist_without_index_fails_closed(tmp_path: Path) -> None:
    root, tracked = _fixture(tmp_path, dist_index=None)
    (root / "apps" / "house-hq" / "dist" / "asset.js").write_text(
        "console.log('clean')", encoding="utf-8"
    )

    receipt = scan.scan_release(root, tracked_paths=tracked, now=NOW)

    assert receipt["result"] == "fail"
    assert "dist_index_missing" in _codes(receipt)


def test_secret_crossing_read_chunk_boundary_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scan, "CHUNK_BYTES", 32)
    monkeypatch.setattr(scan, "OVERLAP_BYTES", 64)
    secret = "github" + "_pat_" + ("Ab9_" * 12)
    source = (b"x" * 26) + b" " + secret.encode("ascii") + b"\n"
    root, tracked = _fixture(tmp_path, source=source)

    receipt = scan.scan_release(root, tracked_paths=tracked, now=NOW)

    assert receipt["finding_count"] == 1
    assert receipt["findings"][0]["rule"] == "github_token"  # type: ignore[index]
    assert receipt["findings"][0]["byte_offset"] == 27  # type: ignore[index]


def test_named_assignment_detects_credible_value_but_ignores_placeholder(
    tmp_path: Path,
) -> None:
    secret = "Creator" + "-9v#" + "Q2m!" + "7Rx$"
    source = (
        "ALPECCA_CREATOR_PASSWORD=replace-with-your-password\n"
        f"SERVICE_PASSWORD={secret}\n"
    ).encode("utf-8")
    root, tracked = _fixture(tmp_path, source=source)

    receipt = scan.scan_release(root, tracked_paths=tracked, now=NOW)

    assert receipt["finding_count"] == 1
    assert receipt["findings"][0]["rule"] == "named_secret_assignment"  # type: ignore[index]
    assert secret not in json.dumps(receipt)


def test_named_assignment_ignores_noncredential_state_and_phase_fixtures(
    tmp_path: Path,
) -> None:
    source = (
        "BRIDGE_CREDENTIAL_TARGET='Alpecca.Authorization.Secret'\n"
        "generation_token='profile-generation-1'\n"
        "SEAL_SECRET='phase10-transport-dedicated-actor-seal-secret'\n"
        "client.withCredentials='include-credentials'\n"
    ).encode("utf-8")
    root, tracked = _fixture(tmp_path, source=source)

    receipt = scan.scan_release(root, tracked_paths=tracked, now=NOW)

    assert receipt["result"] == "pass"
    assert receipt["finding_count"] == 0


def test_fixture_paths_cannot_escape_repository(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    outside = tmp_path / "outside-private-name.txt"
    outside.write_text("clean", encoding="utf-8")

    receipt = scan.scan_release(root, tracked_paths=[outside], now=NOW)
    serialized = json.dumps(receipt)

    assert receipt["result"] == "fail"
    assert "tracked_path_outside_root" in _codes(receipt)
    assert outside.name not in serialized


def test_receipt_is_deterministic_for_fixed_time_and_unchanged_inputs(tmp_path: Path) -> None:
    root, tracked = _fixture(tmp_path)

    first = scan.scan_release(root, tracked_paths=tracked, now=NOW)
    second = scan.scan_release(root, tracked_paths=tracked, now=NOW)

    assert first == second
    digest = first["receipt_sha256"]
    without_digest = dict(first)
    without_digest.pop("receipt_sha256")
    assert digest == scan.hashlib.sha256(scan._canonical_json(without_digest)).hexdigest()


def test_dry_run_prints_receipt_without_writing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _git_fixture(tmp_path)
    output = tmp_path / "receipt.json"

    result = scan.main(
        ["--root", str(root), "--receipt", str(output), "--dry-run"]
    )
    printed = json.loads(capsys.readouterr().out)

    assert result == 0
    assert printed["release_ready"] is True
    assert not output.exists()


def test_cli_writes_exact_content_free_receipt_atomically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _git_fixture(tmp_path)
    output = tmp_path / "receipts" / "secret-scan.json"

    result = scan.main(["--root", str(root), "--receipt", str(output)])
    printed = json.loads(capsys.readouterr().out)
    stored = json.loads(output.read_text(encoding="utf-8"))

    assert result == 0
    assert stored == printed
    assert stored["release_ready"] is True
    assert not list(output.parent.glob("*.tmp"))


def test_symlinked_dist_file_is_rejected_instead_of_followed(tmp_path: Path) -> None:
    root, tracked = _fixture(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("clean", encoding="utf-8")
    link = root / "apps" / "house-hq" / "dist" / "linked.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this host")

    receipt = scan.scan_release(root, tracked_paths=tracked, now=NOW)

    assert receipt["result"] == "fail"
    assert "not_regular_file" in _codes(receipt)
