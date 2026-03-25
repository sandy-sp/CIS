import json

from company_intel.job_runner import JobRunner
from company_intel.models import CrawlJob, CrawlSettings, PageRecord
from company_intel.storage import JobStorage
from models import PageResult


def _make_record(url: str, source_type: str = "internal", status: str = "success") -> PageRecord:
    return PageRecord(
        url=url,
        normalized_url=url,
        domain="example.com",
        path="/",
        source_type=source_type,
        markdown="# Title\n\nContent",
        clean_text="Title Content",
        raw_text="Title Content",
        title="Title",
        page_category="company",
        status=status,
        word_count=2,
    )


def test_crawl_settings_defaults_match_scrape_first_path():
    settings = CrawlSettings(start_url="https://example.com")

    assert settings.follow_external_sources is False
    assert settings.enable_structured_export is True
    assert not hasattr(settings, "enable_rag_index")


def test_crawl_settings_from_dict_ignores_removed_live_index_key():
    settings = CrawlSettings.from_dict({
        "start_url": "https://example.com",
        "max_pages": 250,
        "enable_rag_index": True,
    })

    assert settings.start_url == "https://example.com"
    assert settings.max_pages == 250
    assert settings.follow_external_sources is False
    assert not hasattr(settings, "enable_rag_index")


def test_crawl_job_from_dict_ignores_removed_legacy_fields():
    job = CrawlJob.from_dict({
        "job_id": "job-123",
        "domain": "example.com",
        "status": "completed",
        "external_pages": 9,
        "settings": {
            "start_url": "https://example.com",
            "enable_rag_index": True,
        },
    })

    assert job.job_id == "job-123"
    assert job.status == "completed"
    assert job.settings.start_url == "https://example.com"
    assert job.settings.follow_external_sources is False


def test_resume_job_resets_terminal_state_and_preserves_progress(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    runner = JobRunner(storage=storage)
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    record = _make_record("https://example.com/about")
    storage.save_page_record(job.job_id, record)

    job.status = "failed"
    job.finished_at = "2026-03-25T01:00:00+00:00"
    job.errors = ["Worker process stopped unexpectedly."]
    storage.save_job(job)

    resumed = runner.resume_job(job.job_id)

    assert resumed.status == "queued"
    assert resumed.finished_at == ""
    assert resumed.errors == []
    assert any("resumed crawl" in warning.lower() for warning in resumed.warnings)


def test_build_crawl_seed_urls_uses_saved_internal_links_for_resume(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    runner = JobRunner(storage=storage)
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    record = _make_record("https://example.com/about")
    record.raw_html = """
    <html><body>
      <a href="/services">Services</a>
      <a href="https://external.example/profile">External</a>
    </body></html>
    """

    urls = runner._build_crawl_seed_urls(job, ["https://example.com/"], [record])

    assert "https://example.com/" in urls
    assert "https://example.com/services" in urls
    assert all("external.example" not in url for url in urls)


class _FakeSnooper:
    def __init__(self, start_url: str, default_delay: float = 0.0):
        self.start_url = start_url
        self.crawl_delay = default_delay
        self.has_llm_txt = False
        self.has_robots_txt = True
        self.seed_source = "discovery"

    def load_robots(self) -> None:
        return None

    def get_discovery_urls(self) -> list[str]:
        return [self.start_url]

    def has_nofollow(self, html: str) -> bool:
        return False

    def is_external(self, url: str) -> bool:
        return not url.startswith("https://example.com")

    def is_disallowed(self, url: str) -> bool:
        return False

    def has_noindex(self, html: str) -> bool:
        return False


class _ControlledSiteCrawler:
    def __init__(self, snooper, **kwargs):
        self.snooper = snooper
        self.max_pages = kwargs.get("max_pages", 500)
        self.visited_urls = list(kwargs.get("visited_urls") or [])
        self.processed_count = kwargs.get("processed_count", 0)
        self.discovered_count = len(self.visited_urls)

    async def crawl(self, seed_urls: list[str], *, cancel_requested=None):
        assert seed_urls == ["https://example.com"]
        self.discovered_count = 2
        results = [
            PageResult(
                url="https://example.com",
                title="Example Biotech",
                description="Example Biotech builds lab software for regulated teams.",
                raw_html="""
                <html><body><main>
                  <h1>Example Biotech</h1>
                  <p>Example Biotech builds lab software for regulated teams and supports delivery across research, quality, and operations.</p>
                  <a href="/services/automation">Automation Services</a>
                </main></body></html>
                """,
                markdown="# Example Biotech\n\nExample Biotech builds lab software for regulated teams and supports delivery across research, quality, and operations.",
                page_type="company",
                engine_used="static",
                status="success",
            ),
            PageResult(
                url="https://example.com/services/automation",
                title="Automation Services",
                description="Automation services for lab and quality workflows.",
                raw_html="""
                <html><body><main>
                  <h1>Automation Services</h1>
                  <p>We design automation programs, integration delivery, and validation support for laboratory and quality operations teams.</p>
                </main></body></html>
                """,
                markdown="# Automation Services\n\nWe design automation programs, integration delivery, and validation support for laboratory and quality operations teams.",
                page_type="services",
                engine_used="static",
                status="success",
            ),
        ]

        for result in results:
            if cancel_requested and cancel_requested():
                break
            yield result


def test_run_persists_scrape_outputs_end_to_end(tmp_path, monkeypatch):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    runner = JobRunner(storage=storage)
    job = runner.create_job(CrawlSettings(start_url="https://example.com", max_pages=5, rate_limit=0))

    monkeypatch.setattr("company_intel.job_runner.Snooper", _FakeSnooper)
    monkeypatch.setattr("company_intel.job_runner.SiteCrawler", _ControlledSiteCrawler)

    runner.run(job.job_id)

    saved_job = storage.load_job(job.job_id)
    export_dir = storage.job_dir(job.job_id) / "exports"
    corpus_path = export_dir / "corpus.jsonl"
    entities_path = export_dir / "entities.json"
    workbook_path = export_dir / "intel.xlsx"

    assert saved_job.status == "completed"
    assert saved_job.pages_scraped == 2
    assert saved_job.finished_at

    homepage_raw = storage.raw_page_path(job.job_id, "https://example.com")
    homepage_clean = storage.clean_page_path(job.job_id, "https://example.com")
    services_raw = storage.raw_page_path(job.job_id, "https://example.com/services/automation")
    services_clean = storage.clean_page_path(job.job_id, "https://example.com/services/automation")

    assert homepage_raw.exists()
    assert homepage_clean.exists()
    assert services_raw.exists()
    assert services_clean.exists()

    homepage_clean_doc = json.loads(homepage_clean.read_text(encoding="utf-8"))
    services_clean_doc = json.loads(services_clean.read_text(encoding="utf-8"))
    corpus_docs = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entities_doc = json.loads(entities_path.read_text(encoding="utf-8"))

    assert homepage_clean_doc["page_category"] == "homepage"
    assert homepage_clean_doc["clean_text"]
    assert services_clean_doc["page_category"] == "services"
    assert services_clean_doc["clean_text"]
    assert entities_path.exists()
    assert corpus_path.exists()
    assert workbook_path.exists()
    assert [doc["url"] for doc in corpus_docs] == [
        "https://example.com",
        "https://example.com/services/automation",
    ]
    assert "company_profile" in entities_doc
