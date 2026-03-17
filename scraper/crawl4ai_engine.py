# scraper/crawl4ai_engine.py
import asyncio

from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from models import PageResult

_SCRAPE_TIMEOUT = 30  # seconds
_WORD_COUNT_THRESHOLD = 50  # pages with fewer words are likely nav/boilerplate


class Crawl4AIEngine:
    """Primary scraping engine using Crawl4AI + Playwright."""

    USER_AGENT = "Business-Scraper/1.0"

    async def scrape(self, url: str) -> tuple[PageResult, list[str]]:
        """
        Scrape a single URL.
        Returns (PageResult, list_of_internal_links).
        PageResult.status == 'failed' if scrape unsuccessful or empty.
        """
        result = PageResult(url=url, engine_used="crawl4ai")
        links: list[str] = []

        try:
            async with AsyncWebCrawler(
                user_agent=self.USER_AGENT,
                headless=True,
                verbose=False,
            ) as crawler:
                crawl_result = await asyncio.wait_for(
                    crawler.arun(
                        url=url,
                        cache_mode=CacheMode.DISABLED,
                        word_count_threshold=_WORD_COUNT_THRESHOLD,
                        content_filter=PruningContentFilter(),
                        markdown_generator=DefaultMarkdownGenerator(options={"fit_markdown": True}),
                    ),
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
            result.status = "failed"
            result.skip_reason = f"crawl4ai error: {exc}"

        return result, links
