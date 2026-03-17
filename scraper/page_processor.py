# scraper/page_processor.py
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import yaml
from bs4 import BeautifulSoup

from models import PageResult

# page_type patterns: (regex, page_type) in priority order
_PAGE_TYPE_PATTERNS = [
    (r"^/$", "homepage"),
    (r"/(about|team|who-we-are|our-story|company|our-team)", "about"),
    (r"/(service|solution|what-we-do|offering|product|our-solution)", "services"),
    (r"/(blog|news|insight|article|post|update)", "blog"),
    (r"/(case-stud|work|portfolio|project|client)", "case-study"),
    (r"/(contact|get-in-touch|reach-us)", "contact"),
]


class PageProcessor:
    """Injects YAML frontmatter, detects page_type, extracts headings, calculates word count."""

    def process(self, result: PageResult) -> PageResult:
        """Enrich a PageResult with frontmatter, page_type, headings, word_count."""
        result.page_type = self.detect_page_type(result.url)
        result.headings = self.extract_headings(result.raw_html)
        result.word_count = self.count_words(result.markdown)

        frontmatter = self._build_frontmatter(result)
        result.markdown = f"---\n{frontmatter}---\n\n{result.markdown}"
        return result

    def detect_page_type(self, url: str) -> str:
        path = urlparse(url).path.lower()
        for pattern, page_type in _PAGE_TYPE_PATTERNS:
            if re.search(pattern, path, re.IGNORECASE):
                return page_type
        return "other"

    def extract_headings(self, html: str) -> list[dict]:
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        headings = []
        for tag in soup.find_all(["h1", "h2"]):
            text = tag.get_text(strip=True)
            if text:
                headings.append({tag.name: text})
        return headings

    def count_words(self, text: str) -> int:
        return len(text.split()) if text.strip() else 0

    def _build_frontmatter(self, result: PageResult) -> str:
        data = {
            "url": result.url,
            "canonical_url": result.canonical_url or result.url,
            "title": result.title,
            "description": result.description,
            "language": result.language,
            "page_type": result.page_type,
            "domain": urlparse(result.url).netloc,
            "scraped_at": result.scraped_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "word_count": result.word_count,
            "engine_used": result.engine_used,
            "headings": result.headings,
        }
        return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
