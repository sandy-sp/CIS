import builtins
import sys
import types

from scraper.scrapling_engine import ScraplingEngine


class _FakePage:
    def __init__(self, html: str, url: str, status: int = 200):
        self.html_content = html
        self.url = url
        self.status = status


def test_scrapling_engine_returns_unavailable_without_dependency():
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scrapling.fetchers":
            raise ImportError("missing scrapling")
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = _fake_import
    engine = ScraplingEngine()
    try:
        result = engine.scrape("https://example.com")
    finally:
        builtins.__import__ = real_import

    assert result.status == "failed"
    assert result.skip_reason == "scrapling unavailable: dependency not installed"


def test_scrapling_engine_scrapes_html(monkeypatch):
    fake_scrapling = types.ModuleType("scrapling")
    fake_fetchers = types.ModuleType("scrapling.fetchers")

    class FakeFetcher:
        @staticmethod
        def get(url, **kwargs):
            assert kwargs["follow_redirects"] is True
            assert kwargs["impersonate"] == "chrome"
            html = """
            <html lang="en">
              <head>
                <title>Example Services</title>
                <meta name="description" content="Advisory and delivery" />
                <link rel="canonical" href="/services" />
              </head>
              <body>
                <main><h1>Services</h1><p>Consulting and implementation.</p></main>
              </body>
            </html>
            """
            return _FakePage(html=html, url=url)

    fake_fetchers.Fetcher = FakeFetcher
    monkeypatch.setitem(sys.modules, "scrapling", fake_scrapling)
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", fake_fetchers)

    engine = ScraplingEngine()
    result = engine.scrape("https://example.com/services")

    assert result.status == "success"
    assert result.engine_used == "scrapling"
    assert result.title == "Example Services"
    assert result.description == "Advisory and delivery"
    assert result.canonical_url == "https://example.com/services"
    assert "Consulting and implementation." in result.markdown
