# pages/index_page.py
"""Index completed company-intel jobs into Qdrant."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from activity_log import log_activity
from app_settings import (
    default_ollama_url,
    embedding_model_defaults,
    ensure_session_settings,
    standalone_container_runtime_hint,
)
from company_intel.storage import JobStorage, collection_name_for_job
from indexer.embedder import Embedder
from indexer.pipeline import IndexerPipeline, _is_indexable_record
from indexer.qdrant_status import (
    QdrantCollectionsStatus,
    fetch_qdrant_collections_status,
    qdrant_state_label,
    stale_registry_target_ids,
    tracked_target_state,
)
from indexer.registry import IndexRegistry


QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_STORAGE = JobStorage()
_REGISTRY = IndexRegistry()
_DISPLAY_TIMEZONE = os.environ.get("APP_TIMEZONE") or os.environ.get("TZ") or "America/New_York"
_EMBEDDING_BACKEND_OPTIONS = ["ollama", "openai", "local"]
_EMBEDDING_BACKEND_LABELS = {
    "ollama": "Bundled Ollama",
    "openai": "OpenAI API",
    "local": "Advanced local model",
}
_DEFAULT_EMBEDDING_MODELS = {
    "ollama": embedding_model_defaults()["ollama"],
    "openai": embedding_model_defaults()["openai"],
    "local": embedding_model_defaults()["local"],
}


def _display_tz() -> ZoneInfo:
    try:
        return ZoneInfo(_DISPLAY_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _format_timestamp_local(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        return value
    return dt.astimezone(_display_tz()).strftime("%Y-%m-%d %H:%M:%S %Z")


def _summarize_indexable_pages(job_id: str, include_external: bool) -> dict:
    source_type = None if include_external else "internal"
    category_counts: dict[str, int] = {}
    indexable_pages = 0
    for record in _STORAGE.iter_page_records(job_id, source_type=source_type):
        if not _is_indexable_record(record, include_external=include_external):
            continue
        indexable_pages += 1
        category = record.page_category or "other"
        category_counts[category] = category_counts.get(category, 0) + 1
    ordered_counts = dict(sorted(category_counts.items(), key=lambda item: (-item[1], item[0])))
    return {
        "indexable_pages": indexable_pages,
        "category_counts": ordered_counts,
    }


def _ensure_index_state() -> None:
    defaults = {
        "indexed_targets": [],
        "selected_job_id": "",
        "active_rag_target_id": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    _sync_registry_targets()


def _job_index_status_rows(
    completed_jobs: list,
    indexed_targets: list[dict],
    qdrant_status: QdrantCollectionsStatus,
) -> list[dict]:
    indexed_lookup = {
        (item.get("job_id", ""), bool(item.get("include_external", True))): item
        for item in indexed_targets
        if item.get("job_id")
    }
    rows = []
    for job in completed_jobs:
        internal = indexed_lookup.get((job.job_id, False))
        full = indexed_lookup.get((job.job_id, True))
        internal_status = qdrant_state_label(tracked_target_state(internal, qdrant_status))
        full_status = qdrant_state_label(tracked_target_state(full, qdrant_status))
        latest = max(
            [value.get("indexed_at", "") for value in (internal, full) if value],
            default="",
        )
        rows.append({
            "Domain": job.domain,
            "Job ID": job.job_id,
            "Pages": job.pages_scraped,
            "Internal Only": internal_status,
            "Internal + External": full_status,
            "Last Indexed": _format_timestamp_local(latest) if latest else "",
        })
    return rows


def _job_label(job) -> str:
    created = job.created_at.replace("T", " ")[:19]
    return f"{job.domain} | {job.pages_scraped} pages | {created} | {job.job_id}"


def _remember_index_target(target: dict) -> None:
    targets = {
        item["target_id"]: item
        for item in st.session_state.get("indexed_targets", [])
        if item.get("target_id")
    }
    targets[target["target_id"]] = target
    st.session_state.indexed_targets = list(targets.values())
    st.session_state.active_rag_target_id = target["target_id"]
    if target.get("job_id"):
        st.session_state.selected_job_id = target["job_id"]


def _sync_registry_targets() -> None:
    registry_targets = _REGISTRY.list_targets()
    st.session_state.indexed_targets = list(registry_targets)
    active_target = st.session_state.get("active_rag_target_id", "")
    target_ids = {item.get("target_id", "") for item in registry_targets}
    if active_target not in target_ids:
        st.session_state.active_rag_target_id = registry_targets[0]["target_id"] if registry_targets else ""


def index_page() -> None:
    _ensure_index_state()

    st.title("Index")
    st.caption("Turn a completed crawl into a searchable knowledge base for retrieval and chat.")
    st.info("Recommended path: use the bundled Ollama embedding model in Docker. OpenAI and local sentence-transformer models remain optional.")
    docker_hint = standalone_container_runtime_hint()
    if docker_hint:
        st.info(docker_hint)
    settings = ensure_session_settings(st.session_state)

    completed_jobs = _STORAGE.list_jobs(status="completed")
    jobs_by_id = {job.job_id: job for job in completed_jobs}
    indexed_targets = st.session_state.get("indexed_targets", [])
    qdrant_status = fetch_qdrant_collections_status(QDRANT_URL)
    stale_target_ids = stale_registry_target_ids(indexed_targets, qdrant_status)

    if not qdrant_status.reachable:
        st.warning("Qdrant is unavailable. Indexed collection status cannot be verified and new indexing is blocked until Qdrant is reachable.")
        if qdrant_status.error:
            st.caption(f"Qdrant error: {qdrant_status.error}")

    if indexed_targets:
        with st.expander("Existing Indexes", expanded=False):
            preview = []
            for item in indexed_targets[:10]:
                preview.append({
                    "Label": item.get("label", ""),
                    "Collection": item.get("collection_name", ""),
                    "Status": qdrant_state_label(tracked_target_state(item, qdrant_status)),
                    "Kind": item.get("source_kind", ""),
                    "Indexed at": _format_timestamp_local(item.get("indexed_at", "")),
                })
            st.dataframe(preview, use_container_width=True, hide_index=True)
            if stale_target_ids:
                st.caption(f"{len(stale_target_ids)} tracked index entries are stale because their collections are missing from Qdrant.")
                if st.button("Remove Missing Registry Entries"):
                    removed = _REGISTRY.remove_targets(stale_target_ids)
                    _sync_registry_targets()
                    st.success(f"Removed {removed} stale registry entr{'y' if removed == 1 else 'ies'}.")
                    st.rerun()
            elif indexed_targets and not qdrant_status.reachable:
                st.caption("Registry cleanup is unavailable until Qdrant is reachable.")

    if not completed_jobs:
        st.warning("No completed company-intel jobs are available yet.")
        return

    with st.expander("Job Index Status", expanded=True):
        st.dataframe(
            _job_index_status_rows(completed_jobs, indexed_targets, qdrant_status),
            use_container_width=True,
            hide_index=True,
        )

    default_job_id = st.session_state.get("selected_job_id", "")
    job_ids = [job.job_id for job in completed_jobs]
    selected_index = job_ids.index(default_job_id) if default_job_id in job_ids else 0
    selected_job_id = st.selectbox(
        "Completed crawl job",
        options=job_ids,
        index=selected_index,
        format_func=lambda job_id: _job_label(jobs_by_id[job_id]),
    )
    selected_job = jobs_by_id[selected_job_id]
    st.session_state.selected_job_id = selected_job_id

    include_external = st.checkbox(
        "Include approved external pages",
        value=selected_job.settings.follow_external_sources,
    )
    collection_name = collection_name_for_job(
        selected_job.job_id,
        selected_job.domain,
        include_external=include_external,
    )
    summary = _summarize_indexable_pages(
        selected_job_id,
        include_external=include_external,
    )
    indexable_pages = summary["indexable_pages"]
    category_counts = summary["category_counts"]

    st.info(
        f"Completed jobs: **{len(completed_jobs)}**. "
        f"Indexable pages for this job: **{indexable_pages}**."
    )
    if category_counts:
        st.write(category_counts)
    target = {
        "target_id": f"job:{selected_job.job_id}:{'full' if include_external else 'internal'}",
        "label": f"{selected_job.domain} ({'internal + approved external' if include_external else 'internal only'})",
        "collection_name": collection_name,
        "source_kind": "company_job",
        "job_id": selected_job.job_id,
        "domain": selected_job.domain,
        "include_external": include_external,
    }

    if not indexable_pages:
        st.warning("This job has no indexable pages after cleaning and deduplication.")
        return

    # --- Settings ---
    st.subheader("Embedding Settings")
    backend_defaults = {
        "local": "local",
        "ollama": "ollama",
        "openai": "openai",
    }
    backend = st.radio(
        "Embedding backend",
        _EMBEDDING_BACKEND_OPTIONS,
        horizontal=True,
        format_func=lambda key: _EMBEDDING_BACKEND_LABELS[key],
        index=_EMBEDDING_BACKEND_OPTIONS.index(backend_defaults.get(settings.get("embedding_backend", "ollama"), "ollama")),
    )

    api_key = None
    ollama_url = settings.get("ollama_url", default_ollama_url())
    default_model_name = _DEFAULT_EMBEDDING_MODELS[backend]
    saved_backend_label = backend_defaults.get(settings.get("embedding_backend", "ollama"), "ollama")
    saved_model = settings.get("embedding_model", "")
    model_name = saved_model if saved_model and saved_backend_label == backend else default_model_name
    if backend == "openai":
        api_key = st.text_input("OpenAI API Key", type="password",
                                placeholder="sk-...", value=settings.get("embedding_api_key", ""))
        model_name = st.text_input("Embedding Model", value=model_name)
        if not api_key:
            st.warning("Enter your OpenAI API key to proceed.")
            return
    elif backend == "ollama":
        ollama_url = st.text_input("Ollama Endpoint", value=ollama_url)
        model_name = st.text_input("Embedding Model", value=model_name)
        st.caption("Uses the bundled Docker Ollama server by default.")
    else:
        model_name = st.text_input("Embedding Model", value=model_name)
        st.caption("Advanced option. Requires `requirements-local.txt` and is not bundled in the default Docker image.")

    if st.button("Build Search Index", type="primary"):
        if not qdrant_status.reachable:
            details = f": {qdrant_status.error}" if qdrant_status.error else "."
            st.error(f"Qdrant is unavailable at `{QDRANT_URL}`{details}")
            if docker_hint:
                st.info(docker_hint)
            return
        embedder_backend = backend
        embedder = Embedder(
            backend=embedder_backend,
            api_key=api_key,
            model=model_name or None,
            ollama_url=ollama_url,
        )
        try:
            embedder.health_check()
        except Exception as exc:
            st.error(f"Embedding backend is not ready: {exc}")
            log_activity(
                st.session_state,
                "index",
                f"Indexing preflight failed for `{target['collection_name']}`",
                level="error",
                details=str(exc),
            )
            return
        pipeline = IndexerPipeline(
            collection_name=target["collection_name"],
            embedder=embedder,
            qdrant_url=QDRANT_URL,
            storage=_STORAGE,
        )
        log_activity(
            st.session_state,
            "index",
            f"Started indexing for `{target['collection_name']}`",
            details=(
                f"Corpus: {target['label']} | "
                f"Backend: {embedder_backend} | Model: {getattr(embedder, '_model_name', '')}"
            ),
        )

        progress_bar = st.progress(0)
        status_text = st.empty()
        had_error = False
        logged_milestones: set[int] = set()

        run_iter = pipeline.run_job(
            target["job_id"],
            include_external=target["include_external"],
        )
        if target["target_id"] in {item.get("target_id") for item in indexed_targets}:
            run_iter = pipeline.replace_job_collection(
                target["job_id"],
                include_external=target["include_external"],
            )

        for progress in run_iter:
            if progress.error:
                st.error(f"Indexing error: {progress.error}")
                log_activity(
                    st.session_state,
                    "index",
                    f"Indexing failed for `{target['collection_name']}`",
                    level="error",
                    details=progress.error,
                )
                had_error = True
                break
            if indexable_pages:
                pct = progress.pages_done / indexable_pages
                progress_bar.progress(min(pct, 1.0))
                status_text.text(
                    f"Processed {progress.pages_done}/{indexable_pages} pages and indexed "
                    f"{progress.chunks_done} chunks"
                )
                milestone = (int(pct * 100) // 25) * 25
                if 25 <= milestone < 100 and milestone not in logged_milestones:
                    logged_milestones.add(milestone)
                    log_activity(
                        st.session_state,
                        "index",
                        f"Indexing `{target['collection_name']}` reached {milestone}%",
                        details=f"{progress.pages_done}/{indexable_pages} pages",
                    )
            else:
                pct = progress.chunks_done / progress.chunks_total if progress.chunks_total else 0
                progress_bar.progress(min(pct, 1.0))
                status_text.text(f"Indexed {progress.chunks_done}/{progress.chunks_total} chunks")
                milestone = (int(pct * 100) // 25) * 25
                if 25 <= milestone < 100 and milestone not in logged_milestones:
                    logged_milestones.add(milestone)
                    log_activity(
                        st.session_state,
                        "index",
                        f"Indexing `{target['collection_name']}` reached {milestone}%",
                        details=f"{progress.chunks_done}/{progress.chunks_total} chunks",
                    )

        if had_error:
            return

        progress_bar.progress(1.0)
        status_text.text(
            f"Indexing complete. Processed {indexable_pages} pages and built the search collection."
        )

        # Show collection stats
        stats = None
        try:
            stats = pipeline.get_stats()
            col1, col2, col3 = st.columns(3)
            col1.metric("Total vectors", stats["total_vectors"])
            col2.metric("Dimensions", stats["dimensions"])
            col3.metric("Collection", stats["collection_name"])
        except Exception as exc:
            st.warning(f"Could not fetch collection stats: {exc}")

        stored_target = dict(target)
        stored_target["indexed_at"] = stored_target.get("indexed_at") or None
        stored_target["embedding_backend"] = embedder_backend
        stored_target["embedding_model"] = getattr(embedder, "_model_name", "")
        stored_target["embedding_ollama_url"] = ollama_url if embedder_backend == "ollama" else ""
        stored_target["dimensions"] = embedder.dimensions
        if stats:
            stored_target["stats"] = stats
        stored_target = _REGISTRY.save_target(stored_target)
        _remember_index_target(stored_target)
        total_vectors = stats["total_vectors"] if stats else 0
        log_activity(
            st.session_state,
            "index",
            f"Completed indexing for `{target['collection_name']}`",
            level="success",
            details=f"Vectors: {total_vectors} | Dimensions: {stored_target['dimensions']}",
        )
