"""Phase 6A regression coverage for bounded semantic memory recall."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from alpecca import memory as memory_store
from alpecca import state as state_store


class FakeEmbedder:
    """Return exact, deterministic vectors for stored text and recall queries."""

    def __init__(self, vectors: dict[str, list]) -> None:
        self._vectors = vectors

    def __call__(self, text: str) -> list:
        return list(self._vectors[text])


def _memory_db(tmp_path, name: str):
    db_path = tmp_path / name
    state_store.init_db(db_path)
    return db_path


def test_orthogonal_high_salience_semantic_memory_abstains(tmp_path):
    content = "crimson observatory ledger"
    query = "velvet violin request"
    embed = FakeEmbedder({content: [1.0, 0.0], query: [0.0, 1.0]})
    db_path = _memory_db(tmp_path, "orthogonal.db")

    assert memory_store.remember(
        content,
        salience=1.0,
        db_path=db_path,
        embed_fn=embed,
    )

    assert memory_store.recall(query, db_path=db_path, embed_fn=embed) == []


def test_negative_cosine_semantic_memory_abstains(tmp_path):
    content = "amber telescope ledger"
    query = "violet rainfall melody"
    embed = FakeEmbedder(
        {
            content: [1.0, 0.0],
            query: [-0.5, 0.8660254037844386],
        }
    )
    db_path = _memory_db(tmp_path, "negative.db")

    assert memory_store.remember(
        content,
        salience=1.0,
        db_path=db_path,
        embed_fn=embed,
    )

    assert memory_store.recall(query, db_path=db_path, embed_fn=embed) == []


def test_related_lexically_disjoint_vectors_recall_semantically(tmp_path):
    content = "Biscuit rests beneath the sycamore canopy"
    query = "puppy enjoys a woodland stroll"
    embed = FakeEmbedder({content: [1.0, 0.0], query: [0.98, 0.2]})
    db_path = _memory_db(tmp_path, "related.db")

    assert memory_store.remember(
        content,
        salience=0.8,
        db_path=db_path,
        embed_fn=embed,
    )

    hits = memory_store.recall(query, db_path=db_path, embed_fn=embed)

    assert [hit["content"] for hit in hits] == [content]
    assert hits[0]["recall_method"] == "semantic"
    assert hits[0]["recall_similarity"] > 0.9


@pytest.mark.parametrize(
    "stored_vector,query_vector",
    [
        pytest.param(["not-a-number", 1.0], [1.0, 0.0], id="malformed"),
        pytest.param([0.0, 0.0], [1.0, 0.0], id="zero"),
        pytest.param([1.0, 0.0, 0.0], [1.0, 0.0], id="mixed-dimension"),
    ],
)
def test_unusable_vectors_fall_back_to_lexical_recall(
    tmp_path,
    stored_vector,
    query_vector,
):
    content = "lexical fallback anchor remains available"
    query = "find the lexical fallback anchor"
    embed = FakeEmbedder({content: stored_vector, query: query_vector})
    db_path = _memory_db(tmp_path, "fallback.db")

    assert memory_store.remember(
        content,
        salience=0.8,
        db_path=db_path,
        embed_fn=embed,
    )

    hits = memory_store.recall(query, db_path=db_path, embed_fn=embed)

    assert [hit["content"] for hit in hits] == [content]
    assert hits[0]["recall_method"] == "keyword"
    assert hits[0]["recall_similarity"] > 0.0


def test_semantic_recall_remains_isolated_to_requested_scope(tmp_path):
    creator_content = "creator cedar recollection"
    guest_content = "guest birch recollection"
    query = "hidden grove prompt"
    embed = FakeEmbedder(
        {
            creator_content: [1.0, 0.0],
            guest_content: [1.0, 0.0],
            query: [1.0, 0.0],
        }
    )
    db_path = _memory_db(tmp_path, "scopes.db")

    assert memory_store.remember(
        creator_content,
        salience=0.8,
        db_path=db_path,
        embed_fn=embed,
        scope="creator-private",
    )
    assert memory_store.remember(
        guest_content,
        salience=0.8,
        db_path=db_path,
        embed_fn=embed,
        scope="guest-private",
    )

    creator_hits = memory_store.recall(
        query,
        top_k=5,
        db_path=db_path,
        embed_fn=embed,
        scope="creator-private",
        include_shared=False,
    )
    guest_hits = memory_store.recall(
        query,
        top_k=5,
        db_path=db_path,
        embed_fn=embed,
        scope="guest-private",
        include_shared=False,
    )

    assert [hit["content"] for hit in creator_hits] == [creator_content]
    assert [hit["scope"] for hit in creator_hits] == ["creator-private"]
    assert [hit["content"] for hit in guest_hits] == [guest_content]
    assert [hit["scope"] for hit in guest_hits] == ["guest-private"]


def test_semantic_recall_order_and_results_are_deterministic(tmp_path, monkeypatch):
    first_content = "scarlet observatory account"
    second_content = "indigo shoreline record"
    query = "retrieve the remembered scenes"
    embed = FakeEmbedder(
        {
            first_content: [1.0, 0.0],
            second_content: [0.0, 1.0],
            query: [0.8, 0.6],
        }
    )
    db_path = _memory_db(tmp_path, "ordering.db")

    write_times = iter((1_000.0, 1_001.0))
    monkeypatch.setattr(
        memory_store,
        "time",
        SimpleNamespace(time=lambda: next(write_times)),
    )
    assert memory_store.remember(
        first_content,
        salience=0.8,
        db_path=db_path,
        embed_fn=embed,
    )
    assert memory_store.remember(
        second_content,
        salience=0.8,
        db_path=db_path,
        embed_fn=embed,
    )

    monkeypatch.setattr(
        memory_store,
        "time",
        SimpleNamespace(time=lambda: 2_000.0),
    )
    first_run = memory_store.recall(
        query,
        top_k=2,
        db_path=db_path,
        embed_fn=embed,
    )
    second_run = memory_store.recall(
        query,
        top_k=2,
        db_path=db_path,
        embed_fn=embed,
    )

    assert first_run == second_run
    assert [hit["content"] for hit in first_run] == [
        first_content,
        second_content,
    ]
    assert all(hit["recall_method"] == "semantic" for hit in first_run)
