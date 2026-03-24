# pages/scrape_page.py
import json
import os
import queue
import threading
import time
from collections import Counter
from pathlib import Path
import re

import streamlit as st

from activity_log import activity_marker_changed, log_activity
from app_settings import default_ollama_url, ensure_session_settings
from company_intel import BenchmarkCase, CrawlSettings, JobRunner, build_job_benchmark_draft, evaluate_job
from company_intel.evaluation import write_report
from company_intel.review import external_review_status, set_external_review_status
from company_intel.storage import JobStorage, collection_name_for_job
from indexer.embedder import Embedder
from indexer.pipeline import IndexerPipeline
from indexer.registry import IndexRegistry


REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_STORAGE = JobStorage()
_REGISTRY = IndexRegistry()
_BENCHMARKS_DIR = Path("benchmarks")


def _job_option_label(job: dict) -> str:
    created = (job.get("created_at") or "").replace("T", " ")[:19]
    return f"{job.get('domain', '')} | {job.get('status', '')} | {created} | {job.get('job_id', '')}"


def _ensure_state() -> None:
    defaults = {
        "crawl_running": False,
        "job_id": "",
        "job_data": None,
        "result_queue": None,
        "cancel_flag": [],
        "recent_records": [],
        "job_bundle": None,
        "job_records": [],
        "job_entities": {},
        "selected_job_id": "",
        "collection_name": "",
        "indexed_targets": [],
        "active_rag_target_id": "",
        "benchmark_draft_bytes": b"",
        "benchmark_draft_file_name": "",
        "benchmark_draft_summary": {},
        "benchmark_draft_job_id": "",
        "benchmark_report_json_bytes": b"",
        "benchmark_report_md_bytes": b"",
        "benchmark_report_summary": {},
        "benchmark_report_rows": [],
        "benchmark_report_job_id": "",
        "benchmark_report_name": "",
        "benchmark_report_details": {},
        "benchmark_editor_text": "",
        "benchmark_editor_file_name": "",
        "benchmark_editor_summary": {},
        "benchmark_editor_job_id": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _run_job(job_id: str, result_queue: queue.Queue, cancel_flag: list) -> None:
    runner = JobRunner(redis_url=REDIS_URL, storage=_STORAGE)
    runner.run(job_id, result_queue=result_queue, cancel_flag=cancel_flag)


def _start_job(start_url: str, max_pages: int, rate_limit: float,
               follow_external_sources: bool, ignore_robots: bool) -> None:
    settings = CrawlSettings(
        start_url=start_url,
        max_pages=max_pages,
        rate_limit=rate_limit,
        follow_external_sources=follow_external_sources,
        ignore_robots_exclusions=ignore_robots,
        enable_structured_export=True,
        enable_rag_index=False,
    )
    runner = JobRunner(redis_url=REDIS_URL, storage=_STORAGE)
    job = runner.create_job(settings)
    log_activity(
        st.session_state,
        "crawl",
        f"Started crawl job `{job.job_id}` for {job.domain}",
        details=(
            f"Max pages: {max_pages} | Rate limit: {rate_limit}s | "
            f"External sources: {'yes' if follow_external_sources else 'no'} | "
            f"Ignore exclusions: {'yes' if ignore_robots else 'no'}"
        ),
    )

    st.session_state.crawl_running = True
    st.session_state.job_id = job.job_id
    st.session_state.job_data = job.to_dict()
    st.session_state.selected_job_id = job.job_id
    st.session_state.collection_name = collection_name_for_job(
        job.job_id,
        job.domain,
        include_external=follow_external_sources,
    )
    st.session_state.recent_records = []
    st.session_state.job_bundle = None
    st.session_state.job_records = []
    st.session_state.job_entities = {}
    st.session_state.benchmark_draft_bytes = b""
    st.session_state.benchmark_draft_file_name = ""
    st.session_state.benchmark_draft_summary = {}
    st.session_state.benchmark_draft_job_id = ""
    st.session_state.benchmark_report_json_bytes = b""
    st.session_state.benchmark_report_md_bytes = b""
    st.session_state.benchmark_report_summary = {}
    st.session_state.benchmark_report_rows = []
    st.session_state.benchmark_report_job_id = ""
    st.session_state.benchmark_report_name = ""
    st.session_state.benchmark_report_details = {}
    st.session_state.benchmark_editor_text = ""
    st.session_state.benchmark_editor_file_name = ""
    st.session_state.benchmark_editor_summary = {}
    st.session_state.benchmark_editor_job_id = ""
    st.session_state.cancel_flag = []
    st.session_state.result_queue = queue.Queue()

    threading.Thread(
        target=_run_job,
        args=(job.job_id, st.session_state.result_queue, st.session_state.cancel_flag),
        daemon=True,
    ).start()


def _load_job_outputs(job_id: str) -> None:
    job = _STORAGE.load_job(job_id)
    records = _STORAGE.load_page_records(job_id)
    entities_path = _STORAGE.job_dir(job_id) / "exports" / "entities.json"
    entities = {}
    if entities_path.exists():
        entities = json.loads(entities_path.read_text(encoding="utf-8"))
    st.session_state.job_id = job_id
    st.session_state.job_data = job.to_dict()
    st.session_state.selected_job_id = job_id
    st.session_state.collection_name = collection_name_for_job(
        job.job_id,
        job.domain,
        include_external=job.settings.follow_external_sources,
    )
    st.session_state.job_records = [record.to_dict() for record in records]
    st.session_state.job_entities = entities
    st.session_state.job_bundle = _STORAGE.bundle_job(job_id)
    st.session_state.benchmark_draft_bytes = b""
    st.session_state.benchmark_draft_file_name = ""
    st.session_state.benchmark_draft_summary = {}
    st.session_state.benchmark_draft_job_id = ""
    st.session_state.benchmark_report_json_bytes = b""
    st.session_state.benchmark_report_md_bytes = b""
    st.session_state.benchmark_report_summary = {}
    st.session_state.benchmark_report_rows = []
    st.session_state.benchmark_report_job_id = ""
    st.session_state.benchmark_report_name = ""
    st.session_state.benchmark_report_details = {}
    st.session_state.benchmark_editor_text = ""
    st.session_state.benchmark_editor_file_name = ""
    st.session_state.benchmark_editor_summary = {}
    st.session_state.benchmark_editor_job_id = ""


def _poll_queue() -> None:
    rq = st.session_state.result_queue
    batch = 0
    while batch < 20:
        try:
            event = rq.get_nowait()
        except queue.Empty:
            break

        if event["type"] == "page":
            record = event["record"]
            job_payload = event["job"]
            st.session_state.job_data = job_payload
            st.session_state.recent_records = ([record] + st.session_state.recent_records)[:50]
            processed = (
                job_payload.get("pages_scraped", 0)
                + job_payload.get("pages_failed", 0)
                + job_payload.get("pages_skipped", 0)
            )
            total = max(job_payload.get("pages_total", 0), processed)
            milestone = ((processed * 100) // total // 10) * 10 if total else 0
            marker_key = f"crawl-progress:{job_payload.get('job_id', '')}"
            if 10 <= milestone < 100 and activity_marker_changed(st.session_state, marker_key, milestone):
                log_activity(
                    st.session_state,
                    "crawl",
                    f"Crawl job `{job_payload.get('job_id', '')}` reached {milestone}%",
                    details=f"{processed}/{total} pages processed",
                )
        elif event["type"] == "job":
            job_payload = event["job"]
            st.session_state.job_data = job_payload
            status = job_payload.get("status", "")
            marker_key = f"crawl-status:{job_payload.get('job_id', '')}"
            if status and activity_marker_changed(st.session_state, marker_key, status):
                log_activity(
                    st.session_state,
                    "crawl",
                    f"Crawl job `{job_payload.get('job_id', '')}` entered `{status}`",
                    details=f"Domain: {job_payload.get('domain', '')}",
                )
        elif event["type"] == "complete":
            job_payload = event["job"]
            st.session_state.job_data = job_payload
            st.session_state.crawl_running = False
            final_status = job_payload.get("status", "")
            marker_key = f"crawl-complete:{job_payload.get('job_id', '')}"
            if final_status and activity_marker_changed(st.session_state, marker_key, final_status):
                level = "success" if final_status == "completed" else ("warning" if final_status == "cancelled" else "error")
                log_activity(
                    st.session_state,
                    "crawl",
                    f"Crawl job `{job_payload.get('job_id', '')}` {final_status}",
                    level=level,
                    details=(
                        f"Scraped: {job_payload.get('pages_scraped', 0)} | "
                        f"Failed: {job_payload.get('pages_failed', 0)} | "
                        f"Skipped: {job_payload.get('pages_skipped', 0)}"
                    ),
                )
            _load_job_outputs(st.session_state.job_id)
            st.rerun()
        batch += 1


def _render_job_summary() -> None:
    job = st.session_state.job_data or {}
    if not job:
        return

    st.subheader("Job Summary")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Status", job.get("status", ""))
    c2.metric("Seed URLs", job.get("seed_count", 0))
    c3.metric("Scraped", job.get("pages_scraped", 0))
    c4.metric("Failed", job.get("pages_failed", 0))
    c5.metric("Skipped", job.get("pages_skipped", 0))
    c6.metric("External", job.get("external_pages", 0))

    c7, c8, c9 = st.columns(3)
    c7.metric("Words", f"{job.get('total_words', 0):,}")
    c8.metric("LLM.txt", "Found" if job.get("llm_txt_found") else "Not found")
    c9.metric("Robots.txt", "Found" if job.get("robots_txt_found") else "Not found")

    if job.get("warnings"):
        for warning in job["warnings"]:
            st.warning(warning)
    if job.get("errors"):
        for error in job["errors"]:
            st.error(error)

    st.caption(f"Job ID: `{job.get('job_id', '')}`")
    st.caption(f"Output: `{job.get('output_dir', '')}`")


def _render_recent_records() -> None:
    if not st.session_state.recent_records:
        return
    st.subheader("Live Feed")
    table = []
    for record in st.session_state.recent_records[:20]:
        table.append({
            "URL": record["url"],
            "Category": record["page_category"],
            "Status": record["status"],
            "Words": record["word_count"],
            "Engine": record["engine_used"],
        })
    st.dataframe(table, use_container_width=True)


def _apply_external_review(job_id: str, urls: list[str], status: str) -> None:
    if not job_id or not urls:
        return
    records = _STORAGE.load_page_records(job_id)
    by_url = {record.url: record for record in records}
    changed = False
    for url in urls:
        record = by_url.get(url)
        if not record or record.source_type != "external":
            continue
        if external_review_status(record) == status:
            continue
        set_external_review_status(record, status)
        _STORAGE.save_page_record(job_id, record)
        changed = True
    if changed:
        log_activity(
            st.session_state,
            "review",
            f"Updated {len(urls)} external sources to `{status}` for `{job_id}`",
        )
        JobRunner(redis_url=REDIS_URL, storage=_STORAGE).refresh_outputs(job_id)
        _auto_refresh_indexed_targets(job_id)
        _load_job_outputs(job_id)


def _auto_refresh_indexed_targets(job_id: str) -> None:
    job = _STORAGE.load_job(job_id)
    settings = ensure_session_settings(st.session_state)
    for target in _REGISTRY.list_targets():
        if target.get("job_id") != job_id or target.get("source_kind") != "company_job":
            continue
        backend = target.get("embedding_backend") or "local"
        api_key = ""
        ollama_url = target.get("embedding_ollama_url") or settings.get("ollama_url", default_ollama_url())
        if backend == "openai":
            api_key = settings.get("embedding_api_key", "")
            if not api_key:
                job.warnings = sorted(set(job.warnings + [
                    f"Skipped auto-refresh for `{target.get('collection_name', '')}` because no OpenAI embedding API key is configured in Settings."
                ]))
                log_activity(
                    st.session_state,
                    "index",
                    f"Skipped auto-refresh for `{target.get('collection_name', '')}`",
                    level="warning",
                    details="Missing OpenAI embedding API key in Settings",
                )
                continue
        try:
            embedder = Embedder(
                backend=backend,
                api_key=api_key or None,
                model=target.get("embedding_model") or None,
                ollama_url=ollama_url,
            )
            pipeline = IndexerPipeline(
                collection_name=target["collection_name"],
                embedder=embedder,
                qdrant_url=QDRANT_URL,
                storage=_STORAGE,
            )
            for progress in pipeline.replace_job_collection(
                job_id,
                include_external=bool(target.get("include_external")),
            ):
                if progress.error:
                    raise RuntimeError(progress.error)
            refreshed_target = dict(target)
            refreshed_target["indexed_at"] = None
            refreshed_target["stats"] = pipeline.get_stats()
            _REGISTRY.save_target(refreshed_target)
            log_activity(
                st.session_state,
                "index",
                f"Auto-refreshed indexed corpus `{target.get('collection_name', '')}`",
                level="success",
                details=f"Job: {job_id}",
            )
        except Exception as exc:
            job.warnings = sorted(set(job.warnings + [
                f"Auto-refresh failed for `{target.get('collection_name', '')}`: {exc}"
            ]))
            log_activity(
                st.session_state,
                "index",
                f"Auto-refresh failed for `{target.get('collection_name', '')}`",
                level="error",
                details=str(exc),
            )
    _STORAGE.save_job(job)


def _external_review_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        if record.get("source_type") != "external":
            continue
        metadata = record.get("metadata") or {}
        rows.append({
            "Score": int(metadata.get("review_score", 0) or 0),
            "Review Status": external_review_status(record),
            "Discovery": record.get("discovered_via", ""),
            "Domain": record.get("domain", ""),
            "Category": record.get("page_category", ""),
            "Status": record.get("status", ""),
            "Provider": metadata.get("search_provider", ""),
            "Query Type": metadata.get("search_kind", ""),
            "Rank": metadata.get("search_rank", ""),
            "URL": record.get("url", ""),
            "Why": metadata.get("review_reason", ""),
            "Query": metadata.get("search_query", ""),
        })
    return rows


def _render_external_sources(records: list[dict]) -> None:
    rows = _external_review_rows(records)
    if not rows:
        return

    st.subheader("External Source Review")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("External pages", len(rows))
    c2.metric("Approved", sum(1 for row in rows if row["Review Status"] == "approved"))
    c3.metric("Pending", sum(1 for row in rows if row["Review Status"] == "pending"))
    c4.metric("Rejected", sum(1 for row in rows if row["Review Status"] == "rejected"))
    c5.metric("Successful", sum(1 for row in rows if row["Status"] == "success"))

    available_domains = sorted({row["Domain"] for row in rows if row["Domain"]})
    f1, f2, f3, f4, f5 = st.columns(5)
    discovery = f1.selectbox(
        "Discovery filter",
        ["All", "search", "site-external-link"],
        key="external_discovery_filter",
    )
    review_status = f2.selectbox(
        "Review filter",
        ["All", "approved", "pending", "rejected"],
        key="external_review_status_filter",
    )
    status = f3.selectbox(
        "Fetch status",
        ["All"] + sorted({row["Status"] for row in rows if row["Status"]}),
        key="external_status_filter",
    )
    selected_domains = f4.multiselect(
        "Domains",
        options=available_domains,
        default=[],
        key="external_domain_filter",
    )
    min_score = f5.slider(
        "Minimum score",
        min_value=0,
        max_value=100,
        value=0,
        key="external_score_filter",
    )

    filtered = []
    for row in rows:
        if discovery != "All" and row["Discovery"] != discovery:
            continue
        if review_status != "All" and row["Review Status"] != review_status:
            continue
        if status != "All" and row["Status"] != status:
            continue
        if selected_domains and row["Domain"] not in selected_domains:
            continue
        if row["Score"] < min_score:
            continue
        filtered.append(row)

    filtered.sort(key=lambda row: (-row["Score"], row["Domain"], row["URL"]))
    if not filtered:
        st.info("No external sources match the current review filters.")
        return

    st.caption("Only external sources marked `approved` are included in exports and future indexing runs.")
    st.dataframe(filtered[:200], use_container_width=True)

    review_choices = {row["URL"]: f"{row['Review Status']} | {row['Score']} | {row['Domain']} | {row['URL']}" for row in filtered}
    selected_urls = st.multiselect(
        "Selected external sources",
        options=list(review_choices),
        format_func=lambda url: review_choices[url],
        key="external_review_targets",
    )
    action1, action2, action3 = st.columns(3)
    if action1.button("Approve Selected", disabled=not selected_urls, key="approve_external_sources"):
        _apply_external_review(st.session_state.job_id, selected_urls, "approved")
        st.rerun()
    if action2.button("Reject Selected", disabled=not selected_urls, key="reject_external_sources"):
        _apply_external_review(st.session_state.job_id, selected_urls, "rejected")
        st.rerun()
    if action3.button("Reset To Pending", disabled=not selected_urls, key="pending_external_sources"):
        _apply_external_review(st.session_state.job_id, selected_urls, "pending")
        st.rerun()


def _safe_benchmark_filename(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower()
    return slug or "benchmark"


def _benchmark_repo_file_name(value: str) -> str:
    candidate = Path(str(value or "").strip() or "benchmark.json").name
    stem = Path(candidate).stem or "benchmark"
    return f"{_safe_benchmark_filename(stem)}.json"


def _normalize_benchmark_payload(benchmark_payload: bytes | str) -> tuple[BenchmarkCase, bytes, dict[str, int]]:
    if isinstance(benchmark_payload, str):
        benchmark_payload = benchmark_payload.encode("utf-8")
    payload = json.loads(benchmark_payload.decode("utf-8"))
    benchmark = BenchmarkCase.from_dict(payload)
    normalized = json.dumps(benchmark.to_dict(), indent=2, sort_keys=True).encode("utf-8")
    summary = {key: len(values) for key, values in benchmark.entities.items()}
    return benchmark, normalized, summary


def _load_benchmark_editor_payload(benchmark_payload: bytes, file_name: str, *, job_id: str = "") -> None:
    _benchmark, normalized, summary = _normalize_benchmark_payload(benchmark_payload)
    st.session_state.benchmark_editor_text = normalized.decode("utf-8")
    st.session_state.benchmark_editor_file_name = _benchmark_repo_file_name(file_name)
    st.session_state.benchmark_editor_summary = summary
    st.session_state.benchmark_editor_job_id = job_id


def _save_curated_benchmark(
    benchmark_payload: bytes | str,
    file_name: str,
    *,
    benchmarks_dir: Path | None = None,
) -> tuple[Path, dict[str, int]]:
    benchmark, normalized, summary = _normalize_benchmark_payload(benchmark_payload)
    output_dir = benchmarks_dir or _BENCHMARKS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = _benchmark_repo_file_name(file_name or benchmark.company_domain or benchmark.name)
    output_path = output_dir / output_name
    output_path.write_bytes(normalized)
    return output_path, summary


def _build_benchmark_draft_payload(
    job_id: str,
    *,
    limit_per_type: int = 25,
    entity_types: list[str] | None = None,
    storage: JobStorage | None = None,
) -> tuple[str, bytes, dict[str, int]]:
    storage = storage or _STORAGE
    benchmark = build_job_benchmark_draft(
        job_id,
        storage=storage,
        limit_per_type=limit_per_type,
        entity_types=entity_types,
    )
    payload = json.dumps(benchmark.to_dict(), indent=2, sort_keys=True).encode("utf-8")
    filename = f"{_safe_benchmark_filename(benchmark.company_domain or benchmark.name)}-benchmark-draft.json"
    summary = {key: len(values) for key, values in benchmark.entities.items()}
    return filename, payload, summary


def _prepare_benchmark_draft(job_id: str, limit_per_type: int, entity_types: list[str]) -> None:
    filename, payload, summary = _build_benchmark_draft_payload(
        job_id,
        limit_per_type=limit_per_type,
        entity_types=entity_types or None,
    )
    _load_benchmark_editor_payload(payload, filename, job_id=job_id)
    st.session_state.benchmark_draft_bytes = payload
    st.session_state.benchmark_draft_file_name = filename
    st.session_state.benchmark_draft_summary = summary
    st.session_state.benchmark_draft_job_id = job_id
    log_activity(
        st.session_state,
        "benchmark",
        f"Generated benchmark draft for `{job_id}`",
        level="success",
        details=f"Entity types: {len(summary)} | Entries: {sum(summary.values())}",
    )


def _available_benchmark_files() -> list[Path]:
    if not _BENCHMARKS_DIR.exists():
        return []
    return sorted(_BENCHMARKS_DIR.glob("*.json"))


def _benchmark_relative_name(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _benchmark_report_rows(report) -> list[dict]:
    rows = []
    for entity_type, entity_report in sorted(report.entity_types.items()):
        rows.append({
            "Entity Type": entity_type,
            "Gold": entity_report.gold_count,
            "Predicted": entity_report.predicted_count,
            "Matched": entity_report.matched_count,
            "Precision": entity_report.precision,
            "Recall": entity_report.recall,
            "F1": entity_report.f1,
            "Attribute Accuracy": entity_report.attribute_accuracy,
            "Source URL Accuracy": entity_report.source_url_accuracy,
            "Missing": len(entity_report.missing),
            "Unexpected": len(entity_report.unexpected),
        })
    return rows


def _benchmark_entity_detail(report_payload: dict, entity_type: str) -> dict[str, list]:
    entity_report = (report_payload.get("entity_types", {}) or {}).get(entity_type, {}) or {}
    match_rows = []
    for match in entity_report.get("matches", []) or []:
        match_rows.append({
            "Expected": match.get("expected_name", ""),
            "Predicted": match.get("predicted_name", ""),
            "Matched": "yes" if match.get("matched") else "",
            "Checks Passed": f"{match.get('passed_check_count', 0)}/{match.get('total_check_count', 0)}",
            "Source URL Checks": f"{match.get('source_url_passed', 0)}/{match.get('source_url_total', 0)}",
            "Failed Checks": ", ".join(match.get("failed_checks", []) or []),
            "Notes": match.get("expected_notes", ""),
        })
    return {
        "matches": match_rows,
        "missing": list(entity_report.get("missing", []) or []),
        "unexpected": list(entity_report.get("unexpected", []) or []),
    }


def _evaluate_benchmark_payload(
    job_id: str,
    benchmark_payload: bytes,
    benchmark_label: str,
    *,
    storage: JobStorage | None = None,
) -> dict:
    storage = storage or _STORAGE
    payload = json.loads(benchmark_payload.decode("utf-8"))
    benchmark = BenchmarkCase.from_dict(payload)
    report = evaluate_job(job_id, benchmark, storage=storage)
    report_dir = storage.job_dir(job_id) / "exports" / "evaluation" / _safe_benchmark_filename(benchmark.name or benchmark_label)
    benchmark_path = report_dir / "benchmark_input.json"
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(json.dumps(benchmark.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    json_path, markdown_path = write_report(report, report_dir)
    return {
        "benchmark_name": report.benchmark_name,
        "overall": report.overall(),
        "rows": _benchmark_report_rows(report),
        "details": report.to_dict(),
        "json_bytes": json_path.read_bytes(),
        "markdown_bytes": markdown_path.read_bytes(),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "benchmark_path": str(benchmark_path),
    }


def _prepare_benchmark_report(job_id: str, benchmark_payload: bytes, benchmark_label: str) -> None:
    result = _evaluate_benchmark_payload(job_id, benchmark_payload, benchmark_label)
    st.session_state.benchmark_report_json_bytes = result["json_bytes"]
    st.session_state.benchmark_report_md_bytes = result["markdown_bytes"]
    st.session_state.benchmark_report_summary = result["overall"]
    st.session_state.benchmark_report_rows = result["rows"]
    st.session_state.benchmark_report_job_id = job_id
    st.session_state.benchmark_report_name = result["benchmark_name"]
    st.session_state.benchmark_report_details = result["details"]
    log_activity(
        st.session_state,
        "benchmark",
        f"Evaluated benchmark `{result['benchmark_name']}` for `{job_id}`",
        level="success",
        details=(
            f"Precision: {result['overall']['precision']:.4f} | "
            f"Recall: {result['overall']['recall']:.4f} | "
            f"F1: {result['overall']['f1']:.4f}"
        ),
    )


def _render_benchmark_draft() -> None:
    if not st.session_state.job_id or not st.session_state.job_entities:
        return

    st.subheader("Benchmark Draft")
    st.caption("Generate a draft benchmark JSON from the extracted entities, then curate it into gold data before scoring.")
    entity_options = [key for key, values in st.session_state.job_entities.items() if values]
    if not entity_options:
        st.info("No extracted entities are available yet for benchmark drafting.")
        return

    default_types = [key for key in ("services", "industries", "case_studies", "partners", "customers", "people", "events") if key in entity_options]
    selected_types = st.multiselect(
        "Entity types",
        options=entity_options,
        default=default_types or entity_options,
        key="benchmark_draft_entity_types",
    )
    limit_per_type = st.slider(
        "Draft entries per type",
        min_value=1,
        max_value=50,
        value=25,
        key="benchmark_draft_limit",
    )
    if st.button("Generate Benchmark Draft", key="generate_benchmark_draft"):
        _prepare_benchmark_draft(st.session_state.job_id, int(limit_per_type), selected_types)
        st.rerun()

    if st.session_state.get("benchmark_draft_job_id") != st.session_state.job_id:
        return

    summary = st.session_state.get("benchmark_draft_summary") or {}
    if summary:
        st.write(summary)
    payload = st.session_state.get("benchmark_draft_bytes") or b""
    filename = st.session_state.get("benchmark_draft_file_name") or "benchmark-draft.json"
    if payload:
        st.download_button(
            "Download Benchmark Draft",
            data=payload,
            file_name=filename,
            mime="application/json",
            key="download_benchmark_draft",
        )


def _render_benchmark_editor() -> None:
    if not st.session_state.job_id or not st.session_state.job_entities:
        return

    st.subheader("Benchmark Curation")
    st.caption("Edit the generated draft into reviewed gold data, validate it, and save it under `benchmarks/` for repeatable scoring.")

    if st.session_state.get("benchmark_draft_job_id") != st.session_state.job_id:
        st.info("Generate a benchmark draft first, then curate it here.")
        return

    if not st.session_state.get("benchmark_editor_text"):
        draft_payload = st.session_state.get("benchmark_draft_bytes") or b""
        draft_name = st.session_state.get("benchmark_draft_file_name") or "benchmark-draft.json"
        if draft_payload:
            _load_benchmark_editor_payload(draft_payload, draft_name, job_id=st.session_state.job_id)

    st.text_input(
        "Benchmark file name",
        key="benchmark_editor_file_name",
        help="Saved under benchmarks/ with a sanitized .json file name.",
    )
    st.text_area(
        "Curated benchmark JSON",
        key="benchmark_editor_text",
        height=360,
    )

    raw_text = st.session_state.get("benchmark_editor_text", "")
    validation_error = ""
    normalized_payload = b""
    summary: dict[str, int] = {}
    if raw_text.strip():
        try:
            _benchmark, normalized_payload, summary = _normalize_benchmark_payload(raw_text)
        except Exception as exc:
            validation_error = str(exc)

    if st.session_state.get("benchmark_editor_summary"):
        st.write(st.session_state["benchmark_editor_summary"])

    action1, action2, action3 = st.columns(3)
    if action1.button("Validate Curated Benchmark", key="validate_curated_benchmark", disabled=not raw_text.strip()):
        if validation_error:
            st.error(f"Benchmark validation failed: {validation_error}")
        else:
            st.session_state.benchmark_editor_text = normalized_payload.decode("utf-8")
            st.session_state.benchmark_editor_summary = summary
            log_activity(
                st.session_state,
                "benchmark",
                f"Validated curated benchmark for `{st.session_state.job_id}`",
                level="success",
                details=f"Entity types: {len(summary)} | Entries: {sum(summary.values())}",
            )
            st.success("Benchmark JSON is valid.")

    if action2.button("Save Curated Benchmark", key="save_curated_benchmark", disabled=not raw_text.strip()):
        if validation_error:
            st.error(f"Benchmark validation failed: {validation_error}")
        else:
            output_path, saved_summary = _save_curated_benchmark(
                normalized_payload,
                st.session_state.get("benchmark_editor_file_name", ""),
            )
            st.session_state.benchmark_editor_text = normalized_payload.decode("utf-8")
            st.session_state.benchmark_editor_file_name = output_path.name
            st.session_state.benchmark_editor_summary = saved_summary
            log_activity(
                st.session_state,
                "benchmark",
                f"Saved curated benchmark `{output_path.name}`",
                level="success",
                details=f"Path: {output_path}",
            )
            st.success(f"Saved benchmark to `{output_path}`")

    if normalized_payload:
        action3.download_button(
            "Download Curated Benchmark",
            data=normalized_payload,
            file_name=_benchmark_repo_file_name(st.session_state.get("benchmark_editor_file_name", "")),
            mime="application/json",
            key="download_curated_benchmark",
        )
    elif validation_error:
        st.caption(f"Current editor content is not valid JSON for benchmark scoring: {validation_error}")


def _render_benchmark_evaluation() -> None:
    if not st.session_state.job_id or not st.session_state.job_entities:
        return

    st.subheader("Benchmark Evaluation")
    st.caption("Score this completed job against a curated benchmark JSON and review per-entity-type accuracy.")

    benchmark_files = _available_benchmark_files()
    source_options = []
    if benchmark_files:
        source_options.append("Repository benchmark")
    source_options.append("Upload benchmark JSON")
    source_mode = st.radio(
        "Benchmark source",
        source_options,
        horizontal=True,
        key="benchmark_eval_source_mode",
    )

    benchmark_payload = b""
    benchmark_label = ""

    if source_mode == "Repository benchmark":
        selected_path = st.selectbox(
            "Benchmark file",
            options=benchmark_files,
            format_func=lambda path: _benchmark_relative_name(path),
            key="benchmark_eval_file",
        )
        benchmark_payload = selected_path.read_bytes()
        benchmark_label = _benchmark_relative_name(selected_path)
    else:
        uploaded = st.file_uploader(
            "Upload benchmark JSON",
            type=["json"],
            key="benchmark_eval_upload",
        )
        if uploaded is not None:
            benchmark_payload = uploaded.getvalue()
            benchmark_label = uploaded.name

    if st.button("Run Benchmark Evaluation", key="run_benchmark_evaluation", disabled=not benchmark_payload):
        try:
            _prepare_benchmark_report(st.session_state.job_id, benchmark_payload, benchmark_label or "uploaded benchmark")
            st.rerun()
        except Exception as exc:
            log_activity(
                st.session_state,
                "benchmark",
                f"Benchmark evaluation failed for `{st.session_state.job_id}`",
                level="error",
                details=str(exc),
            )
            st.error(f"Benchmark evaluation failed: {exc}")

    if st.session_state.get("benchmark_report_job_id") != st.session_state.job_id:
        return

    summary = st.session_state.get("benchmark_report_summary") or {}
    rows = st.session_state.get("benchmark_report_rows") or []
    if not summary or not rows:
        return

    st.caption(f"Benchmark: `{st.session_state.get('benchmark_report_name', '')}`")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Precision", f"{summary.get('precision', 0.0):.4f}")
    c2.metric("Recall", f"{summary.get('recall', 0.0):.4f}")
    c3.metric("F1", f"{summary.get('f1', 0.0):.4f}")
    c4.metric("Matched", f"{summary.get('matched_count', 0)}/{summary.get('gold_count', 0)}")
    c5, c6 = st.columns(2)
    c5.metric("Attribute Accuracy", f"{summary.get('attribute_accuracy', 0.0):.4f}")
    c6.metric("Source URL Accuracy", f"{summary.get('source_url_accuracy', 0.0):.4f}")
    st.dataframe(rows, use_container_width=True, hide_index=True)

    detail_payload = st.session_state.get("benchmark_report_details") or {}
    detail_types = list((detail_payload.get("entity_types", {}) or {}).keys())
    if detail_types:
        selected_detail_type = st.selectbox(
            "Entity type detail",
            options=detail_types,
            key="benchmark_report_detail_type",
        )
        detail = _benchmark_entity_detail(detail_payload, selected_detail_type)
        st.caption(f"Detail for `{selected_detail_type}`")
        if detail["matches"]:
            st.dataframe(detail["matches"], use_container_width=True, hide_index=True)
        if detail["missing"]:
            st.write({"Missing expected entities": detail["missing"]})
        if detail["unexpected"]:
            st.write({"Unexpected predicted entities": detail["unexpected"]})

    json_bytes = st.session_state.get("benchmark_report_json_bytes") or b""
    md_bytes = st.session_state.get("benchmark_report_md_bytes") or b""
    if json_bytes or md_bytes:
        d1, d2 = st.columns(2)
        if json_bytes:
            d1.download_button(
                "Download Benchmark Report JSON",
                data=json_bytes,
                file_name=f"{_safe_benchmark_filename(st.session_state.get('benchmark_report_name', 'benchmark'))}-report.json",
                mime="application/json",
                key="download_benchmark_report_json",
            )
        if md_bytes:
            d2.download_button(
                "Download Benchmark Report Markdown",
                data=md_bytes,
                file_name=f"{_safe_benchmark_filename(st.session_state.get('benchmark_report_name', 'benchmark'))}-report.md",
                mime="text/markdown",
                key="download_benchmark_report_md",
            )


def _render_outputs() -> None:
    if not st.session_state.job_id or st.session_state.crawl_running:
        return

    job_dir = _STORAGE.job_dir(st.session_state.job_id)
    excel_path = job_dir / "exports" / "intel.xlsx"
    entities_path = job_dir / "exports" / "entities.json"
    corpus_path = job_dir / "exports" / "corpus.jsonl"

    if any(path.exists() for path in (excel_path, entities_path, corpus_path)):
        st.subheader("Downloads")
        col1, col2, col3, col4 = st.columns(4)
        if excel_path.exists():
            col1.download_button(
                "Download Excel",
                data=excel_path.read_bytes(),
                file_name=f"{st.session_state.job_id}-intel.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if entities_path.exists():
            col2.download_button(
                "Download Entities JSON",
                data=entities_path.read_bytes(),
                file_name=f"{st.session_state.job_id}-entities.json",
                mime="application/json",
            )
        if corpus_path.exists():
            col3.download_button(
                "Download Corpus JSONL",
                data=corpus_path.read_bytes(),
                file_name=f"{st.session_state.job_id}-corpus.jsonl",
                mime="application/json",
            )
        if st.session_state.job_bundle:
            col4.download_button(
                "Download Job Bundle",
                data=st.session_state.job_bundle,
                file_name=f"{st.session_state.job_id}.zip",
                mime="application/zip",
            )

    records = st.session_state.job_records
    if records:
        st.subheader("Corpus Overview")
        counts = Counter(record["page_category"] for record in records)
        st.write(dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))))

        preview = []
        for record in sorted(records, key=lambda item: item["url"])[:50]:
            preview.append({
                "URL": record["url"],
                "Category": record["page_category"],
                "Subtype": record["page_subtype"],
                "Source": record["source_type"],
                "Status": record["status"],
                "Words": record["word_count"],
                "Engine": record["engine_used"],
                "Duplicate": "yes" if record["is_duplicate"] else "",
            })
        st.dataframe(preview, use_container_width=True)
        _render_external_sources(records)

    entities = st.session_state.job_entities
    if entities:
        st.subheader("Extracted Entities")
        summary = {key: len(value) for key, value in entities.items()}
        st.write(summary)
        with st.expander("Quality & Benchmark Tools", expanded=False):
            _render_benchmark_draft()
            _render_benchmark_editor()
            _render_benchmark_evaluation()


def scrape_page() -> None:
    _ensure_state()

    st.title("Company Intelligence Collector")
    st.caption("Crawl a company website into a mirrored corpus, classify pages, gather public external sources, and generate structured exports.")
    st.info("Start with a company homepage URL. When the crawl completes, you can review the extracted data, download exports, build a search index, and chat against the results.")

    jobs = [job.to_dict() for job in _STORAGE.list_jobs()]
    if jobs and not st.session_state.crawl_running:
        st.subheader("Open Saved Job")
        default_job_id = st.session_state.get("selected_job_id", "")
        job_ids = [job["job_id"] for job in jobs]
        selected_index = job_ids.index(default_job_id) if default_job_id in job_ids else 0
        load_col1, load_col2 = st.columns([4, 1])
        selected_job_id = load_col1.selectbox(
            "Inspect existing job",
            options=job_ids,
            index=selected_index,
            format_func=lambda job_id: _job_option_label(next(job for job in jobs if job["job_id"] == job_id)),
        )
        if load_col2.button("Load Job"):
            _load_job_outputs(selected_job_id)
            st.rerun()

    st.subheader("Start New Crawl")
    with st.form("crawl_form"):
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            url_input = st.text_input("Target URL", placeholder="https://example.com")
        with col2:
            max_pages = st.number_input("Max pages", min_value=10, max_value=5000, value=500, step=50)
        with col3:
            rate_limit = st.number_input("Rate limit (s)", min_value=0.5, max_value=10.0, value=1.0, step=0.5)

        opt1, opt2 = st.columns(2)
        with opt1:
            follow_external_sources = st.checkbox("Collect external public sources", value=True)
        with opt2:
            ignore_robots = st.checkbox("Ignore robots/llm exclusions", value=True)

        submitted = st.form_submit_button("Start Crawl Job", disabled=st.session_state.crawl_running)

    if submitted and url_input:
        if not url_input.startswith(("http://", "https://")):
            st.error("Enter a full URL starting with http:// or https://")
        else:
            _start_job(
                start_url=url_input.strip(),
                max_pages=int(max_pages),
                rate_limit=float(rate_limit),
                follow_external_sources=follow_external_sources,
                ignore_robots=ignore_robots,
            )
            st.rerun()

    _render_job_summary()
    _render_recent_records()
    _render_outputs()

    if st.session_state.crawl_running and st.session_state.result_queue:
        col_a, col_b = st.columns(2)
        if col_a.button("Cancel Crawl"):
            st.session_state.cancel_flag.append(True)
            log_activity(
                st.session_state,
                "crawl",
                f"Cancellation requested for crawl job `{st.session_state.job_id}`",
                level="warning",
            )
        if col_b.button("Refresh Now"):
            _poll_queue()
            st.rerun()

        _poll_queue()
        if st.session_state.crawl_running:
            time.sleep(0.3)
            st.rerun()
