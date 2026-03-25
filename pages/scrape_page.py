from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from company_intel import CrawlSettings, JobRunner
from company_intel.storage import JobStorage
from scraper.snooper import Snooper


_STORAGE = JobStorage()
_ACTIVE_JOB_STATUSES = {"queued", "discovering", "crawling", "processing"}
_ROOT_DIR = Path(__file__).resolve().parent.parent


def _ensure_state(state=None) -> None:
    if state is None:
        state = st.session_state
    defaults = {
        "current_page": "Scrape",
        "active_job_id": "",
        "selected_job_id": "",
        "discovery_preview": None,
    }
    for key, value in defaults.items():
        if key not in state:
            state[key] = value


def sync_active_crawl_state(state=None, storage: JobStorage | None = None) -> None:
    if state is None:
        state = st.session_state
    storage = storage or _STORAGE
    _ensure_state(state)

    active_job_id = str(state.get("active_job_id") or "").strip()
    if active_job_id:
        try:
            job = storage.load_job(active_job_id)
        except Exception:
            state["active_job_id"] = ""
            return
        if job.status in _ACTIVE_JOB_STATUSES and not storage.worker_is_running(job.job_id):
            _finalize_stale_job(job, storage)
            job = storage.load_job(active_job_id)
        if job.status in _ACTIVE_JOB_STATUSES:
            state["selected_job_id"] = job.job_id
            return
        state["active_job_id"] = ""
        state["selected_job_id"] = job.job_id
        return

    for job in storage.list_jobs():
        if job.status in _ACTIVE_JOB_STATUSES and not storage.worker_is_running(job.job_id):
            _finalize_stale_job(job, storage)
            job = storage.load_job(job.job_id)
        if job.status in _ACTIVE_JOB_STATUSES:
            state["active_job_id"] = job.job_id
            state["selected_job_id"] = job.job_id
            return
        if not state.get("selected_job_id"):
            state["selected_job_id"] = job.job_id


def _finalize_stale_job(job, storage: JobStorage) -> None:
    if job.status not in _ACTIVE_JOB_STATUSES:
        return
    if storage.cancel_requested(job.job_id):
        job.status = "cancelled"
        job.warnings = sorted(set(job.warnings + ["Crawl stopped after a cancel request."]))
        storage.clear_cancel_request(job.job_id)
    else:
        job.status = "failed"
        job.errors = sorted(set(job.errors + ["Worker process stopped unexpectedly."]))
    job.finished_at = datetime.now(tz=timezone.utc).isoformat()
    storage.clear_worker_pid(job.job_id)
    storage.save_job(job)


def _preview_discovery(start_url: str, rate_limit: float) -> dict:
    snooper = Snooper(start_url, default_delay=rate_limit)
    snooper.load_robots()
    urls = snooper.get_discovery_urls()
    return {
        "start_url": start_url,
        "count": len(urls),
        "seed_source": snooper.seed_source,
        "robots_txt_found": snooper.has_robots_txt,
        "llm_txt_found": snooper.has_llm_txt,
        "crawl_delay": snooper.crawl_delay,
        "sample_urls": urls[:25],
    }


def _start_job(start_url: str, max_pages: int, rate_limit: float, ignore_robots: bool) -> str:
    settings = CrawlSettings(
        start_url=start_url,
        max_pages=max_pages,
        rate_limit=rate_limit,
        follow_external_sources=False,
        ignore_robots_exclusions=ignore_robots,
        enable_structured_export=True,
        enable_rag_index=False,
    )
    runner = JobRunner(storage=_STORAGE)
    job = runner.create_job(settings)
    _STORAGE.clear_cancel_request(job.job_id)

    worker_log = _STORAGE.job_dir(job.job_id) / "worker.log"
    with worker_log.open("ab") as log_handle:
        proc = subprocess.Popen(
            [sys.executable, "-m", "company_intel.worker", job.job_id],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(_ROOT_DIR),
            close_fds=True,
        )
    _STORAGE.save_worker_pid(job.job_id, proc.pid)
    return job.job_id


def _render_job_summary(job: dict) -> None:
    st.subheader("Job Status")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Status", job.get("status", ""))
    c2.metric("Discovered", job.get("pages_total", 0))
    c3.metric("Scraped", job.get("pages_scraped", 0))
    c4.metric("Skipped", job.get("pages_skipped", 0))
    c5.metric("Denied/Failed", job.get("pages_failed", 0))

    c6, c7, c8, c9 = st.columns(4)
    c6.metric("Access denied", job.get("pages_blocked", 0))
    c7.metric("Words", f"{job.get('total_words', 0):,}")
    c8.metric("Robots.txt", "Found" if job.get("robots_txt_found") else "Not found")
    c9.metric("LLM.txt", "Found" if job.get("llm_txt_found") else "Not found")

    st.caption(f"Job ID: `{job.get('job_id', '')}`")
    st.caption(f"Output: `{job.get('output_dir', '')}`")

    if job.get("warnings"):
        for warning in job["warnings"]:
            st.warning(warning)
    if job.get("errors"):
        for error in job["errors"]:
            st.error(error)


def _render_live_log(job_id: str) -> None:
    rows = _STORAGE.load_crawl_log(job_id, limit=30)
    if not rows:
        return
    st.subheader("Recent Crawl Activity")
    table = []
    for row in rows:
        table.append({
            "Time": str(row.get("timestamp", "")).replace("T", " ")[:19],
            "Status": row.get("status", row.get("level", "")),
            "Engine": row.get("engine", ""),
            "Words": row.get("words", ""),
            "URL": row.get("url", row.get("message", "")),
            "Reason": row.get("reason", ""),
        })
    st.dataframe(table, use_container_width=True, hide_index=True)


def scrape_page() -> None:
    _ensure_state()
    sync_active_crawl_state(st.session_state)

    st.title("Company Intelligence Scraper")
    st.caption("Discover a company site, crawl its first-party pages, save clean JSON artifacts, and export an Excel summary.")

    with st.form("scrape_job_form"):
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            start_url = st.text_input("Target URL", placeholder="https://example.com")
        with col2:
            max_pages = st.number_input("Max pages", min_value=10, max_value=5000, value=500, step=50)
        with col3:
            rate_limit = st.number_input("Rate limit (s)", min_value=0.0, max_value=10.0, value=1.0, step=0.5)

        ignore_robots = st.checkbox("Ignore robots/llm exclusions", value=True)
        action1, action2 = st.columns(2)
        preview_clicked = action1.form_submit_button("Preview Site Discovery")
        start_clicked = action2.form_submit_button(
            "Start Crawl Job",
            disabled=bool(st.session_state.get("active_job_id")),
        )

    if preview_clicked and start_url:
        if not start_url.startswith(("http://", "https://")):
            st.error("Enter a full URL starting with http:// or https://")
        else:
            try:
                st.session_state.discovery_preview = _preview_discovery(start_url.strip(), float(rate_limit))
            except Exception as exc:
                st.session_state.discovery_preview = None
                st.error(f"Discovery preview failed: {exc}")

    preview = st.session_state.get("discovery_preview")
    if preview and preview.get("start_url") == start_url:
        st.subheader("Discovery Preview")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Seed URLs", preview.get("count", 0))
        c2.metric("Seed source", preview.get("seed_source", ""))
        c3.metric("Robots.txt", "Found" if preview.get("robots_txt_found") else "Not found")
        c4.metric("LLM.txt", "Found" if preview.get("llm_txt_found") else "Not found")
        st.caption(f"Effective crawl delay: `{preview.get('crawl_delay', 0)}`s")
        st.dataframe(
            [{"Seed URL": url} for url in preview.get("sample_urls", [])],
            use_container_width=True,
            hide_index=True,
        )

    if start_clicked and start_url:
        if not start_url.startswith(("http://", "https://")):
            st.error("Enter a full URL starting with http:// or https://")
        else:
            job_id = _start_job(start_url.strip(), int(max_pages), float(rate_limit), bool(ignore_robots))
            st.session_state.active_job_id = job_id
            st.session_state.selected_job_id = job_id
            st.rerun()

    active_job_id = st.session_state.get("active_job_id", "")
    if active_job_id:
        try:
            job = _STORAGE.load_job(active_job_id).to_dict()
        except Exception:
            sync_active_crawl_state(st.session_state)
            st.info("Refreshing crawl state...")
            time.sleep(0.2)
            st.rerun()
        _render_job_summary(job)
        _render_live_log(active_job_id)

        if st.button("Cancel Crawl", key="cancel_active_crawl"):
            _STORAGE.request_cancel(active_job_id)
            st.warning("Cancellation requested. The worker will stop after the current page finishes.")

        if job.get("status") in _ACTIVE_JOB_STATUSES and st.session_state.get("current_page") == "Scrape":
            time.sleep(1.0)
            st.rerun()

    elif not _STORAGE.list_jobs():
        st.info("No scrape jobs yet. Preview a site map or start a crawl to begin.")
    else:
        st.info("No active crawl job. Open the Jobs page to inspect saved runs and downloads.")
