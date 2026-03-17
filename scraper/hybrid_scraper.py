# scraper/hybrid_scraper.py
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator

from models import PageResult
from scraper.crawl4ai_engine import Crawl4AIEngine
from scraper.scrapy_engine import ScrapyEngine
from scraper.queue_manager import QueueManager
from scraper.snooper import Snooper
from scraper.page_processor import PageProcessor

_MAX_DEPTH = 10


class HybridScraper:
    """Async generator: Crawl4AI primary → Scrapy fallback per URL."""

    def __init__(self, queue: QueueManager, snooper: Snooper,
                 max_pages: int = 500, cancel_flag: list | None = None):
        self.queue = queue
        self.snooper = snooper
        self.max_pages = max_pages
        self.cancel_flag = cancel_flag or []  # set cancel_flag.append(True) to stop
        self._processor = PageProcessor()
        self._primary = Crawl4AIEngine()
        self._fallback = ScrapyEngine()
        self._pages_done = 0

    async def crawl(self, start_url: str) -> AsyncGenerator[PageResult, None]:
        with ThreadPoolExecutor(max_workers=1) as pool:
            while True:
                if self.cancel_flag:
                    break
                if self._pages_done >= self.max_pages:
                    break

                url = self.queue.dequeue()
                if url is None:
                    break

                result = await self._scrape_url(url, pool)

                # External URLs are saved to Redis but NOT yielded as results
                if result.status == "skipped" and result.skip_reason == "external url":
                    continue

                if result.status == "success":
                    result = self._processor.process(result)
                    content_hash = self.queue.content_hash(result.markdown)
                    if self.queue.is_duplicate_content(content_hash):
                        result.skip_reason = "duplicate-content"
                    else:
                        self.queue.add_content_hash(content_hash)

                # Mark as actually scraped (two-set dedup: enqueued ≠ visited)
                if result.status in ("success", "failed"):
                    self.queue.mark_visited(url)

                self._pages_done += 1
                self.queue.update_meta(
                    pages_done=self._pages_done,
                    total_words=int(self.queue.get_meta().get("total_words", 0)) + result.word_count,
                )
                self.queue.log(self._format_log(result))

                yield result

                if self.snooper.crawl_delay > 0:
                    await asyncio.sleep(self.snooper.crawl_delay)

    async def _scrape_url(self, url: str, pool: ThreadPoolExecutor) -> PageResult:
        # Pre-flight checks
        if self.snooper.is_disallowed(url):
            return PageResult(url=url, status="skipped", skip_reason="robots disallowed")
        if self.snooper.is_external(url):
            self.queue.save_external(url)
            return PageResult(url=url, status="skipped", skip_reason="external url")

        # Primary: Crawl4AI
        result, links = await self._primary.scrape(url)

        if result.status == "success":
            if self.snooper.has_noindex(result.raw_html):
                return PageResult(url=url, status="skipped", skip_reason="noindex")
            if not self.snooper.has_nofollow(result.raw_html):
                self._enqueue_links(links, url)
            return result

        # Fallback: Scrapy (blocking, in thread)
        loop = asyncio.get_running_loop()
        fallback = await loop.run_in_executor(pool, self._fallback.scrape, url)
        if fallback.status == "success":
            if self.snooper.has_noindex(fallback.raw_html):
                return PageResult(url=url, status="skipped", skip_reason="noindex")
            return fallback

        # Both failed
        self.queue.mark_failed(url)
        return PageResult(url=url, status="failed", skip_reason="both engines failed")

    def _enqueue_links(self, links: list[str], source_url: str) -> None:
        for link in links:
            if not self.snooper.is_external(link) and not self.snooper.is_disallowed(link):
                self.queue.enqueue(link)
        self.queue.update_meta(pages_found=self.queue._r.scard(
            self.queue._keys["enqueued"]  # count discovered URLs, not scraped
        ))

    def _format_log(self, result: PageResult) -> str:
        if result.status == "success":
            tag = "[WARN]" if result.engine_used == "scrapy" else "[OK]  "
            return f"{tag} {result.url} [{result.engine_used}] {result.word_count}w"
        elif result.status == "skipped":
            return f"[SKIP] {result.url}  {result.skip_reason}"
        else:
            return f"[FAIL] {result.url}  {result.skip_reason}"
