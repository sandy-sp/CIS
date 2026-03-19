# tests/test_indexer_pipeline.py
import pytest
from unittest.mock import MagicMock
from company_intel.models import CrawlSettings, PageRecord
from company_intel.storage import JobStorage
from indexer.pipeline import IndexerPipeline, _page_record_to_chunks
from indexer.embedder import Embedder


@pytest.fixture
def mock_embedder():
    embedder = MagicMock(spec=Embedder)
    embedder.dimensions = 4
    embedder.embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
    return embedder


@pytest.fixture
def pipeline(tmp_path, mock_embedder):
    db_path = tmp_path / "pipeline.db"
    from scraper.pipeline_db import PipelineDB
    db = PipelineDB(db_path=db_path)
    return IndexerPipeline(
        collection_name="test-collection",
        embedder=mock_embedder,
        in_memory=True,
        db=db,
    )


def _sample_record() -> PageRecord:
    return PageRecord(
        url="https://example.com/services/cloud",
        normalized_url="https://example.com/services/cloud",
        domain="example.com",
        path="/services/cloud",
        title="Cloud Services",
        markdown=(
            "# Cloud Services\n\n"
            "We provide comprehensive cloud migration services to modernize "
            "infrastructure and improve reliability."
        ),
        clean_text=(
            "We provide comprehensive cloud migration services to modernize "
            "infrastructure and improve reliability."
        ),
        page_category="services",
        page_subtype="managed-services",
        source_type="internal",
        status="success",
        word_count=13,
    )


def test_pipeline_run_yields_progress(pipeline):
    pipeline.embedder.embed.return_value = [[0.1, 0.2, 0.3, 0.4]]

    progress_events = list(pipeline.run([_sample_record()]))

    assert len(progress_events) > 0
    final = progress_events[-1]
    assert final.chunks_done == 1
    assert final.chunks_total == 1


def test_pipeline_run_calls_embedder(pipeline):
    list(pipeline.run([_sample_record()]))

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


def test_pipeline_updates_sqlite_after_indexing(pipeline):
    # Pre-populate DB so mark_indexed can update
    pipeline._db.upsert_scraped(
        url="https://example.com/services/cloud",
        domain="example.com",
        page_type="services",
        word_count=100, scraped_at="2026-03-17T10:00:00"
    )
    pipeline._db.mark_cleaned("https://example.com/services/cloud", "2026-03-17T11:00:00", 1)

    list(pipeline.run([_sample_record()]))

    pages = pipeline._db.get_pages()
    assert any(p["status"] == "indexed" for p in pages)


def test_page_record_to_chunks_uses_company_intel_metadata():
    record = PageRecord(
        url="https://example.com/services/cloud",
        normalized_url="https://example.com/services/cloud",
        domain="example.com",
        path="/services/cloud",
        title="Cloud Services",
        markdown="# Cloud Services\n\nWe provide cloud migration and managed platform support.",
        clean_text="We provide cloud migration and managed platform support.",
        page_category="services",
        page_subtype="managed-services",
        source_type="internal",
        word_count=9,
    )

    chunks = _page_record_to_chunks(record, job_id="job-123")

    assert len(chunks) == 1
    assert chunks[0]["page_type"] == "services"
    assert chunks[0]["source_type"] == "internal"
    assert chunks[0]["job_id"] == "job-123"
    assert "cloud migration" in chunks[0]["text"].lower()


def test_pipeline_run_job_indexes_company_records(tmp_path, mock_embedder):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    job.status = "completed"
    storage.save_job(job)

    record = PageRecord(
        url="https://example.com/about",
        normalized_url="https://example.com/about",
        domain="example.com",
        path="/about",
        title="About Example",
        markdown="# About\n\nExample builds regulated data platforms.",
        clean_text="Example builds regulated data platforms.",
        page_category="company",
        source_type="internal",
        word_count=5,
    )
    storage.save_page_record(job.job_id, record)

    db_path = tmp_path / "pipeline.db"
    from scraper.pipeline_db import PipelineDB
    db = PipelineDB(db_path=db_path)

    pipeline = IndexerPipeline(
        collection_name="job-test",
        embedder=mock_embedder,
        in_memory=True,
        db=db,
        storage=storage,
    )

    progress_events = list(pipeline.run_job(job.job_id))

    assert progress_events
    assert progress_events[-1].chunks_total == 1
    assert pipeline.get_stats()["total_vectors"] == 1


def test_page_record_to_chunks_skips_unapproved_external_records():
    record = PageRecord(
        url="https://news.example.org/example-biotech",
        normalized_url="https://news.example.org/example-biotech",
        domain="news.example.org",
        path="/example-biotech",
        source_type="external",
        discovered_via="search",
        title="Example Biotech News",
        markdown="# Example\n\nExample Biotech news item.",
        clean_text="Example Biotech news item.",
        page_category="resources",
        metadata={"review_status": "pending"},
        status="success",
        word_count=4,
    )

    chunks = _page_record_to_chunks(record, job_id="job-123")

    assert chunks == []


def test_replace_job_collection_removes_rejected_external_vectors(tmp_path, mock_embedder):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    job.status = "completed"
    storage.save_job(job)

    approved_external = PageRecord(
        url="https://linkedin.com/company/example",
        normalized_url="https://linkedin.com/company/example",
        domain="linkedin.com",
        path="/company/example",
        title="Example on LinkedIn",
        markdown="# Example\n\nExample company profile.",
        clean_text="Example company profile.",
        page_category="external-profile",
        source_type="external",
        metadata={"review_status": "approved"},
        status="success",
        word_count=3,
    )
    storage.save_page_record(job.job_id, approved_external)

    db_path = tmp_path / "pipeline.db"
    from scraper.pipeline_db import PipelineDB
    db = PipelineDB(db_path=db_path)
    pipeline = IndexerPipeline(
        collection_name="job-refresh-test",
        embedder=mock_embedder,
        in_memory=True,
        db=db,
        storage=storage,
    )

    list(pipeline.replace_job_collection(job.job_id, include_external=True))
    assert pipeline.get_stats()["total_vectors"] == 1

    approved_external.metadata["review_status"] = "rejected"
    storage.save_page_record(job.job_id, approved_external)

    list(pipeline.replace_job_collection(job.job_id, include_external=True))
    assert pipeline.get_stats()["total_vectors"] == 0
