import pytest
import tempfile
from pathlib import Path
from scraper.pipeline_db import PipelineDB


@pytest.fixture
def db(tmp_path):
    return PipelineDB(db_path=tmp_path / "test.db")


def test_upsert_scraped_inserts_row(db):
    db.upsert_scraped("https://example.com/about", "example.com", "about", 500, "2026-03-17T10:00:00")
    pages = db.get_pages()
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example.com/about"
    assert pages[0]["page_type"] == "about"
    assert pages[0]["status"] == "scraped"


def test_upsert_scraped_is_idempotent(db):
    db.upsert_scraped("https://example.com/about", "example.com", "about", 500, "2026-03-17T10:00:00")
    db.upsert_scraped("https://example.com/about", "example.com", "about", 600, "2026-03-17T11:00:00")
    pages = db.get_pages()
    assert len(pages) == 1
    assert pages[0]["word_count"] == 600  # updated


def test_mark_cleaned(db):
    db.upsert_scraped("https://example.com/about", "example.com", "about", 500, "2026-03-17T10:00:00")
    db.mark_cleaned("https://example.com/about", "2026-03-17T11:00:00", chunk_count=3)
    pages = db.get_pages()
    assert pages[0]["status"] == "cleaned"
    assert pages[0]["chunk_count"] == 3
    assert pages[0]["cleaned_at"] is not None


def test_mark_indexed(db):
    db.upsert_scraped("https://example.com/about", "example.com", "about", 500, "2026-03-17T10:00:00")
    db.mark_indexed("https://example.com/about", "2026-03-17T12:00:00")
    pages = db.get_pages()
    assert pages[0]["status"] == "indexed"
    assert pages[0]["indexed_at"] is not None


def test_get_pages_filtered_by_domain(db):
    db.upsert_scraped("https://example.com/about", "example.com", "about", 500, "2026-03-17T10:00:00")
    db.upsert_scraped("https://other.com/page", "other.com", "other", 300, "2026-03-17T10:00:00")
    pages = db.get_pages(domain="example.com")
    assert len(pages) == 1
    assert pages[0]["domain"] == "example.com"


def test_get_stats(db):
    db.upsert_scraped("https://example.com/a", "example.com", "other", 100, "2026-03-17T10:00:00")
    db.upsert_scraped("https://example.com/b", "example.com", "other", 200, "2026-03-17T10:00:00")
    db.mark_cleaned("https://example.com/b", "2026-03-17T11:00:00", chunk_count=2)
    stats = db.get_stats(domain="example.com")
    assert stats["total"] == 2
    assert stats["scraped"] == 1
    assert stats["cleaned"] == 1
