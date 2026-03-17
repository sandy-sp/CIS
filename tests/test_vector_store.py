# tests/test_vector_store.py
import pytest
from indexer.vector_store import VectorStore


DIMS = 4  # small dimensions for tests


@pytest.fixture
def store():
    return VectorStore(collection_name="test-collection", dimensions=DIMS, in_memory=True)


def _make_chunk(chunk_id: str, url: str, text: str, vector=None):
    if vector is None:
        vector = [0.1, 0.2, 0.3, 0.4]
    return {
        "id": chunk_id,
        "vector": vector,
        "payload": {
            "url": url,
            "title": "Test Page",
            "page_type": "services",
            "chunk_index": 0,
            "section_heading": "Introduction",
            "text": text,
        },
    }


def test_store_creates_collection(store):
    stats = store.get_collection_stats()
    assert stats["collection_name"] == "test-collection"
    assert stats["dimensions"] == DIMS


def test_upsert_returns_count(store):
    chunks = [
        _make_chunk("chunk-1", "https://example.com/a", "About cloud services"),
        _make_chunk("chunk-2", "https://example.com/b", "About consulting"),
    ]
    count = store.upsert(chunks)
    assert count == 2


def test_upsert_empty_list_returns_zero(store):
    assert store.upsert([]) == 0


def test_count_after_upsert(store):
    chunks = [_make_chunk(f"c{i}", "https://example.com/page", f"chunk {i}") for i in range(3)]
    store.upsert(chunks)
    assert store.count() == 3


def test_search_returns_results(store):
    store.upsert([_make_chunk("c1", "https://example.com/services", "Cloud services")])
    results = store.search([0.1, 0.2, 0.3, 0.4], top_k=5)
    assert len(results) >= 1
    assert "score" in results[0]
    assert "url" in results[0]
    assert "text" in results[0]


def test_search_respects_top_k(store):
    chunks = [_make_chunk(f"c{i}", f"https://example.com/p{i}", f"content {i}") for i in range(5)]
    store.upsert(chunks)
    results = store.search([0.1, 0.2, 0.3, 0.4], top_k=3)
    assert len(results) <= 3


def test_delete_by_url(store):
    store.upsert([
        _make_chunk("c1", "https://example.com/a", "Content A"),
        _make_chunk("c2", "https://example.com/b", "Content B"),
    ])
    initial_count = store.count()
    store.delete_by_url("https://example.com/a")
    # After delete, count should be less
    assert store.count() < initial_count


def test_collection_stats_has_required_keys(store):
    stats = store.get_collection_stats()
    assert "collection_name" in stats
    assert "total_vectors" in stats
    assert "dimensions" in stats
    assert "status" in stats
