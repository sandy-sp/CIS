# pages/index_page.py
"""Index completed company-intel jobs into Qdrant."""
from collections import Counter
import os

import streamlit as st

from activity_log import log_activity
from app_settings import default_ollama_url, embedding_model_defaults, ensure_session_settings
from company_intel.storage import JobStorage, collection_name_for_job
from indexer.embedder import Embedder
from indexer.pipeline import IndexerPipeline, _is_indexable_record
from indexer.registry import IndexRegistry


QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_STORAGE = JobStorage()
_REGISTRY = IndexRegistry()
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


def _ensure_index_state() -> None:
    defaults = {
        "indexed_targets": [],
        "selected_job_id": "",
        "active_rag_target_id": "",
        "collection_name": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    _sync_registry_targets()


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
    st.session_state.collection_name = target["collection_name"]
    if target.get("job_id"):
        st.session_state.selected_job_id = target["job_id"]


def _sync_registry_targets() -> None:
    registry_targets = _REGISTRY.list_targets()
    merged = {
        item["target_id"]: item
        for item in st.session_state.get("indexed_targets", [])
        if item.get("target_id")
    }
    for item in registry_targets:
        merged[item["target_id"]] = item
    if merged:
        ordered = sorted(
            merged.values(),
            key=lambda item: item.get("indexed_at", ""),
            reverse=True,
        )
        st.session_state.indexed_targets = ordered
        if not st.session_state.get("active_rag_target_id"):
            st.session_state.active_rag_target_id = ordered[0]["target_id"]


def index_page() -> None:
    _ensure_index_state()

    st.title("Index")
    st.caption("Turn a completed crawl into a searchable knowledge base for retrieval and chat.")
    st.info("Recommended path: use the bundled Ollama embedding model in Docker. OpenAI and local sentence-transformer models remain optional.")
    settings = ensure_session_settings(st.session_state)

    completed_jobs = _STORAGE.list_jobs(status="completed")
    jobs_by_id = {job.job_id: job for job in completed_jobs}
    indexed_targets = st.session_state.get("indexed_targets", [])

    if indexed_targets:
        with st.expander("Existing Indexes", expanded=False):
            preview = []
            for item in indexed_targets[:10]:
                preview.append({
                    "Label": item.get("label", ""),
                    "Collection": item.get("collection_name", ""),
                    "Kind": item.get("source_kind", ""),
                    "Indexed at": item.get("indexed_at", "")[:19].replace("T", " "),
                })
            st.dataframe(preview, use_container_width=True, hide_index=True)

    if not completed_jobs:
        st.warning("No completed company-intel jobs are available yet.")
        return

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
        "Include external collected pages",
        value=selected_job.settings.follow_external_sources,
    )
    collection_name = collection_name_for_job(
        selected_job.job_id,
        selected_job.domain,
        include_external=include_external,
    )
    source_type = None if include_external else "internal"
    records = _STORAGE.load_page_records(selected_job_id, source_type=source_type)
    chunk_records = [
        record for record in records
        if _is_indexable_record(record, include_external=include_external)
    ]

    st.info(
        f"Completed jobs: **{len(completed_jobs)}**. "
        f"Indexable pages for this job: **{len(chunk_records)}**."
    )
    if chunk_records:
        counts = Counter(record.page_category for record in chunk_records)
        st.write(dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))))
    target = {
        "target_id": f"job:{selected_job.job_id}:{'full' if include_external else 'internal'}",
        "label": f"{selected_job.domain} ({'internal + external' if include_external else 'internal only'})",
        "collection_name": collection_name,
        "source_kind": "company_job",
        "job_id": selected_job.job_id,
        "domain": selected_job.domain,
        "include_external": include_external,
    }

    if not chunk_records:
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
            pct = progress.chunks_done / progress.chunks_total if progress.chunks_total else 0
            progress_bar.progress(pct)
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
        status_text.text("Indexing complete!")

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
