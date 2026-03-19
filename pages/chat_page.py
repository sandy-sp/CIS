# pages/chat_page.py
"""Ask questions against indexed company-intel collections."""
import os

import streamlit as st

from activity_log import log_activity
from app_settings import default_ollama_url, ensure_session_settings
from chat.generator import Generator
from chat.retriever import Retriever
from company_intel.storage import JobStorage
from indexer.embedder import Embedder
from indexer.registry import IndexRegistry


QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_STORAGE = JobStorage()
_REGISTRY = IndexRegistry()


def _truncate_for_log(text: str, limit: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _chunk_log_summary(chunks: list) -> str:
    labels = []
    for chunk in chunks[:3]:
        if isinstance(chunk, dict):
            title = chunk.get("title", "")
            url = chunk.get("url", "")
        else:
            title = getattr(chunk, "title", "")
            url = getattr(chunk, "url", "")
        labels.append(_truncate_for_log(title or url, limit=60))
    return ", ".join(filter(None, labels))


def _is_generation_error(answer: str) -> bool:
    return answer.startswith("[Ollama error:") or answer.startswith("[OpenAI error:") or answer.startswith("[Anthropic error:")


def _ensure_chat_state() -> None:
    defaults = {
        "chat_history": [],
        "last_sources": [],
        "indexed_targets": [],
        "active_rag_target_id": "",
        "chat_target_id": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    _sync_registry_targets()


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


def chat_page() -> None:
    _ensure_chat_state()

    st.title("Chat")
    st.caption("Ask questions against an indexed company-intel corpus.")

    # --- Settings from session (set by settings page) ---
    settings = ensure_session_settings(st.session_state)
    backend = settings.get("llm_backend", "ollama")
    api_key = settings.get("api_key", "")
    llm_model = settings.get("llm_model", "")
    embedding_backend = settings.get("embedding_backend", "local")
    embedding_api_key = settings.get("embedding_api_key", "")
    embedding_model = settings.get("embedding_model", "")
    ollama_url = settings.get("ollama_url", default_ollama_url())
    indexed_targets = st.session_state.get("indexed_targets", [])

    if not indexed_targets:
        completed_jobs = _STORAGE.list_jobs(status="completed")
        if completed_jobs:
            st.warning("No indexed corpora are tracked in this session. Run the Index step on a completed crawl job first.")
            st.write([f"{job.domain} | {job.job_id}" for job in completed_jobs[:10]])
        else:
            st.warning("No completed crawl jobs are available yet.")
        return

    targets_by_id = {target["target_id"]: target for target in indexed_targets}
    target_ids = list(targets_by_id)
    default_target = st.session_state.get("active_rag_target_id", "")
    selected_index = target_ids.index(default_target) if default_target in target_ids else 0
    active_target_id = st.selectbox(
        "Indexed corpus",
        options=target_ids,
        index=selected_index,
        format_func=lambda target_id: targets_by_id[target_id]["label"],
    )
    st.session_state.active_rag_target_id = active_target_id
    if st.session_state.chat_target_id and st.session_state.chat_target_id != active_target_id:
        st.session_state.chat_history = []
        st.session_state.last_sources = []
    st.session_state.chat_target_id = active_target_id
    active_target = targets_by_id[active_target_id]
    collection_name = active_target["collection_name"]
    st.caption(f"Collection: `{collection_name}`")
    indexed_at = active_target.get("indexed_at", "")
    if indexed_at:
        st.caption(f"Indexed: `{indexed_at[:19].replace('T', ' ')}`")

    # Validate settings
    if backend in ("openai", "anthropic") and not api_key:
        st.warning(f"Configure your {backend.capitalize()} API key in the Settings page.")
        return
    if embedding_backend == "openai" and not embedding_api_key:
        st.warning("Configure your OpenAI embedding API key in the Settings page.")
        return

    # --- Display chat history ---
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # --- Sources from last answer ---
    if st.session_state.last_sources:
        with st.expander("Sources from last answer"):
            for src in st.session_state.last_sources:
                st.markdown(f"**[{src['title']}]({src['url']})**")
                meta = " / ".join(filter(None, [src.get("page_type", ""), src.get("source_type", "")]))
                if meta:
                    st.caption(meta)
                st.caption(src["text"][:200] + "..." if len(src["text"]) > 200 else src["text"])

    # --- Chat input ---
    if question := st.chat_input("Ask a question about the scraped content..."):
        log_activity(
            st.session_state,
            "chat",
            f"Submitted question to `{collection_name}`",
            details=_truncate_for_log(question),
        )
        # Show user message immediately
        st.session_state.chat_history.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # Build embedder
                    emb_kwargs = {"backend": embedding_backend}
                    if embedding_backend == "openai":
                        emb_kwargs["api_key"] = embedding_api_key
                    if embedding_backend == "ollama":
                        emb_kwargs["ollama_url"] = ollama_url
                    if embedding_model:
                        emb_kwargs["model"] = embedding_model
                    embedder = Embedder(**emb_kwargs)

                    # Retrieve relevant chunks
                    retriever = Retriever(
                        collection_name=collection_name,
                        embedder=embedder,
                        qdrant_url=QDRANT_URL,
                        top_k_final=5,
                        use_reranker=False,  # skip reranker for speed; reranker model may not be downloaded
                    )
                    chunks = retriever.retrieve(question)
                    if chunks:
                        log_activity(
                            st.session_state,
                            "chat",
                            f"Retrieved {len(chunks)} chunks for `{collection_name}`",
                            details=_chunk_log_summary(chunks),
                        )
                    else:
                        log_activity(
                            st.session_state,
                            "chat",
                            f"No retrieval hits for `{collection_name}`",
                            level="warning",
                            details=_truncate_for_log(question),
                        )

                    # Generate answer
                    gen_kwargs = {"backend": backend, "ollama_url": ollama_url}
                    if api_key:
                        gen_kwargs["api_key"] = api_key
                    if llm_model:
                        gen_kwargs["model"] = llm_model
                    generator = Generator(**gen_kwargs)
                    answer = generator.generate(
                        question=question,
                        context_chunks=chunks,
                        history=st.session_state.chat_history[-10:],
                    )

                    st.markdown(answer)
                    st.session_state.chat_history.append({"role": "assistant", "content": answer})
                    if _is_generation_error(answer):
                        log_activity(
                            st.session_state,
                            "chat",
                            f"Generation error for `{collection_name}`",
                            level="error",
                            details=answer,
                        )
                    else:
                        log_activity(
                            st.session_state,
                            "chat",
                            f"Generated answer for `{collection_name}`",
                            level="success",
                            details=f"Chunks used: {len(chunks)} | Question: {_truncate_for_log(question)}",
                        )

                    # Save sources for display
                    st.session_state.last_sources = [
                        {
                            "url": c.url,
                            "title": c.title,
                            "text": c.text,
                            "page_type": c.page_type,
                            "source_type": c.source_type,
                        }
                        for c in chunks
                    ]

                except Exception as exc:
                    error_msg = f"Error: {exc}"
                    st.error(error_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
                    log_activity(
                        st.session_state,
                        "chat",
                        f"Chat request failed for `{collection_name}`",
                        level="error",
                        details=str(exc),
                    )

    # --- Clear chat button ---
    if st.session_state.chat_history:
        if st.button("Clear chat"):
            log_activity(
                st.session_state,
                "chat",
                f"Cleared chat history for `{collection_name}`",
            )
            st.session_state.chat_history = []
            st.session_state.last_sources = []
            st.rerun()
