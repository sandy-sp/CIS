from __future__ import annotations

import hashlib
import re
from collections import Counter

import html2text
from bs4 import BeautifulSoup

from company_intel.models import PageRecord


_STRIP_SELECTORS = (
    "nav",
    "footer",
    "header",
    "script",
    "style",
    "noscript",
    "iframe",
    "form",
    ".cookie-banner",
    "#cookie-notice",
    ".cookie-notice",
    ".newsletter-signup",
)

_IMAGE_LINE = re.compile(r"^\s*!\[.*\]\(.*\)\s*$")
_LINK_ONLY = re.compile(r"^\s*[\*\-\+]\s*\[[^\]]+\]\([^)]+\)\s*$")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _markdown_to_text(markdown: str) -> str:
    text = _MARKDOWN_LINK.sub(r"\1", markdown)
    text = re.sub(r"^[#>\-\*\+\d\.\s]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"`{1,3}", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class CorpusCleaner:
    def __init__(self):
        self._converter = html2text.HTML2Text()
        self._converter.ignore_images = True
        self._converter.body_width = 0
        self._converter.unicode_snob = True

    def clean_record(self, record: PageRecord) -> PageRecord:
        html = record.raw_html or ""
        markdown = record.markdown or ""
        if html:
            soup = BeautifulSoup(html, "html.parser")
            for selector in _STRIP_SELECTORS:
                for tag in soup.select(selector):
                    tag.decompose()
            markdown = self._converter.handle(str(soup)).strip()
        markdown = self._strip_noise(markdown)
        record.markdown = markdown
        record.clean_text = _markdown_to_text(markdown)
        record.raw_text = record.raw_text or _markdown_to_text(record.markdown)
        record.word_count = len(record.clean_text.split()) if record.clean_text else 0
        record.content_hash = hashlib.sha256(record.clean_text.lower().encode("utf-8")).hexdigest() if record.clean_text else ""
        record.is_noise = record.page_category == "legal" or record.word_count < 15
        return record

    def remove_template_lines(self, records: list[PageRecord], ratio: float = 0.35) -> list[PageRecord]:
        docs = [record for record in records if record.markdown]
        if not docs:
            return records
        threshold = max(2, int(len(docs) * ratio))
        counts: Counter[str] = Counter()
        line_map: dict[str, str] = {}
        for record in docs:
            seen: set[str] = set()
            for line in record.markdown.splitlines():
                norm = self._normalize_line(line)
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                counts[norm] += 1
                line_map.setdefault(norm, line.strip())

        repeated = {
            norm: line_map[norm]
            for norm, count in counts.items()
            if count >= threshold and self._is_repetitive_boilerplate(line_map[norm])
        }
        if not repeated:
            return records

        for record in records:
            removed: list[str] = []
            kept: list[str] = []
            for line in record.markdown.splitlines():
                norm = self._normalize_line(line)
                if norm and norm in repeated:
                    removed.append(repeated[norm])
                    continue
                kept.append(line)
            if removed:
                record.boilerplate_blocks_removed = sorted(set(record.boilerplate_blocks_removed + removed))
                record.markdown = "\n".join(kept).strip()
                record.clean_text = _markdown_to_text(record.markdown)
                record.word_count = len(record.clean_text.split()) if record.clean_text else 0
                record.content_hash = hashlib.sha256(record.clean_text.lower().encode("utf-8")).hexdigest() if record.clean_text else ""
        return records

    def mark_duplicates(self, records: list[PageRecord]) -> list[PageRecord]:
        seen: dict[str, str] = {}
        for record in records:
            if not record.content_hash:
                continue
            canonical = seen.get(record.content_hash)
            if canonical:
                record.is_duplicate = True
                record.canonical_page_id = canonical
            else:
                seen[record.content_hash] = record.normalized_url
        return records

    def _strip_noise(self, markdown: str) -> str:
        lines = []
        for line in markdown.splitlines():
            if _IMAGE_LINE.match(line):
                continue
            if _LINK_ONLY.match(line):
                continue
            lines.append(line.rstrip())
        return "\n".join(lines).strip()

    def _normalize_line(self, line: str) -> str:
        line = line.strip()
        line = _MARKDOWN_LINK.sub(r"\1", line)
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r"^[#>\-\*\+\d\.\s]+", "", line)
        return line.strip().lower()

    def _is_repetitive_boilerplate(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if len(stripped) > 120:
            return False
        if stripped.startswith("http"):
            return True
        keywords = ("contact", "privacy", "terms", "services", "industries", "about", "careers", "linkedin", "facebook")
        return any(keyword in stripped.lower() for keyword in keywords)
