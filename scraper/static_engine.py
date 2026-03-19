from __future__ import annotations

import requests
import html2text
from bs4 import BeautifulSoup

from models import PageResult


class StaticEngine:
    USER_AGENT = "Business-Scraper/1.0"

    def scrape(self, url: str) -> PageResult:
        result = PageResult(url=url, engine_used="static")
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=20,
            )
        except requests.RequestException as exc:
            result.status = "failed"
            result.skip_reason = f"static error: {exc}"
            return result

        if resp.status_code >= 400:
            result.status = "failed"
            result.skip_reason = f"static http {resp.status_code}"
            return result

        soup = BeautifulSoup(resp.text, "html.parser")
        for selector in ("nav", "footer", "header", "script", "style", "noscript"):
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
            result.skip_reason = "static empty"
            return result

        result.title = (soup.title.get_text(strip=True) if soup.title else "")
        result.description = (
            soup.find("meta", attrs={"name": "description"}).get("content", "").strip()
            if soup.find("meta", attrs={"name": "description"})
            else ""
        )
        canonical_tag = soup.find("link", attrs={"rel": "canonical"})
        result.canonical_url = canonical_tag.get("href", "").strip() if canonical_tag else url
        html_tag = soup.find("html")
        result.language = html_tag.get("lang", "").strip() if html_tag else ""
        result.raw_html = clean_html
        result.markdown = markdown
        result.status = "success"
        return result
