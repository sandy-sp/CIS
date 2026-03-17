from datetime import datetime, timezone
from models import PageResult


def test_page_result_required_field():
    result = PageResult(url="https://example.com")
    assert result.url == "https://example.com"


def test_page_result_defaults():
    result = PageResult(url="https://example.com")
    assert result.canonical_url == ""
    assert result.title == ""
    assert result.description == ""
    assert result.language == ""
    assert result.headings == []
    assert result.raw_html == ""
    assert result.markdown == ""
    assert result.page_type == "other"
    assert result.word_count == 0
    assert result.engine_used == ""
    assert result.status == "failed"
    assert result.skip_reason == ""
    assert isinstance(result.scraped_at, datetime)


def test_page_result_scraped_at_is_utc():
    result = PageResult(url="https://example.com")
    assert result.scraped_at.tzinfo == timezone.utc


def test_page_result_headings_is_not_shared():
    """Each instance must have its own headings list (mutable default trap)."""
    a = PageResult(url="https://example.com/a")
    b = PageResult(url="https://example.com/b")
    a.headings.append({"h1": "Title"})
    assert b.headings == []
