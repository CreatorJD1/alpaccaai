from __future__ import annotations

import pytest

from alpecca.restore_approval import RestoreApprovalError, RestoreApprovalLedger


FINGERPRINT = "a" * 64


def test_preview_approval_is_explicit_bound_and_single_use(tmp_path):
    clock = [1000.0]
    ledger = RestoreApprovalLedger(tmp_path / "restore.db", now=lambda: clock[0])
    preview = ledger.issue_preview(FINGERPRINT, "vault_cloud")

    with pytest.raises(RestoreApprovalError, match="explicit_approval_required"):
        ledger.approve(preview["preview_id"], FINGERPRINT, approved=False)
    approval = ledger.approve(preview["preview_id"], FINGERPRINT, approved=True)
    token = approval["approval_token"]

    with pytest.raises(RestoreApprovalError, match="approval_binding_mismatch"):
        ledger.consume(token, "b" * 64, "vault_cloud")
    with pytest.raises(RestoreApprovalError, match="approval_binding_mismatch"):
        ledger.consume(token, FINGERPRINT, "posted")
    assert ledger.consume(token, FINGERPRINT, "vault_cloud") == preview["preview_id"]
    with pytest.raises(RestoreApprovalError, match="approval_replayed"):
        ledger.consume(token, FINGERPRINT, "vault_cloud")
    with pytest.raises(RestoreApprovalError, match="approval_invalid"):
        ledger.consume("x" * 31 + "\u2603", FINGERPRINT, "vault_cloud")


def test_preview_and_approval_expire_fail_closed(tmp_path):
    clock = [2000.0]
    ledger = RestoreApprovalLedger(tmp_path / "restore.db", now=lambda: clock[0])
    preview = ledger.issue_preview(FINGERPRINT, "posted")
    clock[0] += 601
    with pytest.raises(RestoreApprovalError, match="preview_expired"):
        ledger.approve(preview["preview_id"], FINGERPRINT, approved=True)

    preview = ledger.issue_preview(FINGERPRINT, "posted")
    approval = ledger.approve(preview["preview_id"], FINGERPRINT, approved=True)
    clock[0] += 301
    with pytest.raises(RestoreApprovalError, match="approval_expired"):
        ledger.consume(approval["approval_token"], FINGERPRINT, "posted")


def test_ledger_persists_only_token_digest(tmp_path):
    import sqlite3

    db = tmp_path / "restore.db"
    ledger = RestoreApprovalLedger(db, now=lambda: 3000.0)
    preview = ledger.issue_preview(FINGERPRINT, "posted")
    approval = ledger.approve(preview["preview_id"], FINGERPRINT, approved=True)
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT approval_digest FROM mindscape_restore_approvals WHERE preview_id = ?",
            (preview["preview_id"],),
        ).fetchone()
    assert row and len(row[0]) == 64
    assert approval["approval_token"] not in row[0]
