# tests/test_indexer_pipeline.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from indexer.pipeline import IndexerPipeline, IndexProgress, _parse_chunk_file
from indexer.embedder import Embedder
from indexer.vector_store import VectorStore


SAMPLE_CHUNK_MD = """---
url: https://example.com/services
title: Our Services
page_type: services
chunk_index: 0
chunk_total: 2
section_heading: 'Cloud Solutions'
word_count: 45
---

We provide comprehensive cloud migration services to help businesses modernize their
infrastructure and reduce costs while improving reliability and scalability.
"""


@pytest.fixture
def mock_embedder():
    embedder = MagicMock(spec=Embedder)
    embedder.dimensions = 4
    embedder.embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
    return embedder


@pytest.fixture
def pipeline(tmp_path, mock_embedder):
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    db_path = tmp_path / "pipeline.db"
    from scraper.pipeline_db import PipelineDB
    db = PipelineDB(db_path=db_path)
    return IndexerPipeline(
        collection_name="test-collection",
        embedder=mock_embedder,
        clean_dir=clean_dir,
        in_memory=True,
        db=db,
    )


def test_parse_chunk_file_extracts_metadata(tmp_path):
    f = tmp_path / "chunk.md"
    f.write_text(SAMPLE_CHUNK_MD)
    result = _parse_chunk_file(f)
    assert result["url"] == "https://example.com/services"
    assert result["chunk_index"] == 0
    assert result["section_heading"] == "Cloud Solutions"
    assert len(result["text"]) > 0


def test_parse_chunk_file_missing_file_returns_none(tmp_path):
    result = _parse_chunk_file(tmp_path / "nonexistent.md")
    assert result is None


def test_pipeline_run_yields_progress(pipeline, tmp_path):
    chunk_file = tmp_path / "clean" / "services_chunk_000.md"
    chunk_file.write_text(SAMPLE_CHUNK_MD)
    pipeline.mock_embedder = pipeline.embedder  # access mock
    pipeline.embedder.embed.return_value = [[0.1, 0.2, 0.3, 0.4]]

    progress_events = list(pipeline.run([chunk_file]))

    assert len(progress_events) > 0
    final = progress_events[-1]
    assert final.chunks_done == 1
    assert final.chunks_total == 1


def test_pipeline_run_calls_embedder(pipeline, tmp_path):
    chunk_file = tmp_path / "clean" / "services_chunk_000.md"
    chunk_file.write_text(SAMPLE_CHUNK_MD)

    list(pipeline.run([chunk_file]))

    pipeline.embedder.embed.assert_called_once()
    call_texts = pipeline.embedder.embed.call_args[0][0]
    assert len(call_texts) == 1
    assert "cloud migration" in call_texts[0].lower()


def test_pipeline_run_empty_returns_empty(pipeline):
    progress_events = list(pipeline.run([]))
    assert progress_events == []


def test_pipeline_get_stats_returns_dict(pipeline):
    stats = pipeline.get_stats()
    assert "total_vectors" in stats
    assert "dimensions" in stats
    assert "collection_name" in stats


def test_pipeline_updates_sqlite_after_indexing(pipeline, tmp_path):
    chunk_file = tmp_path / "clean" / "services_chunk_000.md"
    chunk_file.write_text(SAMPLE_CHUNK_MD)

    # Pre-populate DB so mark_indexed can update
    pipeline._db.upsert_scraped(
        url="https://example.com/services",
        domain="example.com", page_type="services",
        word_count=100, scraped_at="2026-03-17T10:00:00"
    )
    pipeline._db.mark_cleaned("https://example.com/services", "2026-03-17T11:00:00", 2)

    list(pipeline.run([chunk_file]))

    pages = pipeline._db.get_pages()
    assert any(p["status"] == "indexed" for p in pages)
