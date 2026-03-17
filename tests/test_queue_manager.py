# tests/test_queue_manager.py
import pytest
import fakeredis
from scraper.queue_manager import QueueManager


@pytest.fixture
def qm(fake_redis):
    return QueueManager("example.com", redis_client=fake_redis)


def test_enqueue_and_dequeue(qm):
    qm.enqueue("https://example.com/about")
    qm.enqueue("https://example.com/services")
    assert qm.dequeue() == "https://example.com/about"
    assert qm.dequeue() == "https://example.com/services"
    assert qm.dequeue() is None


def test_enqueue_deduplicates_same_url(qm):
    qm.enqueue("https://example.com/about")
    qm.enqueue("https://example.com/about")
    assert qm.dequeue() == "https://example.com/about"
    assert qm.dequeue() is None


def test_enqueue_normalizes_trailing_slash(qm):
    qm.enqueue("https://example.com/about/")
    qm.enqueue("https://example.com/about")
    assert qm.dequeue() is not None
    assert qm.dequeue() is None  # second was a duplicate after normalisation


def test_normalize_url_sorts_query_params(qm):
    norm = qm.normalize("https://example.com/page?b=2&a=1")
    assert norm == "https://example.com/page?a=1&b=2"


def test_normalize_url_lowercases_domain(qm):
    norm = qm.normalize("https://EXAMPLE.COM/About")
    assert norm == "https://example.com/About"


def test_mark_visited_and_is_visited(qm):
    qm.mark_visited("https://example.com/page")
    assert qm.is_visited("https://example.com/page")
    assert not qm.is_visited("https://example.com/other")


def test_enqueue_does_not_mark_as_scraped(qm):
    """Enqueueing a URL must NOT mark it as scraped (two-set design)."""
    qm.enqueue("https://example.com/about")
    assert not qm.is_visited("https://example.com/about")  # not yet scraped
    qm.mark_visited("https://example.com/about")
    assert qm.is_visited("https://example.com/about")  # now scraped


def test_content_hash_dedup(qm):
    assert not qm.is_duplicate_content("abc123hash")
    qm.add_content_hash("abc123hash")
    assert qm.is_duplicate_content("abc123hash")


def test_save_and_get_external_link(qm):
    qm.save_external("https://linkedin.com/company/example")
    qm.save_external("https://linkedin.com/company/example")  # duplicate
    qm.save_external("https://twitter.com/example")
    links = qm.get_external_links()
    assert "linkedin.com" in links
    assert len(links["linkedin.com"]) == 1  # deduped
    assert "twitter.com" in links


def test_log_line_stored(qm):
    qm.log("[OK] /about [crawl4ai] 500w")
    qm.log("[OK] /services [crawl4ai] 800w")
    lines = qm.get_log_lines(50)
    assert "[OK] /about [crawl4ai] 500w" in lines


def test_update_and_get_meta(qm):
    qm.update_meta(pages_done=5, pages_found=20, total_words=4000)
    meta = qm.get_meta()
    assert meta["pages_done"] == "5"
    assert meta["pages_found"] == "20"
    assert meta["total_words"] == "4000"


def test_has_existing_state(qm):
    assert not qm.has_existing_state()
    qm.enqueue("https://example.com/")
    assert qm.has_existing_state()


def test_flush_clears_all_keys(qm):
    qm.enqueue("https://example.com/")
    qm.mark_visited("https://example.com/about")
    qm.flush()
    assert not qm.has_existing_state()
    assert not qm.is_visited("https://example.com/about")
