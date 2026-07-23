from __future__ import annotations

import json

import pytest

from alpecca import google_workspace
from alpecca import toolkit as toolkit_mod
from alpecca import turn_context


READY_ENV = {
    "ALPECCA_GOOGLE_WORKSPACE": "1",
    "ALPECCA_GOOGLE_ROOT_ID": "rootFolder_123456",
    "ALPECCA_GOOGLE_TIMEOUT": "5",
}


def test_status_is_truthful_and_never_returns_credentials(monkeypatch):
    monkeypatch.setattr(
        google_workspace,
        "oauth_config",
        lambda _env=None: google_workspace.OAuthConfig(
            "client-id", "client-secret", "refresh-token", "test-store"
        ),
    )
    result = google_workspace.status(environ=READY_ENV)

    assert result["ready"] is True
    assert result["credential_source"] == "test-store"
    serialized = json.dumps(result)
    assert "client-secret" not in serialized
    assert "refresh-token" not in serialized
    assert result["destructive_actions"] is False
    assert result["sharing_actions"] is False


def test_disabled_or_missing_root_fails_closed():
    assert google_workspace.status(
        environ={"ALPECCA_GOOGLE_WORKSPACE": "0"}
    )["state"] == "disabled"
    client = google_workspace.GoogleWorkspaceClient(
        environ={"ALPECCA_GOOGLE_WORKSPACE": "1"},
        token_provider=lambda: "token",
        transport=lambda *_args: {},
    )
    with pytest.raises(google_workspace.GoogleWorkspaceError, match="root"):
        client.create_folder("Assistance")


def test_create_folder_is_additive_and_bound_to_private_root():
    calls = []

    def transport(method, url, body, headers, timeout):
        calls.append((method, url, json.loads(body), dict(headers), timeout))
        return {
            "id": "folderReceipt_123456",
            "name": "Assistance",
            "mimeType": google_workspace.GOOGLE_FOLDER_MIME,
            "webViewLink": "https://drive.google.com/drive/folders/folderReceipt_123456",
        }

    client = google_workspace.GoogleWorkspaceClient(
        environ=READY_ENV,
        token_provider=lambda: "short-lived-access-token",
        transport=transport,
    )
    receipt = client.create_folder("Assistance")

    assert receipt["verified_receipt"] is True
    assert receipt["file_id"] == "folderReceipt_123456"
    assert calls[0][2] == {
        "name": "Assistance",
        "mimeType": google_workspace.GOOGLE_FOLDER_MIME,
        "parents": ["rootFolder_123456"],
    }
    assert "short-lived-access-token" not in json.dumps(receipt)


def test_create_document_uses_drive_receipt_then_docs_insert():
    calls = []

    def transport(method, url, body, headers, timeout):
        payload = json.loads(body) if body else None
        calls.append((method, url, payload))
        if "/drive/v3/files" in url:
            return {"id": "documentReceipt_123456", "name": "Daily status"}
        return {"replies": [{}]}

    client = google_workspace.GoogleWorkspaceClient(
        environ=READY_ENV,
        token_provider=lambda: "token",
        transport=transport,
    )
    receipt = client.create_document("Daily status", "Systems checked and ready.")

    assert receipt["verified_receipt"] is True
    assert receipt["content_inserted"] is True
    assert calls[0][2]["mimeType"] == google_workspace.GOOGLE_DOC_MIME
    assert calls[0][2]["parents"] == ["rootFolder_123456"]
    assert calls[1][1].endswith("/documents/documentReceipt_123456:batchUpdate")
    assert calls[1][2]["requests"][0]["insertText"]["location"] == {"index": 1}
    assert calls[1][2]["requests"][0]["insertText"]["text"] == "Systems checked and ready."


def test_invalid_receipt_never_claims_success():
    client = google_workspace.GoogleWorkspaceClient(
        environ=READY_ENV,
        token_provider=lambda: "token",
        transport=lambda *_args: {"id": "bad id with spaces"},
    )
    with pytest.raises(google_workspace.GoogleWorkspaceError, match="valid file receipt"):
        client.create_folder("Assistance")


def test_creator_tool_registry_dispatches_google_document_with_audited_receipt(monkeypatch):
    mind = type("Mind", (), {"_location": "workshop"})()
    toolkit = toolkit_mod.InnateToolkit(mind)
    turn = turn_context.TurnContext.create("creator-google", principal="creator")
    observations = []
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "INNATE_TOOLS", True)
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "GOOGLE_WORKSPACE", True)
    monkeypatch.setattr(toolkit_mod.cognition_mod, "record_observation", observations.append)
    monkeypatch.setattr(
        toolkit_mod.google_workspace_mod,
        "create_document",
        lambda title, content: {
            "ok": True,
            "kind": "document",
            "name": title,
            "file_id": "documentReceipt_123456",
            "web_view_link": "https://docs.google.com/document/d/documentReceipt_123456/edit",
            "verified_receipt": True,
            "content_inserted": bool(content),
        },
    )

    names = {schema["function"]["name"] for schema in toolkit.schemas(turn=turn)}
    assert {"google_status", "google_create_folder", "google_create_document"} <= names
    result = json.loads(toolkit.execute(
        "google_create_document",
        {"title": "Assistance notes", "content": "One verified note."},
        turn=turn,
    ))

    assert result["verified_receipt"] is True
    assert observations[-1].metadata["tool"] == "google_create_document"
    assert "Assistance notes" not in json.dumps(observations[-1].metadata)
