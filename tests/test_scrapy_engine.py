import json
import pytest
from unittest.mock import patch, MagicMock
from scraper.scrapy_engine import ScrapyEngine
from models import PageResult

SAMPLE_OUTPUT = json.dumps({
    "url": "https://example.com/services",
    "title": "Services",
    "description": "We do things",
    "language": "en",
    "canonical_url": "https://example.com/services",
    "raw_html": "<h1>Services</h1><p>We do things</p>",
    "markdown": "# Services\n\nWe do things",
    "status": "success",
})


@pytest.fixture
def engine():
    return ScrapyEngine()


def test_scrape_success_parses_json_output(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=SAMPLE_OUTPUT,
            stderr="",
        )
        result = engine.scrape("https://example.com/services")

    assert isinstance(result, PageResult)
    assert result.status == "success"
    assert result.engine_used == "scrapy"
    assert result.title == "Services"
    assert "Services" in result.markdown


def test_scrape_subprocess_failure_returns_failed(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Spider error",
        )
        result = engine.scrape("https://example.com/broken")

    assert result.status == "failed"
    assert "scrapy" in result.skip_reason.lower()


def test_scrape_timeout_returns_failed(engine):
    import subprocess
    with patch("scraper.scrapy_engine.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 20)):
        result = engine.scrape("https://example.com/slow")

    assert result.status == "failed"
    assert "timeout" in result.skip_reason.lower()


def test_scrape_sets_engine_used(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=SAMPLE_OUTPUT, stderr="")
        result = engine.scrape("https://example.com/services")

    assert result.engine_used == "scrapy"


def test_scrape_invalid_json_returns_failed(engine):
    with patch("scraper.scrapy_engine.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        result = engine.scrape("https://example.com/bad")

    assert result.status == "failed"
    assert "scrapy" in result.skip_reason.lower()


def test_start_requests_sets_playwright_meta():
    """BUG-D: SinglePageSpider.start_requests() must set meta['playwright'] = True."""
    import sys
    import types

    # Build minimal scrapy mock so scrapy_worker can be imported without scrapy installed
    fake_scrapy = types.ModuleType("scrapy")

    class FakeRequest:
        def __init__(self, url, meta=None, callback=None):
            self.url = url
            self.meta = meta or {}
            self.callback = callback

    class FakeSpider:
        name = ""
        custom_settings = {}
        def __init__(self, *args, **kwargs):
            pass

    fake_scrapy.Spider = FakeSpider
    fake_scrapy.Request = FakeRequest

    # Also stub out sub-modules referenced at import time
    for sub in ("scrapy_playwright", "scrapy_playwright.handler", "bs4", "html2text"):
        if sub not in sys.modules:
            sys.modules[sub] = types.ModuleType(sub)

    fake_crawler_mod = types.ModuleType("scrapy.crawler")

    class FakeCrawlerProcess:
        def __init__(self, *args, **kwargs):
            pass
        def crawl(self, *args, **kwargs):
            pass
        def start(self):
            pass

    fake_crawler_mod.CrawlerProcess = FakeCrawlerProcess
    sys.modules["scrapy.crawler"] = fake_crawler_mod
    fake_scrapy.crawler = fake_crawler_mod

    was_present = "scrapy" in sys.modules
    old_scrapy = sys.modules.get("scrapy")
    sys.modules["scrapy"] = fake_scrapy

    # Remove cached scrapy_worker so it re-imports with our mock
    old_worker = sys.modules.pop("scraper.scrapy_worker", None)
    try:
        from scraper.scrapy_worker import SinglePageSpider
        container = []
        spider = SinglePageSpider.__new__(SinglePageSpider)
        spider.start_urls = ["https://example.com/js-heavy"]
        spider.result_container = container
        requests = list(spider.start_requests())
        assert len(requests) == 1
        assert requests[0].meta.get("playwright") is True
    finally:
        # Restore modules to avoid polluting other tests
        if old_worker is not None:
            sys.modules["scraper.scrapy_worker"] = old_worker
        else:
            sys.modules.pop("scraper.scrapy_worker", None)
        if was_present:
            sys.modules["scrapy"] = old_scrapy
        else:
            sys.modules.pop("scrapy", None)
