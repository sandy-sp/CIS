from company_intel.models import CrawlJob, CrawlSettings
from pages.index_page import _job_index_status_rows


def _job(job_id: str, domain: str) -> CrawlJob:
    return CrawlJob(
        job_id=job_id,
        domain=domain,
        settings=CrawlSettings(start_url=f"https://{domain}"),
        status="completed",
        pages_scraped=42,
    )


def test_job_index_status_rows_marks_internal_and_full_targets():
    jobs = [_job("job-1", "example.com"), _job("job-2", "acme.com")]
    indexed_targets = [
        {
            "job_id": "job-1",
            "include_external": False,
            "indexed_at": "2026-03-25T14:00:00+00:00",
        },
        {
            "job_id": "job-1",
            "include_external": True,
            "indexed_at": "2026-03-25T14:05:00+00:00",
        },
    ]

    rows = _job_index_status_rows(jobs, indexed_targets)

    assert rows[0]["Internal Only"] == "Indexed"
    assert rows[0]["Internal + External"] == "Indexed"
    assert rows[0]["Last Indexed"] == "2026-03-25 14:05:00"
    assert rows[1]["Internal Only"] == "Not indexed"
    assert rows[1]["Internal + External"] == "Not indexed"
