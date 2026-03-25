# scraper/crawl4ai_engine.py
import asyncio
import re

from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from models import PageResult

_SCRAPE_TIMEOUT = 30  # seconds
_WORD_COUNT_THRESHOLD = 50  # pages with fewer words are likely nav/boilerplate


class Crawl4AIEngine:
    """Primary scraping engine using Crawl4AI + Playwright."""

    USER_AGENT = "Business-Scraper/1.0"
    _DISABLE_PATTERNS = (
        re.compile(r"cannot find module .+playwright/.+cli\.js", re.IGNORECASE),
        re.compile(r"connection closed while reading from the driver", re.IGNORECASE),
        re.compile(r"playwright.+not found", re.IGNORECASE),
    )

    async def scrape(self, url: str) -> tuple[PageResult, list[str]]:
        """
        Scrape a single URL.
        Returns (PageResult, list_of_internal_links).
        PageResult.status == 'failed' if scrape unsuccessful or empty.
        """
        result = PageResult(url=url, engine_used="crawl4ai")
        links: list[str] = []
        disabled_reason = getattr(self, "_disabled_reason", "")
        if disabled_reason:
            result.status = "failed"
            result.skip_reason = f"crawl4ai unavailable: {disabled_reason}"
            return result, links

        try:
            browser_config = BrowserConfig(
                user_agent=self.USER_AGENT,
                headless=True,
                verbose=False,
            )
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.DISABLED,
                word_count_threshold=_WORD_COUNT_THRESHOLD,
                markdown_generator=DefaultMarkdownGenerator(
                    content_filter=PruningContentFilter(),
                    options={"fit_markdown": True},
                ),
            )
            async with AsyncWebCrawler(config=browser_config) as crawler:
                crawl_result = await asyncio.wait_for(
                    crawler.arun(url=url, config=run_config),
                    timeout=_SCRAPE_TIMEOUT,
                )

            if not crawl_result.success:
                result.status = "failed"
                result.skip_reason = f"crawl4ai error: {getattr(crawl_result, 'error_message', 'unknown')}"
                return result, links

            if not crawl_result.markdown or not crawl_result.markdown.strip():
                result.status = "failed"
                result.skip_reason = "crawl4ai empty"
                return result, links

            meta = crawl_result.metadata or {}
            result.status_code = int(
                getattr(crawl_result, "status_code", 0)
                or getattr(crawl_result, "response_status_code", 0)
                or 0
            )
            result.title = meta.get("title", "")
            result.description = meta.get("description", "")
            result.language = meta.get("language", "")
            result.canonical_url = meta.get("canonical", "") or url
            result.raw_html = crawl_result.cleaned_html or ""
            result.markdown = crawl_result.markdown
            result.status = "success"

            internal = crawl_result.links.get("internal", [])
            links = [lnk["href"] for lnk in internal if lnk.get("href", "").startswith("http")]

        except asyncio.TimeoutError:
            result.status = "failed"
            result.skip_reason = "crawl4ai timeout"
        except Exception as exc:
            if self._is_driver_unavailable_error(exc):
                self._disabled_reason = "playwright driver unavailable"
                result.status = "failed"
                result.skip_reason = f"crawl4ai unavailable: {self._disabled_reason}"
                return result, links
            result.status = "failed"
            result.skip_reason = f"crawl4ai error: {exc}"

        return result, links

    def _is_driver_unavailable_error(self, exc: Exception) -> bool:
        message = str(exc or "")
        return any(pattern.search(message) for pattern in self._DISABLE_PATTERNS)
