# tests/test_pipeline.py
import pytest
from pathlib import Path
from processor.pipeline import Pipeline, ProcessingResult


SAMPLE_MD = """---
url: https://example.com/services
title: Our Services
page_type: services
word_count: 150
scraped_at: 2026-03-17T10:00:00Z
engine_used: crawl4ai
---

# Our Services

We provide comprehensive business consulting services to help companies grow and thrive
in the digital age. Our expert team brings decades of experience across multiple industries
including technology, finance, healthcare, and retail.

## Cloud Solutions

Migrate your infrastructure to the cloud with our proven methodology. We handle
everything from initial assessment to full deployment, monitoring, and ongoing support.
Our cloud solutions reduce costs by an average of 30% while improving reliability.

## Digital Strategy

Develop a comprehensive digital strategy that aligns with your business objectives.
Our consultants work closely with your leadership team to define roadmaps and priorities
that drive measurable outcomes and competitive advantage.
"""

NOISE_MD = """---
url: https://example.com/privacy
title: Privacy Policy
page_type: other
word_count: 20
scraped_at: 2026-03-17T10:00:00Z
engine_used: crawl4ai
---

# Privacy Policy

We respect your privacy.
"""


@pytest.fixture
def pipeline(tmp_path):
    raw_dir = tmp_path / "raw"
    clean_dir = tmp_path / "clean"
    raw_dir.mkdir()
    db_path = tmp_path / "pipeline.db"
    from scraper.pipeline_db import PipelineDB
    db = PipelineDB(db_path=db_path)
    return Pipeline(raw_dir=raw_dir, clean_dir=clean_dir, db=db)


def test_pipeline_processes_markdown_file(pipeline, tmp_path):
    md_file = tmp_path / "raw" / "services.md"
    md_file.write_text(SAMPLE_MD)

    results = pipeline.run([md_file])

    assert len(results) == 1
    assert not results[0].skipped
    assert results[0].chunk_count > 0
    assert results[0].clean_word_count > 0


def test_pipeline_skips_noise_url(pipeline, tmp_path):
    md_file = tmp_path / "raw" / "privacy.md"
    md_file.write_text(NOISE_MD)

    results = pipeline.run([md_file])

    assert len(results) == 1
    assert results[0].skipped
    assert results[0].skip_reason == "noise-url"


def test_pipeline_saves_chunks_to_clean_dir(pipeline, tmp_path):
    md_file = tmp_path / "raw" / "services.md"
    md_file.write_text(SAMPLE_MD)
    clean_dir = tmp_path / "clean"

    pipeline.run([md_file])

    chunk_files = list(clean_dir.glob("*.md"))
    assert len(chunk_files) > 0


def test_pipeline_chunk_files_have_frontmatter(pipeline, tmp_path):
    md_file = tmp_path / "raw" / "services.md"
    md_file.write_text(SAMPLE_MD)

    pipeline.run([md_file])

    chunk_files = list((tmp_path / "clean").glob("*.md"))
    assert chunk_files  # at least one chunk
    content = chunk_files[0].read_text()
    assert content.startswith("---")
    assert "url:" in content
    assert "chunk_index:" in content


def test_pipeline_updates_sqlite(pipeline, tmp_path):
    md_file = tmp_path / "raw" / "services.md"
    md_file.write_text(SAMPLE_MD)

    # First upsert_scraped so mark_cleaned can update
    pipeline._db.upsert_scraped(
        url="https://example.com/services",
        domain="example.com",
        page_type="services",
        word_count=150,
        scraped_at="2026-03-17T10:00:00",
    )

    pipeline.run([md_file])

    pages = pipeline._db.get_pages()
    assert len(pages) == 1
    assert pages[0]["status"] == "cleaned"
    assert pages[0]["chunk_count"] > 0


def test_pipeline_empty_file_list_returns_empty(pipeline):
    results = pipeline.run([])
    assert results == []
