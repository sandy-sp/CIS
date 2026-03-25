from unittest.mock import patch

from company_intel.models import CrawlSettings
from company_intel.storage import JobStorage
from pages.scrape_page import _preview_discovery, sync_active_crawl_state


def test_sync_active_crawl_state_tracks_latest_active_job(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    old_job = storage.create_job(CrawlSettings(start_url="https://one.example"))
    old_job.status = "completed"
    storage.save_job(old_job)

    active_job = storage.create_job(CrawlSettings(start_url="https://two.example"))
    active_job.status = "crawling"
    storage.save_job(active_job)

    state = {}
    sync_active_crawl_state(state, storage=storage)

    assert state["active_job_id"] == active_job.job_id
    assert state["selected_job_id"] == active_job.job_id


def test_sync_active_crawl_state_clears_finished_active_job(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    job.status = "completed"
    storage.save_job(job)

    state = {"active_job_id": job.job_id}
    sync_active_crawl_state(state, storage=storage)

    assert state["active_job_id"] == ""
    assert state["selected_job_id"] == job.job_id


def test_preview_discovery_returns_count_and_source():
    with patch("pages.scrape_page.Snooper") as MockSnooper:
        snooper = MockSnooper.return_value
        snooper.seed_source = "sitemap+root"
        snooper.has_robots_txt = True
        snooper.has_llm_txt = False
        snooper.crawl_delay = 1.5
        snooper.get_discovery_urls.return_value = [
            "https://example.com/",
            "https://example.com/services",
            "https://example.com/about",
        ]

        preview = _preview_discovery("https://example.com", 1.0)

    assert preview["count"] == 3
    assert preview["seed_source"] == "sitemap+root"
    assert preview["robots_txt_found"] is True
    assert preview["llm_txt_found"] is False
    assert preview["sample_urls"][0] == "https://example.com/"
