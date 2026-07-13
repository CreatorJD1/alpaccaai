"""Read-only Alpecca source workspace boundaries and HTTP surface."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from alpecca import source_workspace


def _roots(tmp_path: Path) -> dict[str, Path]:
    source = tmp_path / "alpecca"
    source.mkdir()
    (source / "mind.py").write_text("print('mind')", encoding="utf-8")
    (source / ".env.local").write_text("secret", encoding="utf-8")
    blocked = source / "data"
    blocked.mkdir()
    (blocked / "secret.txt").write_text("secret", encoding="utf-8")
    house = tmp_path / "house"
    house.mkdir()
    (house / "main.ts").write_text("export {};", encoding="utf-8")
    return {
        "source": source,
        "house": house,
        "tests": tmp_path / "missing-tests",
        "scripts": tmp_path / "missing-scripts",
        "docs": tmp_path / "missing-docs",
        "project": tmp_path,
    }


def test_source_listing_is_metadata_only_and_hides_blocked_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(source_workspace, "SOURCE_ROOTS", _roots(tmp_path))

    result = source_workspace.list_entries("source")

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["entries"] == [{
        "name": "mind.py",
        "rel": "mind.py",
        "is_dir": False,
        "size": len("print('mind')"),
        "attachable": True,
    }]
    serialized = json.dumps(result)
    assert "print('mind')" not in serialized
    assert ".env" not in serialized
    assert "secret" not in serialized
    assert str(tmp_path) not in serialized


def test_source_reference_rejects_credentials_traversal_and_empty_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(source_workspace, "SOURCE_ROOTS", _roots(tmp_path))

    for rel, reason in (
        (".env.local", "credential-path"),
        ("data/secret.txt", "blocked-path"),
        ("../outside.txt", "traversal"),
        ("", "path-required"),
    ):
        try:
            source_workspace.reference_allowed("source", rel)
        except source_workspace.SourceWorkspaceRejected as exc:
            assert exc.reason == reason
        else:
            raise AssertionError(f"{rel!r} was unexpectedly allowed")


def test_source_reference_rejects_windows_path_aliases(monkeypatch, tmp_path):
    monkeypatch.setattr(source_workspace, "SOURCE_ROOTS", _roots(tmp_path))

    for rel in ("mind.py.", "mind.py ", "mind.py::$DATA", "credentials.json."):
        with pytest.raises(source_workspace.SourceWorkspaceRejected) as rejected:
            source_workspace.reference_allowed("source", rel)
        assert rejected.value.reason == "path-alias-not-allowed"


def test_source_listing_and_search_report_fixed_work_caps(monkeypatch, tmp_path):
    roots = _roots(tmp_path)
    for index in range(8):
        (roots["source"] / f"module_{index}.py").write_text("pass", encoding="utf-8")
    monkeypatch.setattr(source_workspace, "SOURCE_ROOTS", roots)
    monkeypatch.setattr(source_workspace, "SEARCH_VISIT_LIMIT", 3)

    listing = source_workspace.list_entries("source", limit=2)
    search = source_workspace.search("not-present", limit=10)

    assert len(listing["entries"]) == 2
    assert listing["truncated"] is True
    assert search["matches"] == []
    assert search["truncated"] is True
    assert search["visited"] == 3


def test_source_search_returns_bounded_relative_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(source_workspace, "SOURCE_ROOTS", _roots(tmp_path))

    result = source_workspace.search("main", limit=5)

    assert result["ok"] is True
    assert result["matches"] == [{
        "root": "house",
        "name": "main.ts",
        "rel": "main.ts",
        "is_dir": False,
        "size": len("export {};"),
        "attachable": True,
    }]


def test_source_workspace_routes_are_creator_only_and_no_store(monkeypatch, tmp_path):
    monkeypatch.setattr(source_workspace, "SOURCE_ROOTS", _roots(tmp_path))
    client = TestClient(server.app)
    try:
        anonymous = client.get("/source-workspace")
        assert anonymous.status_code == 401

        headers = {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}
        overview = client.get("/source-workspace", headers=headers)
        listing = client.get(
            "/source-workspace/list",
            headers=headers,
            params={"root": "source"},
        )
        search = client.get(
            "/source-workspace/search",
            headers=headers,
            params={"q": "mind"},
        )
    finally:
        client.close()

    assert overview.status_code == listing.status_code == search.status_code == 200
    assert overview.headers["cache-control"] == "no-store"
    assert listing.headers["cache-control"] == "no-store"
    assert search.headers["cache-control"] == "no-store"
    assert listing.json()["entries"][0]["rel"] == "mind.py"
    assert search.json()["matches"][0]["root"] == "source"
