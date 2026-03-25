from __future__ import annotations

import streamlit as st

from company_intel import JobRunner
from company_intel.runtime import launch_worker
from company_intel.storage import JobStorage


_STORAGE = JobStorage()


def _job_label(job: dict) -> str:
    created = (job.get("created_at") or "").replace("T", " ")[:19]
    return f"{job.get('domain', '')} | {job.get('status', '')} | {created} | {job.get('job_id', '')}"


def _can_resume(job) -> bool:
    return job.status in {"failed", "cancelled"} and not _STORAGE.worker_is_running(job.job_id)


def jobs_page() -> None:
    st.title("Jobs & Downloads")
    st.caption("Inspect saved scrape runs, resume interrupted jobs, review the saved corpus, and download job artifacts.")

    jobs = [job.to_dict() for job in _STORAGE.list_jobs()]
    if not jobs:
        st.info("No saved jobs yet.")
        return

    job_ids = [job["job_id"] for job in jobs]
    selected_job_id = st.selectbox(
        "Saved jobs",
        options=job_ids,
        format_func=lambda job_id: _job_label(next(job for job in jobs if job["job_id"] == job_id)),
    )
    try:
        job = _STORAGE.load_job(selected_job_id)
    except Exception:
        st.info("Refreshing saved jobs...")
        st.rerun()
        return
    records = _STORAGE.load_page_records(selected_job_id)
    entities = _STORAGE.load_entities(selected_job_id)
    job_bundle = _STORAGE.bundle_job(selected_job_id)

    st.subheader("Job Summary")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Status", job.status)
    c2.metric("Discovered", job.pages_total)
    c3.metric("Scraped", job.pages_scraped)
    c4.metric("Skipped", job.pages_skipped)
    c5.metric("Denied/Failed", job.pages_failed)

    c6, c7, c8, c9 = st.columns(4)
    c6.metric("Access denied", job.pages_blocked)
    c7.metric("Words", f"{job.total_words:,}")
    c8.metric("Robots.txt", "Found" if job.robots_txt_found else "Not found")
    c9.metric("LLM.txt", "Found" if job.llm_txt_found else "Not found")

    if _can_resume(job):
        if st.button("Resume Crawl", key=f"resume_{job.job_id}"):
            runner = JobRunner(storage=_STORAGE)
            resumed = runner.resume_job(job.job_id)
            launch_worker(resumed.job_id, storage=_STORAGE)
            st.session_state.active_job_id = resumed.job_id
            st.session_state.selected_job_id = resumed.job_id
            st.session_state.next_page = "Scrape"
            st.rerun()
    elif job.status == "completed":
        if st.button("Open In Index", key=f"open_index_{job.job_id}"):
            st.session_state.selected_job_id = job.job_id
            st.session_state.next_page = "Index"
            st.rerun()

    excel_path = _STORAGE.job_dir(selected_job_id) / "exports" / "intel.xlsx"
    entities_path = _STORAGE.job_dir(selected_job_id) / "exports" / "entities.json"
    corpus_path = _STORAGE.job_dir(selected_job_id) / "exports" / "corpus.jsonl"

    st.subheader("Downloads")
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button(
        "Download Job ZIP",
        data=job_bundle,
        file_name=f"{selected_job_id}.zip",
        mime="application/zip",
    )
    if excel_path.exists():
        d2.download_button(
            "Download Excel",
            data=excel_path.read_bytes(),
            file_name=f"{selected_job_id}-intel.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if entities_path.exists():
        d3.download_button(
            "Download Entities JSON",
            data=entities_path.read_bytes(),
            file_name=f"{selected_job_id}-entities.json",
            mime="application/json",
        )
    if corpus_path.exists():
        d4.download_button(
            "Download Corpus JSONL",
            data=corpus_path.read_bytes(),
            file_name=f"{selected_job_id}-corpus.jsonl",
            mime="application/json",
        )

    if entities:
        st.subheader("Entity Summary")
        st.write({key: len(values) for key, values in entities.items()})

    if records:
        st.subheader("Page Inventory")
        preview = []
        for record in sorted(records, key=lambda item: item.url)[:100]:
            preview.append({
                "URL": record.url,
                "Category": record.page_category,
                "Status": record.status,
                "Source": record.source_type,
                "Words": record.word_count,
                "Engine": record.engine_used,
                "Duplicate": "yes" if record.is_duplicate else "",
            })
        st.dataframe(preview, use_container_width=True, hide_index=True)

    log_rows = _STORAGE.load_crawl_log(selected_job_id, limit=50)
    if log_rows:
        st.subheader("Crawl Log")
        table = []
        for row in log_rows:
            table.append({
                "Time": str(row.get("timestamp", "")).replace("T", " ")[:19],
                "Status": row.get("status", row.get("level", "")),
                "Engine": row.get("engine", ""),
                "URL": row.get("url", row.get("message", "")),
                "Reason": row.get("reason", ""),
            })
        st.dataframe(table, use_container_width=True, hide_index=True)
