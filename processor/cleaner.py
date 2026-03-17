# processor/cleaner.py
"""
Cleans scraped Markdown/HTML content using Trafilatura.

Input: Either raw HTML string OR Markdown string with optional YAML frontmatter.
Output: CleanResult with clean_text (plain text for RAG) and metadata preserved.
"""
import re
from dataclasses import dataclass
from typing import Optional

import trafilatura
import yaml


@dataclass
class CleanResult:
    url: str
    title: str
    page_type: str
    clean_text: str         # clean plain text, ready for chunking
    word_count: int
    original_word_count: int
    is_high_noise: bool     # True if >80% of content was stripped
    skip_reason: str = ""   # non-empty if page should be skipped


# URL patterns to skip entirely (legal/cookie/sitemap noise)
_SKIP_URL_PATTERNS = re.compile(
    r"/(privacy|terms|cookie|legal|sitemap|gdpr|disclaimer|imprint|impressum)",
    re.IGNORECASE,
)

# Minimum word count after cleaning (below this = empty nav page)
_MIN_WORDS = 50


class Cleaner:
    """Cleans scraped content using Trafilatura for RAG-quality text extraction."""

    def clean_html(self, html: str, url: str = "", title: str = "",
                   page_type: str = "other") -> CleanResult:
        """Clean raw HTML string using Trafilatura."""
        original_word_count = len(html.split())

        # Skip high-noise URL patterns
        if url and _SKIP_URL_PATTERNS.search(url):
            return CleanResult(
                url=url, title=title, page_type=page_type,
                clean_text="", word_count=0,
                original_word_count=original_word_count,
                is_high_noise=True,
                skip_reason="noise-url",
            )

        # Use trafilatura to extract clean text
        clean_text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_precision=True,
        ) or ""

        clean_text = clean_text.strip()
        word_count = len(clean_text.split()) if clean_text else 0

        # Skip pages with too little content
        if word_count < _MIN_WORDS:
            return CleanResult(
                url=url, title=title, page_type=page_type,
                clean_text=clean_text, word_count=word_count,
                original_word_count=original_word_count,
                is_high_noise=True,
                skip_reason="too-short",
            )

        # Flag high-noise pages (>80% content stripped)
        html_word_count = len(re.sub(r"<[^>]+>", " ", html).split())
        is_high_noise = html_word_count > 0 and (word_count / html_word_count) < 0.2

        return CleanResult(
            url=url, title=title, page_type=page_type,
            clean_text=clean_text, word_count=word_count,
            original_word_count=html_word_count,
            is_high_noise=is_high_noise,
        )

    def clean_markdown_file(self, content: str) -> CleanResult:
        """
        Process a Markdown file (with optional YAML frontmatter).
        Extracts metadata from frontmatter, then cleans the markdown body.
        Returns a CleanResult with metadata from frontmatter.
        """
        url, title, page_type, markdown_body = self._parse_frontmatter(content)

        # Skip by URL pattern
        if url and _SKIP_URL_PATTERNS.search(url):
            return CleanResult(
                url=url, title=title, page_type=page_type,
                clean_text="", word_count=0,
                original_word_count=len(markdown_body.split()),
                is_high_noise=True,
                skip_reason="noise-url",
            )

        original_word_count = len(markdown_body.split())

        # For Markdown input, use trafilatura on the markdown text itself
        # Trafilatura handles markdown if we wrap in minimal HTML
        html_wrapped = f"<html><body>{markdown_body}</body></html>"
        clean_text = trafilatura.extract(
            html_wrapped,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_precision=False,  # less aggressive for markdown
        ) or markdown_body.strip()  # fallback: use original markdown body

        clean_text = clean_text.strip()
        word_count = len(clean_text.split()) if clean_text else 0

        if word_count < _MIN_WORDS:
            return CleanResult(
                url=url, title=title, page_type=page_type,
                clean_text=clean_text, word_count=word_count,
                original_word_count=original_word_count,
                is_high_noise=True,
                skip_reason="too-short",
            )

        is_high_noise = original_word_count > 0 and (word_count / original_word_count) < 0.2

        return CleanResult(
            url=url, title=title, page_type=page_type,
            clean_text=clean_text, word_count=word_count,
            original_word_count=original_word_count,
            is_high_noise=is_high_noise,
        )

    def _parse_frontmatter(self, content: str) -> tuple[str, str, str, str]:
        """Extract url, title, page_type from YAML frontmatter. Returns (url, title, page_type, body)."""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1]) or {}
                    body = parts[2].strip()
                    return (
                        meta.get("url", ""),
                        meta.get("title", ""),
                        meta.get("page_type", "other"),
                        body,
                    )
                except yaml.YAMLError:
                    pass
        return "", "", "other", content
