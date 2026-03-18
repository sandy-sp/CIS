import pytest
from unittest.mock import MagicMock
from chat.retriever import Retriever, RetrievedChunk
from indexer.embedder import Embedder

DIMS = 4

@pytest.fixture
def mock_embedder():
    e = MagicMock(spec=Embedder)
    e.dimensions = DIMS
    e.embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
    return e

@pytest.fixture
def retriever(mock_embedder):
    return Retriever(
        collection_name="test-rag",
        embedder=mock_embedder,
        in_memory=True,
        use_reranker=False,
    )

def _seed_store(retriever, n=5):
    for i in range(n):
        retriever._store.upsert([{
            "id": f"chunk-{i}",
            "vector": [0.1 + i*0.01, 0.2, 0.3, 0.4],
            "payload": {
                "url": f"https://example.com/page-{i}",
                "title": f"Page {i}",
                "page_type": "services",
                "chunk_index": i,
                "section_heading": f"Section {i}",
                "text": f"Content about topic {i} in detail.",
            },
        }])

def test_retrieve_returns_list(retriever):
    _seed_store(retriever)
    assert isinstance(retriever.retrieve("cloud services"), list)

def test_retrieve_returns_retrieved_chunks(retriever):
    _seed_store(retriever)
    results = retriever.retrieve("cloud services")
    assert all(isinstance(r, RetrievedChunk) for r in results)

def test_retrieve_respects_top_k_final(retriever):
    _seed_store(retriever, n=10)
    retriever.top_k_final = 3
    assert len(retriever.retrieve("cloud")) <= 3

def test_retrieve_empty_collection_returns_empty(retriever):
    assert retriever.retrieve("cloud services") == []

def test_retrieve_chunk_has_required_fields(retriever):
    _seed_store(retriever, n=2)
    results = retriever.retrieve("cloud services")
    if results:
        chunk = results[0]
        assert chunk.url
        assert chunk.text
        assert isinstance(chunk.score, float)

def test_retrieve_embedder_error_returns_empty(retriever, mock_embedder):
    mock_embedder.embed.side_effect = Exception("API error")
    assert retriever.retrieve("cloud services") == []

def test_retrieve_calls_embedder_with_query(retriever, mock_embedder):
    _seed_store(retriever)
    retriever.retrieve("what are cloud services?")
    mock_embedder.embed.assert_called_once_with(["what are cloud services?"])
