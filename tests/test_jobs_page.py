from company_intel.models import CrawlJob, CrawlSettings
from pages.jobs_page import _can_resume


def test_can_resume_only_allows_failed_or_cancelled_jobs():
    settings = CrawlSettings(start_url="https://example.com")
    failed = CrawlJob(job_id="job-1", domain="example.com", settings=settings, status="failed")
    cancelled = CrawlJob(job_id="job-2", domain="example.com", settings=settings, status="cancelled")
    completed = CrawlJob(job_id="job-3", domain="example.com", settings=settings, status="completed")

    assert _can_resume(failed) is True
    assert _can_resume(cancelled) is True
    assert _can_resume(completed) is False
