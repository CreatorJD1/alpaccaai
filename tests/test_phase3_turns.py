"""Focused Phase 3 turn-transaction and context-isolation coverage."""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from alpecca import memory as memory_store
from alpecca import mindpage
from alpecca import state as state_store
from alpecca import turn_context


def test_turn_context_canonicalizes_identity_and_scope():
    creator = turn_context.TurnContext.create(
        "house conversation",
        principal="creator",
        surface="house hq",
        privacy_scope="creator private",
        portal_epoch="portal 7",
    )
    untrusted_identity = turn_context.TurnContext.create(
        "house conversation",
        principal="CreatorJD",
        surface="house hq",
        portal_epoch="portal 7",
    )
    same_scope_new_turn = turn_context.TurnContext.create(
        "house conversation",
        principal="creator",
        surface="house hq",
        privacy_scope="creator private",
        portal_epoch="portal 7",
    )

    assert creator.principal == "creator"
    assert untrusted_identity.principal == "guest"
    assert untrusted_identity.memory_scope == "guest-house-conversation"
    assert creator.conversation_id == "house-conversation"
    assert creator.surface == "house-hq"
    assert creator.memory_scope == "creator-private"
    assert creator.portal_epoch == "portal-7"
    assert creator.turn_id != same_scope_new_turn.turn_id
    assert creator.scope_key == same_scope_new_turn.scope_key
    assert creator.scope_key != untrusted_identity.scope_key
    with pytest.raises(dataclasses.FrozenInstanceError):
        creator.principal = "guest"


def test_durable_history_isolated_by_full_turn_scope(tmp_path):
    db_path = tmp_path / "turn-history.db"
    creator = turn_context.TurnContext.create(
        "conversation-1",
        principal="creator",
        surface="app",
        privacy_scope="creator-private",
        portal_epoch="portal-a",
    )
    guest = turn_context.TurnContext.create(
        "conversation-1",
        principal="guest",
        surface="app",
        privacy_scope="guest-private",
        portal_epoch="portal-a",
    )
    other_conversation = turn_context.TurnContext.create(
        "conversation-2",
        principal="creator",
        surface="app",
        privacy_scope="creator-private",
        portal_epoch="portal-a",
    )
    other_surface = turn_context.TurnContext.create(
        "conversation-1",
        principal="creator",
        surface="house-hq",
        privacy_scope="creator-private",
        portal_epoch="portal-a",
    )
    other_epoch = turn_context.TurnContext.create(
        "conversation-1",
        principal="creator",
        surface="app",
        privacy_scope="creator-private",
        portal_epoch="portal-b",
    )

    turn_context.save_history(
        creator,
        [{"role": "user", "content": "creator-only history marker"}],
        db_path=db_path,
    )
    turn_context.save_history(
        guest,
        [{"role": "user", "content": "guest-only history marker"}],
        db_path=db_path,
    )
    turn_context.save_history(
        other_conversation,
        [{"role": "user", "content": "other-conversation marker"}],
        db_path=db_path,
    )
    turn_context.save_history(
        other_surface,
        [{"role": "user", "content": "other-surface marker"}],
        db_path=db_path,
    )
    turn_context.save_history(
        other_epoch,
        [{"role": "user", "content": "other-epoch marker"}],
        db_path=db_path,
    )

    restarted_creator = turn_context.TurnContext.create(
        "conversation-1",
        principal="creator",
        surface="app",
        privacy_scope="creator-private",
        portal_epoch="portal-a",
    )
    assert turn_context.load_history(restarted_creator, db_path=db_path) == [
        {"role": "user", "content": "creator-only history marker"}
    ]
    assert turn_context.load_history(guest, db_path=db_path) == [
        {"role": "user", "content": "guest-only history marker"}
    ]
    assert turn_context.load_history(other_conversation, db_path=db_path) == [
        {"role": "user", "content": "other-conversation marker"}
    ]
    assert turn_context.load_history(other_surface, db_path=db_path) == [
        {"role": "user", "content": "other-surface marker"}
    ]
    assert turn_context.load_history(other_epoch, db_path=db_path) == [
        {"role": "user", "content": "other-epoch marker"}
    ]

    turn_context.clear_history(guest, db_path=db_path)
    assert turn_context.load_history(guest, db_path=db_path) == []
    assert turn_context.load_history(restarted_creator, db_path=db_path) == [
        {"role": "user", "content": "creator-only history marker"}
    ]


def test_scoped_memory_and_mindpage_retrieval_do_not_cross_private_scopes(tmp_path):
    db_path = tmp_path / "scoped-retrieval.db"
    state_store.init_db(db_path)
    creator = turn_context.TurnContext.create(
        "conversation-1",
        principal="creator",
        surface="house-hq",
        privacy_scope="creator-private",
    )
    guest = turn_context.TurnContext.create(
        "conversation-1",
        principal="guest",
        surface="house-hq",
        privacy_scope="guest-private",
    )

    assert memory_store.remember(
        "creator sapphire roadmap marker",
        salience=0.9,
        embed_fn=None,
        scope=creator.memory_scope,
        db_path=db_path,
    )
    assert memory_store.remember(
        "guest sapphire roadmap marker",
        salience=0.9,
        embed_fn=None,
        scope=guest.memory_scope,
        db_path=db_path,
    )
    assert memory_store.remember(
        "shared sapphire roadmap marker",
        salience=0.9,
        embed_fn=None,
        scope="shared",
        db_path=db_path,
    )
    creator_memories = memory_store.recall(
        "creator sapphire roadmap marker",
        top_k=10,
        embed_fn=None,
        scope=creator.memory_scope,
        db_path=db_path,
    )
    guest_memories = memory_store.recall(
        "guest sapphire roadmap marker",
        top_k=10,
        embed_fn=None,
        scope=guest.memory_scope,
        db_path=db_path,
    )
    creator_contents = {item["content"] for item in creator_memories}
    guest_contents = {item["content"] for item in guest_memories}
    assert "creator sapphire roadmap marker" in creator_contents
    assert "guest sapphire roadmap marker" not in creator_contents
    assert "guest sapphire roadmap marker" in guest_contents
    assert "creator sapphire roadmap marker" not in guest_contents
    assert {item["scope"] for item in creator_memories} <= {
        creator.memory_scope,
        "shared",
    }
    assert {item["scope"] for item in guest_memories} <= {
        guest.memory_scope,
        "shared",
    }
    shared_for_creator = memory_store.recall(
        "shared sapphire roadmap marker",
        top_k=10,
        embed_fn=None,
        scope=creator.memory_scope,
        db_path=db_path,
    )
    assert "shared sapphire roadmap marker" in {
        item["content"] for item in shared_for_creator
    }
    guest_private_only = memory_store.recall(
        "guest sapphire roadmap marker",
        top_k=10,
        embed_fn=None,
        scope=guest.memory_scope,
        include_shared=False,
        db_path=db_path,
    )
    assert "guest sapphire roadmap marker" in {
        item["content"] for item in guest_private_only
    }
    assert {item["scope"] for item in guest_private_only} == {
        guest.memory_scope
    }

    creator_page = mindpage.write_page(
        kind="episode",
        topic="creator sapphire roadmap marker",
        summary="creator sapphire roadmap marker",
        content="creator-private page body",
        scope=creator.memory_scope,
        db_path=db_path,
    )
    guest_page = mindpage.write_page(
        kind="episode",
        topic="guest sapphire roadmap marker",
        summary="guest sapphire roadmap marker",
        content="guest-private page body",
        scope=guest.memory_scope,
        db_path=db_path,
    )
    shared_page = mindpage.write_page(
        kind="episode",
        topic="shared sapphire roadmap marker",
        summary="shared sapphire roadmap marker",
        content="shared page body",
        scope="shared",
        db_path=db_path,
    )
    creator_pages = mindpage.recall_page(
        "sapphire roadmap marker",
        limit=10,
        scope=creator.memory_scope,
        db_path=db_path,
    )
    guest_pages = mindpage.recall_page(
        "sapphire roadmap marker",
        limit=10,
        scope=guest.memory_scope,
        db_path=db_path,
    )
    assert {page["id"] for page in creator_pages} == {creator_page, shared_page}
    assert {page["id"] for page in guest_pages} == {guest_page, shared_page}
    guest_private_pages = mindpage.recall_page(
        "sapphire roadmap marker",
        limit=10,
        scope=guest.memory_scope,
        include_shared=False,
        db_path=db_path,
    )
    assert {page["id"] for page in guest_private_pages} == {guest_page}
    assert mindpage.fault_page(
        guest_page,
        scope=creator.memory_scope,
        include_shared=True,
        db_path=db_path,
    ) is None


def test_commit_barrier_rejects_cancelled_turn_and_preserves_committed_turn():
    cancelled = turn_context.TurnContext.create("cancelled", timeout_s=5)
    assert cancelled.cancel("disconnect") is True
    assert cancelled.allow_work() is False
    assert cancelled.begin_commit() is False
    assert cancelled.audit_metadata()["commit_state"] == "cancelled"

    committed = turn_context.TurnContext.create("committed", timeout_s=5)
    assert committed.begin_commit() is True
    assert committed.cancel("late timeout") is False
    committed.finish_commit()
    assert committed.audit_metadata()["commit_state"] == "committed"
    assert committed.audit_metadata()["cancelled"] is False


def test_ws_timeout_cancels_turn_before_late_worker_can_commit(monkeypatch):
    import server

    observed = {}

    async def exercise() -> dict:
        started = asyncio.Event()
        release = asyncio.Event()
        finished = asyncio.Event()

        async def late_worker(turn, *_args, **_kwargs):
            started.set()
            await release.wait()
            observed["allow_work"] = turn.allow_work()
            observed["begin_commit"] = turn.begin_commit()
            finished.set()
            return {"late": True}

        def timeout_result(_user_text, turn=None):
            observed["timeout_turn"] = turn
            return {"reply": "timed out", "turn": turn.audit_metadata()}

        monkeypatch.setattr(server, "_locked_ws_chat_turn", late_worker)
        monkeypatch.setattr(server, "_ws_chat_timeout_result", timeout_result)
        monkeypatch.setattr(server, "WS_CHAT_REPLY_TIMEOUT_SECONDS", 0.01)

        turn = turn_context.TurnContext.create(
            "slow-turn", principal="guest", surface="websocket", timeout_s=5
        )
        result = await server._ws_chat_turn_with_timeout("slow request", turn=turn)
        assert started.is_set()
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=1)
        return result

    result = asyncio.run(exercise())

    assert result["turn"]["commit_state"] == "cancelled"
    assert result["turn"]["cancel_reason"] == "timeout"
    assert observed["timeout_turn"].cancelled.is_set()
    assert observed["allow_work"] is False
    assert observed["begin_commit"] is False
