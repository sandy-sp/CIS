import io
import re
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlparse

from models import PageResult

_PAGE_TYPE_ORDER = ["homepage", "about", "services", "blog", "case-study", "contact", "other"]


class Exporter:
    """Builds the output .zip with individual pages, master_site.md, reports."""

    def __init__(self, domain: str):
        self.domain = domain

    def build_zip(
        self,
        pages: list[PageResult],
        external_links: dict[str, list[str]],
        crawl_duration_seconds: float = 0.0,
    ) -> bytes:
        buf = io.BytesIO()
        successful = [p for p in pages if p.status == "success"]
        failed = [p for p in pages if p.status == "failed"]
        skipped = [p for p in pages if p.status == "skipped"]

        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        prefix = f"{self.domain}-{date_str}"

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Individual pages — track slug counts to avoid silent overwrite on collision
            slug_counts: dict[str, int] = {}
            for page in successful:
                base_slug = self.slugify(page.url)
                if base_slug in slug_counts:
                    slug_counts[base_slug] += 1
                    slug = f"{base_slug}-{slug_counts[base_slug]}"
                else:
                    slug_counts[base_slug] = 0
                    slug = base_slug
                zf.writestr(f"{prefix}/individual_pages/{slug}.md", page.markdown)

            # master_site.md (sorted by page_type)
            sorted_pages = sorted(
                successful,
                key=lambda p: (_PAGE_TYPE_ORDER.index(p.page_type)
                               if p.page_type in _PAGE_TYPE_ORDER else 99, p.url)
            )
            if sorted_pages:
                master = "\n\n---\n\n".join(p.markdown for p in sorted_pages)
            else:
                master = f"# {self.domain}\n\nNo pages were successfully scraped.\n"
            zf.writestr(f"{prefix}/master_site.md", master)

            # external_links.md
            zf.writestr(f"{prefix}/external_links.md", self._build_external_links(external_links))

            # crawl_report.md
            zf.writestr(
                f"{prefix}/crawl_report.md",
                self._build_report(successful, failed, skipped, crawl_duration_seconds),
            )

        return buf.getvalue()

    def slugify(self, url: str) -> str:
        path = urlparse(url).path.strip("/")
        if not path:
            return "homepage"
        slug = re.sub(r"[^a-zA-Z0-9/-]", "", path)
        slug = slug.replace("/", "-").strip("-")
        return slug or "page"

    def _build_external_links(self, external_links: dict[str, list[str]]) -> str:
        if not external_links:
            return "# External Links\n\nNo external links found.\n"
        lines = ["# External Links\n"]
        for domain, urls in sorted(external_links.items()):
            lines.append(f"\n## {domain}\n")
            for url in urls:
                lines.append(f"- [{url}]({url})")
        return "\n".join(lines)

    def _build_report(
        self,
        successful: list[PageResult],
        failed: list[PageResult],
        skipped: list[PageResult],
        duration: float,
    ) -> str:
        total_words = sum(p.word_count for p in successful)
        crawl4ai_count = sum(1 for p in successful if p.engine_used == "crawl4ai")
        scrapy_count = sum(1 for p in successful if p.engine_used == "scrapy")

        skip_reasons: dict[str, int] = {}
        for p in skipped:
            skip_reasons[p.skip_reason] = skip_reasons.get(p.skip_reason, 0) + 1

        lines = [
            "# Crawl Report",
            "",
            f"**Domain:** {self.domain}",
            f"**Duration:** {duration:.1f}s",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|---|---|",
            f"| Pages scraped | {len(successful)} |",
            f"| Pages failed | {len(failed)} |",
            f"| Pages skipped | {len(skipped)} |",
            f"| Total word count | {total_words:,} |",
            f"| Crawl4AI | {crawl4ai_count} |",
            f"| Scrapy fallback | {scrapy_count} |",
            "",
            "## Skip Reasons",
            "",
        ]
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            lines.append(f"- {reason}: {count}")

        if failed:
            lines += ["", "## Failed URLs", ""]
            for p in failed:
                lines.append(f"- {p.url} ({p.skip_reason})")

        return "\n".join(lines)
