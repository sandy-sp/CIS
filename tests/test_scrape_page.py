from unittest.mock import patch

from company_intel.models import CrawlSettings
from company_intel.storage import JobStorage
from pages.scrape_page import _preview_discovery, _start_job, sync_active_crawl_state


def test_sync_active_crawl_state_tracks_latest_active_job(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    old_job = storage.create_job(CrawlSettings(start_url="https://one.example"))
    old_job.status = "completed"
    storage.save_job(old_job)

    active_job = storage.create_job(CrawlSettings(start_url="https://two.example"))
    active_job.status = "crawling"
    storage.save_job(active_job)
    storage.save_worker_pid(active_job.job_id, 12345)

    state = {}
    with patch.object(storage, "worker_is_running", return_value=True):
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


def test_sync_active_crawl_state_marks_stale_active_job_failed(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    job.status = "crawling"
    storage.save_job(job)

    state = {}
    with patch.object(storage, "worker_is_running", return_value=False):
        sync_active_crawl_state(state, storage=storage)

    refreshed = storage.load_job(job.job_id)
    assert refreshed.status == "failed"
    assert "Worker process stopped unexpectedly." in refreshed.errors
    assert state["active_job_id"] == ""
    assert state["selected_job_id"] == job.job_id


def test_sync_active_crawl_state_marks_stale_cancelled_job(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    job.status = "crawling"
    storage.save_job(job)
    storage.request_cancel(job.job_id)

    state = {}
    with patch.object(storage, "worker_is_running", return_value=False):
        sync_active_crawl_state(state, storage=storage)

    refreshed = storage.load_job(job.job_id)
    assert refreshed.status == "cancelled"
    assert "cancel request" in refreshed.warnings[0].lower()
    assert state["active_job_id"] == ""


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


def test_start_job_uses_scrape_first_defaults(monkeypatch, tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    captured = {}

    def fake_create_job(self, settings):
        captured["settings"] = settings
        return storage.create_job(settings)

    monkeypatch.setattr("pages.scrape_page._STORAGE", storage)
    monkeypatch.setattr("pages.scrape_page.JobRunner.create_job", fake_create_job)
    monkeypatch.setattr("pages.scrape_page.launch_worker", lambda job_id, storage=None: 12345)

    job_id = _start_job("https://example.com", 250, 0.5, ignore_robots=False)

    assert job_id
    assert captured["settings"].follow_external_sources is False
    assert captured["settings"].enable_structured_export is True
    assert not hasattr(captured["settings"], "enable_rag_index")
    assert captured["settings"].ignore_robots_exclusions is False
