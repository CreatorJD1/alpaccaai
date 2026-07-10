"""Focused creator-scoped coverage for the Phase 9 source inspection tool."""
from __future__ import annotations

import json
from pathlib import Path

from alpecca import toolkit as toolkit_mod
from alpecca import turn_context
from alpecca.source_perception import SourceInspection, SourceProvenance


class _Mind:
    pass


def _toolkit(monkeypatch):
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "INNATE_TOOLS", True)
    return toolkit_mod.InnateToolkit(_Mind())


def _turn(principal: str):
    return turn_context.TurnContext.create(
        "source-inspection", principal=principal, surface="app", privacy_scope="private"
    )


def test_creator_can_inspect_only_fixed_source_or_docs_roots(monkeypatch):
    toolkit = _toolkit(monkeypatch)
    calls = []
    inspection = SourceInspection(
        ok=True,
        status="ok",
        reason="text-excerpt",
        mime_type="text/x-python",
        provenance=SourceProvenance("source", "cues.py", 12, "sha"),
        encoding="utf-8",
        excerpt="source text",
    )

    def inspect(root, path, **kwargs):
        calls.append((root, path, kwargs))
        return inspection

    monkeypatch.setattr(toolkit_mod.source_perception_mod, "inspect_local_source", inspect)

    result = json.loads(toolkit.execute(
        "source_inspect", {"root": "source", "path": "cues.py"}, turn=_turn("creator")
    ))

    assert result["ok"] is True
    assert result["provenance"]["relative_path"] == "cues.py"
    assert len(calls) == 1
    root, path, kwargs = calls[0]
    assert (root, path) == ("source", "cues.py")
    assert set(kwargs["allowed_roots"]) == {"source", "docs"}
    assert kwargs["allowed_roots"]["source"] == Path(toolkit_mod.__file__).resolve().parent
    assert kwargs["allowed_roots"]["docs"] == Path(toolkit_mod.__file__).resolve().parents[1] / "docs"
    assert "source_inspect" in [item["function"]["name"] for item in toolkit.schemas()]


def test_guest_is_denied_before_any_source_read(monkeypatch):
    toolkit = _toolkit(monkeypatch)
    calls = []
    monkeypatch.setattr(
        toolkit_mod.source_perception_mod,
        "inspect_local_source",
        lambda *_args, **_kwargs: calls.append("read"),
    )

    result = toolkit.execute(
        "source_inspect", {"path": "cues.py"}, turn=_turn("guest")
    )

    assert result == "error: source_inspect is available only to the creator"
    assert calls == []


def test_traversal_data_and_unapproved_roots_are_denied_without_inspection(monkeypatch):
    toolkit = _toolkit(monkeypatch)
    calls = []
    monkeypatch.setattr(
        toolkit_mod.source_perception_mod,
        "inspect_local_source",
        lambda *_args, **_kwargs: calls.append("read"),
    )
    creator = _turn("creator")

    traversal = toolkit.execute(
        "source_inspect", {"root": "source", "path": "../data/alpecca.db"}, turn=creator
    )
    data = toolkit.execute(
        "source_inspect", {"root": "data", "path": "alpecca.db"}, turn=creator
    )
    credential = toolkit.execute(
        "source_inspect", {"root": "docs", "path": "credentials.json"}, turn=creator
    )

    assert traversal == "error: source_inspect does not allow data or credential paths"
    assert data == "error: source_inspect root must be source or docs"
    assert credential == "error: source_inspect does not allow credential files"
    assert calls == []


def test_cancelled_creator_turn_never_calls_source_inspection(monkeypatch):
    toolkit = _toolkit(monkeypatch)
    calls = []
    monkeypatch.setattr(
        toolkit_mod.source_perception_mod,
        "inspect_local_source",
        lambda *_args, **_kwargs: calls.append("read"),
    )
    turn = _turn("creator")
    turn.cancel("timeout")

    result = toolkit.execute("source_inspect", {"path": "cues.py"}, turn=turn)

    assert result == "error: turn was cancelled before the innate tool could run"
    assert calls == []
