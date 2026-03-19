from __future__ import annotations

import asyncio
from queue import Queue
from datetime import datetime, timezone
from urllib.parse import urlparse

import redis

from company_intel.classifier import PageClassifier
from company_intel.cleaner import CorpusCleaner
from company_intel.exporter import IntelExporter
from company_intel.external import ExternalCollector
from company_intel.extractor import UniversalExtractor
from company_intel.models import CrawlJob, CrawlSettings, PageRecord
from company_intel.review import filter_records_for_outputs
from company_intel.storage import JobStorage
from scraper.hybrid_scraper import HybridScraper
from scraper.page_probe import EngineRouter
from scraper.queue_manager import QueueManager
from scraper.snooper import Snooper


def _strip_frontmatter(markdown: str) -> str:
    if markdown.startswith("---"):
        parts = markdown.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return markdown.strip()


class JobRunner:
    def __init__(self, redis_url: str = "redis://localhost:6379", storage: JobStorage | None = None):
        self.redis_url = redis_url
        self.storage = storage or JobStorage()
        self.classifier = PageClassifier()
        self.cleaner = CorpusCleaner()
        self.extractor = UniversalExtractor()
        self.exporter = IntelExporter()
        self.external_collector = ExternalCollector()

    def create_job(self, settings: CrawlSettings) -> CrawlJob:
        return self.storage.create_job(settings)

    def run(self, job_id: str, result_queue: Queue | None = None, cancel_flag: list | None = None) -> None:
        asyncio.run(self._run(job_id, result_queue=result_queue, cancel_flag=cancel_flag or []))

    @staticmethod
    def _emit_job_update(result_queue: Queue | None, job: CrawlJob) -> None:
        if result_queue:
            result_queue.put({"type": "job", "job": job.to_dict()})

    @staticmethod
    def _emit_complete(result_queue: Queue | None, job: CrawlJob) -> None:
        if result_queue:
            result_queue.put({"type": "complete", "job": job.to_dict()})

    async def _run(self, job_id: str, result_queue: Queue | None = None, cancel_flag: list | None = None) -> None:
        cancel_flag = cancel_flag or []
        job = self.storage.load_job(job_id)
        redis_client = self._get_redis_client()
        qm = QueueManager(job.domain, redis_client=redis_client)
        qm.flush()

        try:
            job.status = "discovering"
            self.storage.save_job(job)
            self._emit_job_update(result_queue, job)

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
            self.storage.save_job(job)

            qm.update_meta(
                has_llm_txt=str(snooper.has_llm_txt),
                has_robots_txt=str(snooper.has_robots_txt),
                seed_source=snooper.seed_source,
                seed_count=str(len(seed_urls)),
                pages_found=len(seed_urls),
                pages_done=0,
                total_words=0,
            )
            for url in seed_urls:
                qm.enqueue(url)

            job.status = "crawling"
            self.storage.save_job(job)
            self._emit_job_update(result_queue, job)
            scraper = HybridScraper(
                qm,
                snooper,
                max_pages=job.settings.max_pages,
                cancel_flag=cancel_flag,
                ignore_robots_exclusions=job.settings.ignore_robots_exclusions,
                persist_raw_markdown=False,
                keep_duplicate_pages=True,
                engine_router=EngineRouter(),
                enable_static_salvage=True,
            )

            async for result in scraper.crawl(job.settings.start_url):
                record = self._build_record(job, qm, result)
                self.storage.save_page_record(job.job_id, record)
                self._update_job_counts(job, record)
                self.storage.save_job(job)
                if result_queue:
                    result_queue.put({
                        "type": "page",
                        "job": job.to_dict(),
                        "record": record.to_dict(),
                    })

            if cancel_flag:
                job.status = "cancelled"
                self.storage.save_job(job)
                self._emit_complete(result_queue, job)
                return

            job.status = "cleaning"
            self.storage.save_job(job)
            self._emit_job_update(result_queue, job)
            internal_records = self.storage.load_page_records(job.job_id, source_type="internal")
            internal_records = [record for record in internal_records if record.status == "success"]
            internal_records = self.cleaner.remove_template_lines(internal_records)
            internal_records = self.cleaner.mark_duplicates(internal_records)
            for record in internal_records:
                self._classify_record(record)
                self.storage.save_page_record(job.job_id, record)

            all_records = self.storage.load_page_records(job.job_id)

            if job.settings.follow_external_sources:
                job.status = "external_enrichment"
                self.storage.save_job(job)
                self._emit_job_update(result_queue, job)
                external_report = self.external_collector.collect(
                    qm.get_external_links(),
                    domain=job.domain,
                    internal_records=internal_records,
                )
                for record in external_report.records:
                    self.storage.save_page_record(job.job_id, record)
                if external_report.warnings:
                    job.warnings = sorted(set(job.warnings + external_report.warnings))
                job.external_pages = len(external_report.records)
                self.storage.save_job(job)
                all_records = self.storage.load_page_records(job.job_id)

            job.status = "extracting"
            self.storage.save_job(job)
            self._emit_job_update(result_queue, job)
            self._write_outputs(job, all_records)

            job.status = "completed"
            job.finished_at = datetime.now(tz=timezone.utc).isoformat()
            self.storage.save_job(job)
            self._emit_complete(result_queue, job)
        except Exception as exc:
            job.status = "failed"
            job.errors = sorted(set(job.errors + [str(exc)]))
            self.storage.save_job(job)
            self._emit_complete(result_queue, job)
            raise

    def refresh_outputs(self, job_id: str) -> None:
        job = self.storage.load_job(job_id)
        all_records = self.storage.load_page_records(job_id)
        self._write_outputs(job, all_records)
        self.storage.save_job(job)

    def _build_record(self, job: CrawlJob, qm: QueueManager, result) -> PageRecord:
        parsed = urlparse(result.url)
        markdown_body = _strip_frontmatter(result.markdown or "")
        record = PageRecord(
            url=result.url,
            normalized_url=qm.normalize(result.url),
            domain=parsed.netloc.lstrip("www."),
            path=parsed.path or "/",
            source_type="internal",
            discovered_via="crawl",
            title=result.title,
            description=result.description,
            headings=result.headings,
            language=result.language,
            raw_html=result.raw_html,
            raw_text=markdown_body,
            markdown=markdown_body,
            page_category=result.page_type or "other",
            page_subtype="",
            category_confidence=0.5,
            status=result.status,
            status_code=200 if result.status == "success" else 0,
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

    def _update_job_counts(self, job: CrawlJob, record: PageRecord) -> None:
        if record.status == "success":
            job.pages_scraped += 1
            job.total_words += record.word_count
        elif record.status == "failed":
            job.pages_failed += 1
        else:
            job.pages_skipped += 1
        job.pages_total = max(job.pages_total, job.pages_scraped + job.pages_failed + job.pages_skipped)

    def _write_outputs(self, job: CrawlJob, records: list[PageRecord]) -> None:
        approved_records = filter_records_for_outputs(records)
        entities = self.extractor.extract(approved_records, job.domain)
        self.storage.write_entities(job.job_id, entities)
        self.storage.write_corpus_jsonl(job.job_id, approved_records)
        if job.settings.enable_structured_export:
            self.exporter.write_excel(
                job,
                approved_records,
                entities,
                self.storage.job_dir(job.job_id) / "exports" / "intel.xlsx",
            )

    def _get_redis_client(self):
        try:
            client = redis.from_url(self.redis_url, decode_responses=True)
            client.ping()
            return client
        except Exception:
            try:
                import fakeredis
            except Exception as exc:
                raise RuntimeError(
                    "Redis is unavailable and fakeredis is not installed. Start Redis or install fakeredis."
                ) from exc
            return fakeredis.FakeRedis(decode_responses=True)
