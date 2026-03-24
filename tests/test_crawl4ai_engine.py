# tests/test_crawl4ai_engine.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from scraper.crawl4ai_engine import Crawl4AIEngine
from models import PageResult


@pytest.fixture
def engine():
    return Crawl4AIEngine()


@pytest.mark.asyncio
async def test_scrape_success_returns_page_result(engine):
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "# Services\n\nWe help businesses."
    mock_result.cleaned_html = "<h1>Services</h1><p>We help businesses.</p>"
    mock_result.metadata = {
        "title": "Services",
        "description": "We help",
        "language": "en",
        "canonical": "https://example.com/services",
    }
    mock_result.links = {"internal": [{"href": "https://example.com/about"}], "external": []}

    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=mock_result)
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        result, links = await engine.scrape("https://example.com/services")

    assert isinstance(result, PageResult)
    assert result.status == "success"
    assert result.engine_used == "crawl4ai"
    assert result.title == "Services"
    assert "Services" in result.markdown
    assert "https://example.com/about" in links


@pytest.mark.asyncio
async def test_scrape_failure_returns_failed_result(engine):
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.markdown = ""
    mock_result.error_message = "Connection refused"

    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=mock_result)
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        result, links = await engine.scrape("https://example.com/broken")

    assert result.status == "failed"
    assert result.skip_reason == "crawl4ai error: Connection refused"
    assert links == []


@pytest.mark.asyncio
async def test_scrape_empty_content_returns_failed(engine):
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "   "  # whitespace only
    mock_result.cleaned_html = ""
    mock_result.metadata = {}
    mock_result.links = {"internal": [], "external": []}

    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=mock_result)
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        result, links = await engine.scrape("https://example.com/empty")

    assert result.status == "failed"
    assert result.skip_reason == "crawl4ai empty"


@pytest.mark.asyncio
async def test_scrape_extracts_internal_links_only(engine):
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.markdown = "# Page\n\nContent here."
    mock_result.cleaned_html = "<h1>Page</h1>"
    mock_result.metadata = {"title": "Page", "description": "", "language": "en", "canonical": ""}
    mock_result.links = {
        "internal": [
            {"href": "https://example.com/about"},
            {"href": "https://example.com/services"},
        ],
        "external": [{"href": "https://linkedin.com/company/example"}],
    }

    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=mock_result)
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        result, links = await engine.scrape("https://example.com/page")

    assert "https://example.com/about" in links
    assert "https://example.com/services" in links
    assert "https://linkedin.com/company/example" not in links


@pytest.mark.asyncio
async def test_scrape_timeout_returns_failed(engine):
    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(side_effect=asyncio.TimeoutError())
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        result, links = await engine.scrape("https://example.com/slow")

    assert result.status == "failed"
    assert result.skip_reason == "crawl4ai timeout"
    assert links == []


@pytest.mark.asyncio
async def test_scrape_disables_engine_after_driver_failure(engine):
    with patch("scraper.crawl4ai_engine.AsyncWebCrawler") as MockCrawler:
        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(side_effect=Exception("Connection.init: Connection closed while reading from the driver"))
        MockCrawler.return_value.__aenter__ = AsyncMock(return_value=mock_crawler)
        MockCrawler.return_value.__aexit__ = AsyncMock(return_value=None)

        first_result, first_links = await engine.scrape("https://example.com/js")
        second_result, second_links = await engine.scrape("https://example.com/js-2")

    assert first_result.status == "failed"
    assert first_result.skip_reason == "crawl4ai unavailable: playwright driver unavailable"
    assert second_result.status == "failed"
    assert second_result.skip_reason == "crawl4ai unavailable: playwright driver unavailable"
    assert first_links == []
    assert second_links == []
    assert mock_crawler.arun.await_count == 1
