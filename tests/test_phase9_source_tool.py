"""Focused creator-scoped coverage for the Phase 9 source inspection tool."""
from __future__ import annotations

import json
from pathlib import Path

from alpecca import toolkit as toolkit_mod
from alpecca import turn_context
from alpecca.mind import CoreMind
from alpecca.source_perception import SourceInspection, SourceProvenance


class _Mind:
    pass


class _CloudMind:
    class _CloudLlm:
        @staticmethod
        def is_cloud() -> bool:
            return True

    llm = _CloudLlm()


class _RemoteMind:
    class _RemoteLlm:
        @staticmethod
        def is_cloud() -> bool:
            return False

        @staticmethod
        def local_inference_available() -> bool:
            return False

    llm = _RemoteLlm()


def _toolkit(monkeypatch):
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "INNATE_TOOLS", True)
    return toolkit_mod.InnateToolkit(_Mind())


def _turn(principal: str):
    return turn_context.TurnContext.create(
        "source-inspection", principal=principal, surface="app", privacy_scope="private"
    )


def test_creator_can_inspect_only_explicit_repository_roots(monkeypatch):
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
    assert set(kwargs["allowed_roots"]) == {
        "source", "house", "tests", "scripts", "docs", "project",
    }
    assert kwargs["allowed_roots"]["source"] == Path(toolkit_mod.__file__).resolve().parent
    assert kwargs["allowed_roots"]["house"] == (
        Path(toolkit_mod.__file__).resolve().parents[1] / "apps" / "house-hq" / "src"
    )
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

    assert result == toolkit_mod.CAPABILITY_DENIED
    assert calls == []


def test_cloud_model_backend_is_denied_before_any_source_read(monkeypatch):
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "INNATE_TOOLS", True)
    toolkit = toolkit_mod.InnateToolkit(_CloudMind())
    calls = []
    monkeypatch.setattr(
        toolkit_mod.source_perception_mod,
        "inspect_local_source",
        lambda *_args, **_kwargs: calls.append("read"),
    )

    result = toolkit.execute(
        "source_inspect", {"root": "project", "path": "server.py"},
        turn=_turn("creator"),
    )

    assert result == "error: source_inspect requires Alpecca's verified local model"
    assert calls == []


def test_remote_ollama_target_is_denied_before_any_source_read(monkeypatch):
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "INNATE_TOOLS", True)
    toolkit = toolkit_mod.InnateToolkit(_RemoteMind())
    calls = []
    monkeypatch.setattr(
        toolkit_mod.source_perception_mod,
        "inspect_local_source",
        lambda *_args, **_kwargs: calls.append("read"),
    )

    result = toolkit.execute(
        "source_inspect", {"root": "project", "path": "server.py"},
        turn=_turn("creator"),
    )

    assert result == "error: source_inspect requires Alpecca's verified local model"
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
    assert data == "error: source_inspect root is not an approved repository area"
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


def test_project_root_allows_only_canonical_top_level_source_files(monkeypatch):
    toolkit = _toolkit(monkeypatch)
    calls = []
    inspection = SourceInspection(
        ok=True,
        status="ok",
        reason="text-excerpt",
        mime_type="text/x-python",
        provenance=SourceProvenance("project", "server.py", 12, "sha"),
        encoding="utf-8",
        excerpt="server source",
    )
    monkeypatch.setattr(
        toolkit_mod.source_perception_mod,
        "inspect_local_source",
        lambda *args, **kwargs: calls.append((args, kwargs)) or inspection,
    )
    creator = _turn("creator")

    allowed = json.loads(toolkit.execute(
        "source_inspect", {"root": "project", "path": "server.py"}, turn=creator
    ))
    log_file = toolkit.execute(
        "source_inspect",
        {"root": "project", "path": ".codex-server.out.log"},
        turn=creator,
    )
    nested = toolkit.execute(
        "source_inspect", {"root": "project", "path": "alpecca/mind.py"}, turn=creator
    )
    env_file = toolkit.execute(
        "source_inspect", {"root": "docs", "path": ".env.production"}, turn=creator
    )

    assert allowed["ok"] is True
    assert len(calls) == 1
    assert log_file == (
        "error: source_inspect project root allows only canonical top-level source files"
    )
    assert nested == (
        "error: source_inspect project root allows only canonical top-level source files"
    )
    assert env_file == "error: source_inspect does not allow credential files"


def test_smart_mode_offers_source_inspection_only_to_creator_turns(monkeypatch):
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "INNATE_TOOLS", True)
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "TOOL_MODE", "smart")
    mind = CoreMind()

    creator_schema = mind._tool_schema(
        "Please inspect your source code in server.py.",
        turn=_turn("creator"),
    )
    guest_schema = mind._tool_schema(
        "Please inspect your source code in server.py.",
        turn=_turn("guest"),
    )

    creator_names = [item["function"]["name"] for item in creator_schema or []]
    guest_names = [item["function"]["name"] for item in guest_schema or []]
    assert creator_names[0] == "source_inspect"
    assert "source_inspect" not in guest_names
