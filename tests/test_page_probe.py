from unittest.mock import MagicMock, patch

from scraper.page_probe import EngineRouter


def test_probe_prefers_crawl4ai_for_js_markers():
    router = EngineRouter()
    response = MagicMock(status_code=200, text='<html><div id="__next"></div><script>window.__NEXT_DATA__={}</script></html>')
    with patch("scraper.page_probe.requests.get", return_value=response):
        result = router.probe("https://example.com/app")

    assert result.primary_engine == "crawl4ai"
    assert result.reason == "js-markers"


def test_probe_prefers_scrapy_for_static_page():
    router = EngineRouter()
    html = "<html><body><h1>Services</h1><p>We provide consulting services for life sciences organizations.</p></body></html>"
    response = MagicMock(status_code=200, text=html)
    with patch("scraper.page_probe.requests.get", return_value=response):
        result = router.probe("https://example.com/services")

    assert result.primary_engine == "scrapy"
    assert result.reason == "static-friendly"
