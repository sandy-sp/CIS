from __future__ import annotations

import asyncio
import re
from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from models import PageResult
from scraper.page_probe import EngineRouter
from scraper.snooper import Snooper


_NOISE_URL_PATTERNS = re.compile(
    r"/(privacy|terms|cookie|legal|sitemap|gdpr|disclaimer|imprint|impressum)",
    re.IGNORECASE,
)
_NOISE_QUERY_PARAMS = re.compile(
    r"[?&](ical|outlook-ical|tribe-bar-date)=",
    re.IGNORECASE,
)
_CALENDAR_DATE_PATH = re.compile(
    r"/(day|week|month|year)/\d{4}-\d{2}",
    re.IGNORECASE,
)
_LOGIN_PATTERNS = re.compile(
    r"\b(sign\s*in|log\s*in|login|sign\s*up|create\s+account|please\s+authenticate)\b",
    re.IGNORECASE,
)


def _normalize_url(url: str) -> str:
    stripped = urldefrag(url.strip()).url
    parsed = urlparse(stripped)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query = parsed.query
    return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")


class SiteCrawler:
    """Simple first-party crawler with a static/browser engine pair."""

    def __init__(
        self,
        snooper: Snooper,
        *,
        max_pages: int = 500,
        ignore_robots_exclusions: bool = True,
        rate_limit: float = 1.0,
        engine_router: EngineRouter | None = None,
        browser_engine=None,
        static_engine=None,
    ):
        self.snooper = snooper
        self.max_pages = max_pages
        self.ignore_robots_exclusions = ignore_robots_exclusions
        self.rate_limit = rate_limit
        self.engine_router = engine_router or EngineRouter()
        if browser_engine is None or static_engine is None:
            from scraper.crawl4ai_engine import Crawl4AIEngine
            from scraper.static_engine import StaticEngine
            browser_engine = browser_engine or Crawl4AIEngine()
            static_engine = static_engine or StaticEngine()

        self.browser = browser_engine
        self.static = static_engine
        self.discovered_count = 0
        self.processed_count = 0
        self._enqueued: set[str] = set()
        self._visited: set[str] = set()

    async def crawl(
        self,
        seed_urls: list[str],
        *,
        cancel_requested=None,
    ):
        queue = deque()
        for url in seed_urls:
            self._enqueue(queue, url)

        while queue and self.processed_count < self.max_pages:
            if cancel_requested and cancel_requested():
                break

            url = queue.popleft()
            normalized = _normalize_url(url)
            if normalized in self._visited:
                continue

            result, links = await self._scrape_url(url)
            self._visited.add(normalized)
            self.processed_count += 1

            if result.status == "success" and not self.snooper.has_nofollow(result.raw_html):
                for link in links:
                    if not self.snooper.is_external(link):
                        self._enqueue(queue, link)

            yield result

            if self.rate_limit > 0:
                await asyncio.sleep(self.rate_limit)

    def _enqueue(self, queue: deque[str], url: str) -> None:
        normalized = _normalize_url(url)
        if normalized in self._enqueued:
            return
        self._enqueued.add(normalized)
        queue.append(url)
        self.discovered_count = len(self._enqueued)

    async def _scrape_url(self, url: str) -> tuple[PageResult, list[str]]:
        if self.snooper.is_external(url):
            return PageResult(url=url, status="skipped", skip_reason="external url"), []

        parsed_path = urlparse(url).path
        if _NOISE_URL_PATTERNS.search(parsed_path):
            return PageResult(url=url, status="skipped", skip_reason="noise-url"), []
        if _NOISE_QUERY_PARAMS.search(url):
            return PageResult(url=url, status="skipped", skip_reason="noise-url"), []
        if _CALENDAR_DATE_PATH.search(parsed_path):
            return PageResult(url=url, status="skipped", skip_reason="calendar-date"), []
        if self.snooper.is_disallowed(url) and not self.ignore_robots_exclusions:
            return PageResult(url=url, status="skipped", skip_reason="robots disallowed"), []

        probe_result = await asyncio.to_thread(self.engine_router.probe, url)
        primary = "crawl4ai" if probe_result.primary_engine == "crawl4ai" else "static"
        fallback = "static" if primary == "crawl4ai" else "crawl4ai"

        for engine_name in (primary, fallback):
            candidate, links = await self._run_engine(engine_name, url)
            if candidate.status != "success":
                continue
            if self.snooper.has_noindex(candidate.raw_html):
                return PageResult(url=url, status="skipped", skip_reason="noindex"), []
            if self._is_login_redirect(candidate):
                return PageResult(url=url, status="skipped", skip_reason="login-redirect"), []
            return candidate, links

        return PageResult(url=url, status="failed", skip_reason="all engines failed"), []

    async def _run_engine(self, engine_name: str, url: str) -> tuple[PageResult, list[str]]:
        if engine_name == "crawl4ai":
            return await self.browser.scrape(url)
        result = await asyncio.to_thread(self.static.scrape, url)
        links = self._extract_links(result.raw_html, url) if result.status == "success" else []
        return result, links

    def _extract_links(self, html: str, source_url: str) -> list[str]:
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absolute = urldefrag(urljoin(source_url, href)).url
            parsed = urlparse(absolute)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                links.append(absolute)
        return links

    def _is_login_redirect(self, result: PageResult) -> bool:
        title = result.title.lower() if result.title else ""
        if _LOGIN_PATTERNS.search(title):
            return True
        return bool(_LOGIN_PATTERNS.search((result.markdown or "")[:500]))
