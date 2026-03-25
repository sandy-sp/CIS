from pathlib import Path
from unittest.mock import patch

from company_intel.models import CrawlSettings, PageRecord
from company_intel.storage import JobStorage, collection_name_for_job


def test_job_storage_mirrors_url_paths(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))

    record = PageRecord(
        url="https://example.com/services/consulting",
        normalized_url="https://example.com/services/consulting",
        domain="example.com",
        path="/services/consulting",
        title="Consulting Services",
        markdown="# Consulting",
        clean_text="Consulting",
        word_count=1,
    )
    storage.save_page_record(job.job_id, record)

    raw_path = storage.raw_page_path(job.job_id, record.url)
    clean_path = storage.clean_page_path(job.job_id, record.url)

    assert raw_path.exists()
    assert clean_path.exists()
    assert "services" in str(clean_path)
    assert not (storage.job_dir(job.job_id) / "pages" / "markdown").exists()


def test_job_storage_loads_saved_records(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    record = PageRecord(
        url="https://example.com/about",
        normalized_url="https://example.com/about",
        domain="example.com",
        path="/about",
        title="About",
        markdown="# About",
        clean_text="About Example",
        word_count=2,
    )
    storage.save_page_record(job.job_id, record)

    records = storage.load_page_records(job.job_id)

    assert len(records) == 1
    assert records[0].url == "https://example.com/about"


def test_job_storage_iterates_saved_records(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    first = PageRecord(
        url="https://example.com/about",
        normalized_url="https://example.com/about",
        domain="example.com",
        path="/about",
        title="About",
        clean_text="About Example",
        word_count=2,
    )
    second = PageRecord(
        url="https://example.com/services",
        normalized_url="https://example.com/services",
        domain="example.com",
        path="/services",
        title="Services",
        clean_text="Services Example",
        word_count=2,
    )
    storage.save_page_record(job.job_id, first)
    storage.save_page_record(job.job_id, second)

    records = list(storage.iter_page_records(job.job_id))

    assert [record.url for record in records] == [
        "https://example.com/about",
        "https://example.com/services",
    ]


def test_job_storage_lists_jobs_by_status(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    completed = storage.create_job(CrawlSettings(start_url="https://example.com"))
    completed.status = "completed"
    storage.save_job(completed)

    queued = storage.create_job(CrawlSettings(start_url="https://other.com"))
    storage.save_job(queued)

    jobs = storage.list_jobs(status="completed")

    assert len(jobs) == 1
    assert jobs[0].job_id == completed.job_id


def test_collection_name_for_job_distinguishes_variants():
    full = collection_name_for_job("20260318-example", "example.com", include_external=True)
    internal = collection_name_for_job("20260318-example", "example.com", include_external=False)

    assert full != internal
    assert full.startswith("company-intel-")


def test_job_storage_writes_external_artifacts(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    record = PageRecord(
        url="https://www.linkedin.com/company/example",
        normalized_url="https://www.linkedin.com/company/example",
        domain="linkedin.com",
        path="/company/example",
        source_type="external",
        discovered_via="search",
        title="Example on LinkedIn",
        markdown="# Example",
        clean_text="Example",
        word_count=1,
    )

    storage.save_page_record(job.job_id, record)

    assert storage.external_record_path(job.job_id, record.url).exists()
    assert not list((storage.job_dir(job.job_id) / "externals").rglob("*.md"))


def test_load_job_retries_transient_empty_json(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    valid_payload = (storage.job_dir(job.job_id) / "job.json").read_text(encoding="utf-8")

    with patch.object(Path, "read_text", side_effect=["", valid_payload]):
        loaded = storage.load_job(job.job_id)

    assert loaded.job_id == job.job_id
