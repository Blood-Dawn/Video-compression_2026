from __future__ import annotations

import numpy as np
import pytest

from src.gui.services.semantic_search import SemanticSearchIndex, StubEmbedder


def test_stub_embedder_is_deterministic():
    embedder = StubEmbedder(dimension=16)
    first = embedder.embed(["Person near the entrance"])
    second = embedder.embed(["Person near the entrance"])

    assert first.shape == (1, 16)
    assert np.array_equal(first, second)


def test_stub_embedder_does_not_need_a_model():
    embedder = StubEmbedder(dimension=8)
    vectors = embedder.embed(["vehicle at night", "person at entrance"])

    assert vectors.shape == (2, 8)
    assert np.all(np.isfinite(vectors))


def test_stub_embedder_empty_input():
    embedder = StubEmbedder(dimension=8)
    vectors = embedder.embed([])

    assert vectors.shape == (0, 8)


def test_index_ranks_results():
    embedder = StubEmbedder(dimension=32)
    index = SemanticSearchIndex(embedder)

    index.add(
        [101, 102],
        ["person near the entrance", "vehicle in the parking lot"],
    )

    results = index.search("person near the entrance", limit=2)

    assert len(results) == 2
    assert results[0].item_id == 101
    assert results[0].score >= results[1].score


def test_index_validates_lengths():
    index = SemanticSearchIndex(StubEmbedder())

    with pytest.raises(ValueError, match="same length"):
        index.add([1], ["one", "two"])


def test_index_limit_and_empty_behavior():
    index = SemanticSearchIndex(StubEmbedder())

    assert index.search("anything") == []

    index.add([1, 2], ["first", "second"])

    assert len(index.search("anything", limit=1)) == 1
    assert index.search("anything", limit=0) == []
