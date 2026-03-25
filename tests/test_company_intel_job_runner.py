from company_intel.job_runner import JobRunner
from company_intel.models import CrawlJob, CrawlSettings, PageRecord
from company_intel.storage import JobStorage


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
