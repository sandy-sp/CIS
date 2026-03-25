from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from company_intel.classifier import PageClassifier
from company_intel.cleaner import CorpusCleaner
from company_intel.exporter import IntelExporter
from company_intel.extractor import UniversalExtractor
from company_intel.models import CrawlJob, CrawlSettings, PageRecord
from company_intel.review import filter_records_for_outputs
from company_intel.storage import JobStorage
from scraper.page_probe import EngineRouter
from scraper.site_crawler import SiteCrawler
from scraper.snooper import Snooper


def _strip_frontmatter(markdown: str) -> str:
    if markdown.startswith("---"):
        parts = markdown.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return markdown.strip()


class JobRunner:
    def __init__(self, storage: JobStorage | None = None):
        self.storage = storage or JobStorage()
        self.classifier = PageClassifier()
        self.cleaner = CorpusCleaner()
        self.extractor = UniversalExtractor()
        self.exporter = IntelExporter()

    def create_job(self, settings: CrawlSettings) -> CrawlJob:
        return self.storage.create_job(settings)

    def resume_job(self, job_id: str) -> CrawlJob:
        job = self.storage.load_job(job_id)
        if job.status in {"discovering", "crawling", "processing"}:
            raise ValueError("This crawl is already active.")

        records = self.storage.load_page_records(job_id)
        self._prepare_resume(job, records)
        self.storage.clear_cancel_request(job_id)
        self.storage.clear_worker_pid(job_id)
        self.storage.save_job(job)
        return job

    def run(self, job_id: str) -> None:
        asyncio.run(self._run(job_id))

    async def _run(self, job_id: str) -> None:
        job = self.storage.load_job(job_id)
        self.storage.clear_cancel_request(job_id)
        resume_records = self.storage.load_page_records(job_id)
        visited_urls = [record.normalized_url or record.url for record in resume_records]
        is_resume = bool(resume_records) and job.status in {"failed", "cancelled"}

        try:
            if is_resume:
                self._prepare_resume(job, resume_records)
                self.storage.save_job(job)
                self.storage.append_crawl_log(job_id, {
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "level": "info",
                    "message": f"Resuming crawl from {len(resume_records)} saved pages",
                })

            job.status = "discovering"
            self.storage.save_job(job)

            snooper = Snooper(job.settings.start_url, default_delay=job.settings.rate_limit)
            snooper.load_robots()
            snooper.crawl_delay = max(job.settings.rate_limit, snooper.crawl_delay)
            seed_urls = snooper.get_discovery_urls()

            job.llm_txt_found = snooper.has_llm_txt
            job.robots_txt_found = snooper.has_robots_txt
            job.seed_count = len(seed_urls)
            job.seed_source = snooper.seed_source
            job.pages_total = len(seed_urls)
            if job.settings.ignore_robots_exclusions:
                job.warnings = sorted(set(job.warnings + ["robots.txt and llm.txt exclusions are ignored for crawling"]))
            crawl_seed_urls = self._build_crawl_seed_urls(job, seed_urls, resume_records)
            job.pages_total = max(job.pages_total, len(crawl_seed_urls), len(visited_urls))
            self.storage.save_job(job)
            self.storage.append_crawl_log(job_id, {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "level": "info",
                "message": f"Discovered {len(seed_urls)} seed URLs via {snooper.seed_source}",
            })

            job.status = "crawling"
            self.storage.save_job(job)
            crawler = SiteCrawler(
                snooper,
                max_pages=job.settings.max_pages,
                ignore_robots_exclusions=job.settings.ignore_robots_exclusions,
                rate_limit=snooper.crawl_delay,
                engine_router=EngineRouter(),
                visited_urls=visited_urls,
                processed_count=len(visited_urls),
            )

            async for result in crawler.crawl(
                crawl_seed_urls,
                cancel_requested=lambda: self.storage.cancel_requested(job_id),
            ):
                record = self._build_record(job, result)
                self.storage.save_page_record(job.job_id, record)
                job.pages_total = max(job.pages_total, crawler.discovered_count)
                self._update_job_counts(job, record)
                self.storage.save_job(job)
                self.storage.append_crawl_log(job_id, self._log_entry(record))

            if self.storage.cancel_requested(job_id):
                job.status = "cancelled"
                job.finished_at = datetime.now(tz=timezone.utc).isoformat()
                self.storage.save_job(job)
                self.storage.append_crawl_log(job_id, {
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "level": "warning",
                    "message": "Crawl cancelled",
                })
                return

            job.status = "processing"
            self.storage.save_job(job)
            internal_records = self.storage.load_page_records(job.job_id, source_type="internal")
            internal_records = [record for record in internal_records if record.status == "success"]
            internal_records = self.cleaner.remove_template_lines(internal_records)
            internal_records = self.cleaner.mark_duplicates(internal_records)
            for record in internal_records:
                self._classify_record(record)
                self.storage.save_page_record(job.job_id, record)

            all_records = self.storage.load_page_records(job.job_id)
            self._write_outputs(job, all_records)

            job.status = "completed"
            job.finished_at = datetime.now(tz=timezone.utc).isoformat()
            self.storage.save_job(job)
            self.storage.append_crawl_log(job_id, {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "level": "success",
                "message": "Crawl completed",
            })
        except Exception as exc:
            job.status = "failed"
            job.finished_at = datetime.now(tz=timezone.utc).isoformat()
            job.errors = sorted(set(job.errors + [str(exc)]))
            self.storage.save_job(job)
            self.storage.append_crawl_log(job_id, {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "level": "error",
                "message": str(exc),
            })
            raise
        finally:
            self.storage.clear_cancel_request(job_id)
            self.storage.clear_worker_pid(job_id)

    def refresh_outputs(self, job_id: str) -> None:
        job = self.storage.load_job(job_id)
        all_records = self.storage.load_page_records(job_id)
        self._write_outputs(job, all_records)
        self.storage.save_job(job)

    def _build_record(self, job: CrawlJob, result) -> PageRecord:
        parsed = urlparse(result.url)
        markdown_body = _strip_frontmatter(result.markdown or "")
        record = PageRecord(
            url=result.url,
            normalized_url=self._normalize_url(result.url),
            domain=parsed.netloc.lower().removeprefix("www."),
            path=parsed.path or "/",
            source_type="internal",
            discovered_via="crawl",
            title=result.title or "",
            description=result.description or "",
            headings=result.headings,
            language=result.language or "",
            raw_html=result.raw_html or "",
            raw_text=markdown_body or "",
            markdown=markdown_body or "",
            page_category=result.page_type or "other",
            page_subtype="",
            category_confidence=0.5,
            status=result.status,
            status_code=result.status_code or (200 if result.status == "success" else 0),
            engine_selected=result.engine_used,
            engine_used=result.engine_used,
            robots_disallowed=False,
            outbound_links=[],
            metadata={"skip_reason": result.skip_reason},
        )
        if record.status == "success":
            record = self.cleaner.clean_record(record)
        self._classify_record(record)
        return record

    def _classify_record(self, record: PageRecord) -> None:
        category, subtype, confidence = self.classifier.classify(record)
        record.page_category = category
        record.page_subtype = subtype
        record.category_confidence = confidence

    def _prepare_resume(self, job: CrawlJob, records: list[PageRecord]) -> None:
        job.status = "queued"
        job.finished_at = ""
        job.errors = []
        resumed_warning = f"Resumed crawl from {len(records)} saved pages."
        job.warnings = sorted(set(warning for warning in job.warnings if "worker process stopped unexpectedly" not in warning.lower()))
        job.warnings = sorted(set(job.warnings + [resumed_warning]))

    def _build_crawl_seed_urls(self, job: CrawlJob, seed_urls: list[str], records: list[PageRecord]) -> list[str]:
        if not records:
            return seed_urls

        urls: list[str] = list(seed_urls)
        for record in records:
            if record.source_type != "internal" or record.status != "success":
                continue
            urls.extend(self._extract_resume_links(job, record))

        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            normalized = self._normalize_url(url)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(url)
        return deduped

    def _extract_resume_links(self, job: CrawlJob, record: PageRecord) -> list[str]:
        if not record.raw_html:
            return []

        links: list[str] = []
        soup = BeautifulSoup(record.raw_html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absolute = urldefrag(urljoin(record.url, href)).url
            parsed = urlparse(absolute)
            domain = parsed.netloc.lower().removeprefix("www.")
            if parsed.scheme in {"http", "https"} and domain == job.domain.lower():
                links.append(absolute)
        return links

    def _update_job_counts(self, job: CrawlJob, record: PageRecord) -> None:
        skip_reason = str((record.metadata or {}).get("skip_reason", "")).lower()
        if record.status_code in {401, 403} or "http 401" in skip_reason or "http 403" in skip_reason:
            job.pages_blocked += 1
            job.pages_failed += 1
        elif record.status == "success":
            job.pages_scraped += 1
            job.total_words += record.word_count
        elif record.status == "failed":
            job.pages_failed += 1
        else:
            job.pages_skipped += 1
        job.pages_total = max(
            job.pages_total,
            job.pages_scraped + job.pages_failed + job.pages_skipped,
        )

    def _write_outputs(self, job: CrawlJob, records: list[PageRecord]) -> None:
        internal_records = [
            record for record in filter_records_for_outputs(records)
            if record.source_type == "internal"
        ]
        entities = self.extractor.extract(internal_records, job.domain)
        self.storage.write_entities(job.job_id, entities)
        self.storage.write_corpus_jsonl(job.job_id, internal_records)
        if job.settings.enable_structured_export:
            self.exporter.write_excel(
                job,
                internal_records,
                entities,
                self.storage.job_dir(job.job_id) / "exports" / "intel.xlsx",
            )

    def _normalize_url(self, url: str) -> str:
        stripped = urldefrag(url.strip()).url
        parsed = urlparse(stripped)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        query = parsed.query
        return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")

    def _log_entry(self, record: PageRecord) -> dict:
        skip_reason = str((record.metadata or {}).get("skip_reason", "")).strip()
        return {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "url": record.url,
            "status": record.status,
            "status_code": record.status_code,
            "engine": record.engine_used,
            "category": record.page_category,
            "words": record.word_count,
            "reason": skip_reason,
        }
