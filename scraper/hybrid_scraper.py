# scraper/hybrid_scraper.py
import asyncio
import re as _re
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path as _Path
from typing import AsyncGenerator
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from models import PageResult
from scraper.crawl4ai_engine import Crawl4AIEngine
from scraper.page_probe import EngineRouter
from scraper.scrapy_engine import ScrapyEngine
from scraper.queue_manager import QueueManager
from scraper.snooper import Snooper
from scraper.page_processor import PageProcessor
from scraper.pipeline_db import PipelineDB
from scraper.static_engine import StaticEngine

_NOISE_URL_PATTERNS = re.compile(
    r"/(privacy|terms|cookie|legal|sitemap|gdpr|disclaimer|imprint|impressum)",
    re.IGNORECASE,
)

# Calendar/download URL noise: query params that trigger file downloads or
# generate hundreds of near-identical paginated calendar views
_NOISE_QUERY_PARAMS = re.compile(
    r"[?&](ical|outlook-ical|tribe-bar-date)=",
    re.IGNORECASE,
)

# Calendar date path segments: /day/YYYY-MM-DD, /week/YYYY-MM-DD, /month/YYYY-MM
_CALENDAR_DATE_PATH = re.compile(
    r"/(day|week|month|year)/\d{4}-\d{2}",
    re.IGNORECASE,
)

_LOGIN_PATTERNS = re.compile(
    r"\b(sign\s*in|log\s*in|login|sign\s*up|create\s+account|please\s+authenticate)\b",
    re.IGNORECASE,
)

_RAW_DIR = _Path("data/raw")


def _safe_filename(url: str) -> str:
    """Convert URL to a safe filename."""
    # Remove scheme
    name = _re.sub(r"^https?://", "", url)
    # Replace non-alphanumeric chars with underscore
    name = _re.sub(r"[^a-zA-Z0-9_\-.]", "_", name)
    # Truncate to 200 chars
    return name[:200] + ".md"


class HybridScraper:
    """Async generator: Crawl4AI primary → Scrapy fallback per URL."""

    def __init__(self, queue: QueueManager, snooper: Snooper,
                 max_pages: int = 500, cancel_flag: list | None = None,
                 ignore_robots_exclusions: bool = False,
                 persist_raw_markdown: bool = True,
                 keep_duplicate_pages: bool = False,
                 engine_router: EngineRouter | None = None,
                 enable_static_salvage: bool = False):
        self.queue = queue
        self.snooper = snooper
        self.max_pages = max_pages
        self.cancel_flag = cancel_flag or []  # set cancel_flag.append(True) to stop
        self.ignore_robots_exclusions = ignore_robots_exclusions
        self.persist_raw_markdown = persist_raw_markdown
        self.keep_duplicate_pages = keep_duplicate_pages
        self.enable_static_salvage = enable_static_salvage
        self._processor = PageProcessor()
        self._primary = Crawl4AIEngine()
        self._fallback = ScrapyEngine()
        self._static = StaticEngine()
        self._engine_router = engine_router
        self._pages_done = 0
        self._pipeline_db = PipelineDB()

    def _is_login_redirect(self, result: PageResult) -> bool:
        """True if the page looks like a login wall (200 OK but requires auth)."""
        title = result.title.lower() if result.title else ""
        # Check title first (fast path)
        if _LOGIN_PATTERNS.search(title):
            return True
        # Check first 500 chars of markdown (avoid scanning whole document)
        snippet = (result.markdown or "")[:500]
        return bool(_LOGIN_PATTERNS.search(snippet))

    def _save_to_disk(self, result: PageResult) -> None:
        """Save a successful scraped page to data/raw/ for the Clean step."""
        try:
            _RAW_DIR.mkdir(parents=True, exist_ok=True)
            filename = _safe_filename(result.url)
            (_RAW_DIR / filename).write_text(result.markdown, encoding="utf-8")
        except Exception:
            pass  # disk write failure doesn't fail the crawl

    async def crawl(self, start_url: str) -> AsyncGenerator[PageResult, None]:
        self.queue.enqueue(start_url)
        while True:
            if self.cancel_flag:
                break  # cancelled — don't mark completed, user may want to resume

            if self._pages_done >= self.max_pages:
                self.queue.mark_completed()  # hit the page cap — done
                break

            url = self.queue.dequeue()
            if url is None:
                self.queue.mark_completed()  # queue drained — done
                break

            result = await self._scrape_with_retry(url)

            # External URLs are saved to Redis but NOT yielded as results
            if result.status == "skipped" and result.skip_reason == "external url":
                continue

            if result.status == "success":
                content_hash = self.queue.content_hash(result.markdown)   # hash BEFORE YAML injection
                if self.queue.is_duplicate_content(content_hash):
                    if self.keep_duplicate_pages:
                        result.skip_reason = "duplicate-content"
                        result = self._processor.process(result)
                    else:
                        result.status = "skipped"
                        result.skip_reason = "duplicate-content"
                else:
                    self.queue.add_content_hash(content_hash)
                    result = self._processor.process(result)              # process only non-duplicates

            # Mark as actually scraped (two-set dedup: enqueued ≠ visited)
            if result.status in ("success", "failed"):
                self.queue.mark_visited(url)

            self._pages_done += 1
            self.queue.update_meta(
                pages_done=self._pages_done,
                total_words=int(self.queue.get_meta().get("total_words", 0)) + result.word_count,
            )
            self.queue.log(self._format_log(result))

            if result.status == "success":
                self.queue.save_result(result)   # persist for resume recovery
                if self.persist_raw_markdown:
                    self._save_to_disk(result)
                self._pipeline_db.upsert_scraped(
                    url=result.url,
                    domain=self.queue.domain,
                    page_type=result.page_type,
                    word_count=result.word_count,
                    scraped_at=result.scraped_at.isoformat(),
                )

            yield result

            if self.snooper.crawl_delay > 0:
                await asyncio.sleep(self.snooper.crawl_delay)

    async def _scrape_with_retry(self, url: str) -> PageResult:
        """Scrape URL with up to 3 attempts, exponential backoff on failure (2/4/8s)."""
        delays = [2, 4, 8]
        result = PageResult(url=url, status="failed", skip_reason="not attempted")
        for attempt, delay in enumerate(delays, start=1):
            result = await self._scrape_url(url)
            if result.status != "failed":
                return result
            if attempt < len(delays):
                await asyncio.sleep(delay)
        return result

    async def _scrape_url(self, url: str) -> PageResult:
        # Pre-flight checks
        if self.snooper.is_external(url):
            self.queue.save_external(url)
            return PageResult(url=url, status="skipped", skip_reason="external url")
        parsed_path = urlparse(url).path
        if _NOISE_URL_PATTERNS.search(parsed_path):
            return PageResult(url=url, status="skipped", skip_reason="noise-url")
        if _NOISE_QUERY_PARAMS.search(url):
            return PageResult(url=url, status="skipped", skip_reason="noise-url")
        if _CALENDAR_DATE_PATH.search(parsed_path):
            return PageResult(url=url, status="skipped", skip_reason="calendar-date")
        if self.snooper.is_disallowed(url) and not self.ignore_robots_exclusions:
            result, links = await self._run_scrapy(url)
            if result.status == "success":
                result.skip_reason = "scrapy (robots-disallowed)"
                if self.snooper.has_noindex(result.raw_html):
                    return PageResult(url=url, status="skipped", skip_reason="noindex")
                if self._is_login_redirect(result):
                    return PageResult(url=url, status="skipped", skip_reason="login-redirect")
                if not self.snooper.has_nofollow(result.raw_html):
                    self._enqueue_links(links, url)
                return result
            if result.status == "failed":
                self.queue.mark_failed(url)
            if "robots" not in result.skip_reason:
                result.skip_reason = (
                    f"{result.skip_reason}; scrapy (robots-disallowed)"
                    if result.skip_reason else "scrapy (robots-disallowed)"
                )
            return result

        probe_result = None
        if self._engine_router is not None:
            probe_result = await asyncio.to_thread(self._engine_router.probe, url)

        order = ["crawl4ai", "scrapy"]
        if probe_result and probe_result.primary_engine == "scrapy":
            order = ["scrapy", "crawl4ai"]

        for engine in order:
            if engine == "crawl4ai":
                candidate, links = await self._primary.scrape(url)
            else:
                candidate, links = await self._run_scrapy(url)

            if candidate.status != "success":
                continue

            if probe_result is not None:
                candidate.engine_used = engine

            if self.snooper.has_noindex(candidate.raw_html):
                return PageResult(url=url, status="skipped", skip_reason="noindex")
            if self._is_login_redirect(candidate):
                return PageResult(url=url, status="skipped", skip_reason="login-redirect")
            if not self.snooper.has_nofollow(candidate.raw_html):
                self._enqueue_links(links, url)
            return candidate

        if self.enable_static_salvage:
            salvage = await asyncio.to_thread(self._static.scrape, url)
            if salvage.status == "success":
                if self.snooper.has_noindex(salvage.raw_html):
                    return PageResult(url=url, status="skipped", skip_reason="noindex")
                if self._is_login_redirect(salvage):
                    return PageResult(url=url, status="skipped", skip_reason="login-redirect")
                links = self._extract_links(salvage.raw_html, url)
                if not self.snooper.has_nofollow(salvage.raw_html):
                    self._enqueue_links(links, url)
                return salvage

        # Both failed
        self.queue.mark_failed(url)
        return PageResult(url=url, status="failed", skip_reason="both engines failed")

    def _enqueue_links(self, links: list[str], source_url: str) -> None:
        for link in links:
            if not self.snooper.is_external(link):
                self.queue.enqueue(link)
        self.queue.update_meta(pages_found=self.queue._r.scard(
            self.queue._keys["enqueued"]  # count discovered URLs, not scraped
        ))

    async def _run_scrapy(self, url: str) -> tuple[PageResult, list[str]]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._scrape_with_scrapy, url)

    def _scrape_with_scrapy(self, url: str) -> tuple[PageResult, list[str]]:
        result = self._fallback.scrape(url)
        if not isinstance(result, PageResult):
            return PageResult(url=url, status="skipped", skip_reason="robots disallowed"), []
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

    def _format_log(self, result: PageResult) -> str:
        if result.status == "success":
            tag = "[WARN]" if result.engine_used == "scrapy" else "[OK]  "
            return f"{tag} {result.url} [{result.engine_used}] {result.word_count}w"
        elif result.status == "skipped":
            return f"[SKIP] {result.url}  {result.skip_reason}"
        else:
            return f"[FAIL] {result.url}  {result.skip_reason}"
