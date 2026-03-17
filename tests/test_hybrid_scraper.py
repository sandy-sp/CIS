# tests/test_hybrid_scraper.py
import pytest
import fakeredis
from unittest.mock import AsyncMock, MagicMock, patch
from models import PageResult
from scraper.hybrid_scraper import HybridScraper
from scraper.queue_manager import QueueManager
from scraper.snooper import Snooper


@pytest.fixture
def qm(fake_redis):
    qm = QueueManager("example.com", redis_client=fake_redis)
    qm.enqueue("https://example.com/about")
    qm.enqueue("https://example.com/services")
    return qm


@pytest.fixture
def snooper():
    s = MagicMock(spec=Snooper)
    s.is_disallowed.return_value = False
    s.is_external.return_value = False
    s.has_noindex.return_value = False
    s.has_nofollow.return_value = False
    s.crawl_delay = 0  # no delay in tests
    return s


@pytest.fixture
def success_result():
    return PageResult(url="https://example.com/about", status="success",
                      markdown="# About\n\nContent.", engine_used="crawl4ai")


@pytest.fixture
def failed_result():
    return PageResult(url="https://example.com/about", status="failed",
                      skip_reason="crawl4ai timeout")


@pytest.mark.asyncio
async def test_yields_success_result(qm, snooper, success_result):
    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(success_result, []))
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=2)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert any(r.status == "success" for r in results)


@pytest.mark.asyncio
async def test_falls_back_to_scrapy_on_crawl4ai_failure(qm, snooper, failed_result):
    scrapy_success = PageResult(url="https://example.com/about", status="success",
                                 markdown="# About", engine_used="scrapy")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine") as MockFallback, \
         patch("scraper.hybrid_scraper.asyncio.get_event_loop"):
        mock_primary = AsyncMock()
        mock_primary.scrape = AsyncMock(return_value=(failed_result, []))
        MockPrimary.return_value = mock_primary

        mock_fallback = MagicMock()
        mock_fallback.scrape.return_value = scrapy_success
        MockFallback.return_value = mock_fallback

        scraper = HybridScraper(qm, snooper, max_pages=1)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert any(r.engine_used == "scrapy" for r in results)


@pytest.mark.asyncio
async def test_skips_disallowed_url(qm, snooper):
    snooper.is_disallowed.return_value = True

    with patch("scraper.hybrid_scraper.Crawl4AIEngine"), \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        scraper = HybridScraper(qm, snooper, max_pages=2)
        results = [r async for r in scraper.crawl("https://example.com")]

    skipped = [r for r in results if r.status == "skipped"]
    assert len(skipped) > 0
    assert all("robots" in r.skip_reason for r in skipped)


@pytest.mark.asyncio
async def test_saves_external_url_instead_of_crawling(qm, snooper, fake_redis):
    # Setup: second URL is external
    snooper.is_external.side_effect = lambda url: "linkedin" in url
    qm.enqueue("https://linkedin.com/company/example")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(
            PageResult(url="https://example.com/about", status="success", markdown="x"),
            []
        ))
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=10)
        results = [r async for r in scraper.crawl("https://example.com")]

    # LinkedIn URL should not appear as a result
    assert not any("linkedin" in r.url for r in results)


@pytest.mark.asyncio
async def test_respects_max_pages_limit(fake_redis, snooper):
    qm = QueueManager("example.com", redis_client=fake_redis)
    for i in range(10):
        qm.enqueue(f"https://example.com/page-{i}")

    success = PageResult(url="x", status="success", markdown="content")

    with patch("scraper.hybrid_scraper.Crawl4AIEngine") as MockPrimary, \
         patch("scraper.hybrid_scraper.ScrapyEngine"):
        mock_engine = AsyncMock()
        mock_engine.scrape = AsyncMock(return_value=(success, []))
        MockPrimary.return_value = mock_engine

        scraper = HybridScraper(qm, snooper, max_pages=3)
        results = [r async for r in scraper.crawl("https://example.com")]

    assert len([r for r in results if r.status == "success"]) <= 3
