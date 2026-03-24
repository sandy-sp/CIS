from __future__ import annotations

from urllib.parse import urljoin

import html2text
from bs4 import BeautifulSoup

from models import PageResult


class ScraplingEngine:
    USER_AGENT = "Business-Scraper/1.0"

    def scrape(self, url: str) -> PageResult:
        result = PageResult(url=url, engine_used="scrapling")

        try:
            from scrapling.fetchers import Fetcher
        except ImportError:
            result.status = "failed"
            result.skip_reason = "scrapling unavailable: dependency not installed"
            return result

        try:
            page = Fetcher.get(
                url,
                follow_redirects=True,
                stealthy_headers=True,
                impersonate="chrome",
                headers={"User-Agent": self.USER_AGENT},
            )
        except Exception as exc:
            result.status = "failed"
            result.skip_reason = f"scrapling error: {exc}"
            return result

        status_code = int(getattr(page, "status", 0) or 0)
        if status_code >= 400:
            result.status = "failed"
            result.skip_reason = f"scrapling http {status_code}"
            return result

        html = self._extract_html(page)
        if not html.strip():
            result.status = "failed"
            result.skip_reason = "scrapling empty"
            return result

        soup = BeautifulSoup(html, "html.parser")
        for selector in ("script", "style", "noscript"):
            for tag in soup.select(selector):
                tag.decompose()

        converter = html2text.HTML2Text()
        converter.ignore_images = True
        converter.body_width = 0
        converter.unicode_snob = True

        clean_html = str(soup)
        markdown = converter.handle(clean_html).strip()
        if not markdown:
            result.status = "failed"
            result.skip_reason = "scrapling empty"
            return result

        result.title = soup.title.get_text(strip=True) if soup.title else ""
        result.description = self._meta_content(soup, "description")
        canonical_url = self._canonical_url(soup, page, url)
        html_tag = soup.find("html")

        result.canonical_url = canonical_url
        result.language = html_tag.get("lang", "").strip() if html_tag else ""
        result.raw_html = clean_html
        result.markdown = markdown
        result.status = "success"
        return result

    def _extract_html(self, page: object) -> str:
        html = getattr(page, "html_content", "") or ""
        if isinstance(html, bytes):
            return html.decode("utf-8", errors="ignore")
        if html:
            return str(html)

        body = getattr(page, "body", b"")
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="ignore")
        return str(body or "")

    def _canonical_url(self, soup: BeautifulSoup, page: object, fallback_url: str) -> str:
        canonical_tag = soup.find("link", attrs={"rel": "canonical"})
        page_url = getattr(page, "url", "") or fallback_url
        if canonical_tag and canonical_tag.get("href"):
            return urljoin(page_url, canonical_tag.get("href", "").strip())
        return page_url

    def _meta_content(self, soup: BeautifulSoup, name: str) -> str:
        node = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": f"og:{name}"})
        if not node:
            return ""
        return node.get("content", "").strip()
