# pages/chat_page.py
"""Ask questions against indexed company-intel collections."""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from activity_log import log_activity
from app_settings import default_ollama_url, ensure_session_settings
from chat.generator import Generator
from chat.retriever import Retriever
from company_intel.storage import JobStorage
from indexer.embedder import Embedder
from indexer.qdrant_status import (
    STATE_MISSING,
    STATE_UNAVAILABLE,
    fetch_qdrant_collections_status,
    tracked_target_state,
)
from indexer.registry import IndexRegistry


QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_STORAGE = JobStorage()
_REGISTRY = IndexRegistry()
_DISPLAY_TIMEZONE = os.environ.get("APP_TIMEZONE") or os.environ.get("TZ") or "America/New_York"
_ENTITY_QUERY_MAP = [
    (("employee", "employees", "people", "team", "staff", "linkedin", "leadership"), ("people",)),
    (("service", "services", "solution", "solutions", "offering", "offerings", "capability", "capabilities"), ("services",)),
    (("partner", "partners", "partnership", "alliances"), ("partners",)),
    (("customer", "customers", "client", "clients"), ("customers",)),
    (("event", "events", "conference", "conferences", "webinar", "summit", "symposium", "attended", "hosted"), ("events",)),
    (("case study", "case studies", "success story", "success stories", "project example"), ("case_studies",)),
]
_ENTITY_LIMITS = {
    "company_profile": 1,
    "people": 20,
    "services": 10,
    "partners": 10,
    "customers": 10,
    "events": 10,
    "case_studies": 10,
}

_UNKNOWN_PATTERNS = (
    "i don't know",
    "i do not know",
    "no scraped content",
    "no information to extract",
    "no information available",
    "not enough information",
    "cannot answer based on the scraped content",
)


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
    local_dt = dt.astimezone(_display_tz())
    return local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")


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


def _normalize_entity_value(value) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _entity_bucket_order(question: str) -> list[str]:
    lowered = question.lower()
    buckets = ["company_profile"]
    for keywords, mapped_buckets in _ENTITY_QUERY_MAP:
        if any(keyword in lowered for keyword in keywords):
            buckets.extend(mapped_buckets)
    if buckets == ["company_profile"]:
        buckets.extend(["services", "people", "partners", "events"])
    ordered: list[str] = []
    for bucket in buckets:
        if bucket not in ordered:
            ordered.append(bucket)
    return ordered


def _is_entity_focused_question(question: str) -> bool:
    lowered = question.lower()
    if "list" in lowered:
        return True
    return any(keyword in lowered for keywords, _ in _ENTITY_QUERY_MAP for keyword in keywords)


def _looks_like_unknown_answer(answer: str) -> bool:
    lowered = (answer or "").strip().lower()
    if not lowered:
        return True
    return any(pattern in lowered for pattern in _UNKNOWN_PATTERNS)


def _entity_to_source(bucket: str, entity) -> dict:
    lines = [f"{bucket.replace('_', ' ').title()}: {entity.display_name}"]
    for key, value in sorted(entity.attributes.items()):
        normalized = _normalize_entity_value(value)
        if not normalized:
            continue
        lines.append(f"{key.replace('_', ' ').title()}: {normalized}")
    if entity.evidence_snippets:
        snippet = _normalize_entity_value(entity.evidence_snippets[0])
        if snippet:
            lines.append(f"Evidence: {snippet}")
    return {
        "url": entity.source_urls[0] if entity.source_urls else "",
        "title": f"{bucket.replace('_', ' ').title()} | {entity.display_name}",
        "text": "\n".join(lines),
        "page_type": bucket,
        "source_type": "structured-entity",
    }


def _entity_sources_for_question(job_id: str, question: str) -> list[dict]:
    if not job_id:
        return []
    entities = _STORAGE.load_entities(job_id)
    if not entities:
        return []

    sources: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for bucket in _entity_bucket_order(question):
        for entity in entities.get(bucket, [])[:_ENTITY_LIMITS.get(bucket, 5)]:
            key = (bucket, entity.normalized_key)
            if key in seen:
                continue
            seen.add(key)
            sources.append(_entity_to_source(bucket, entity))
    return sources


def _entity_bucket_alias(entity_type: str) -> str:
    normalized = (entity_type or "").strip().lower().replace(" ", "_")
    aliases = {
        "company": "company_profile",
        "company_profile": "company_profile",
        "services": "services",
        "service": "services",
        "people": "people",
        "person": "people",
        "employees": "people",
        "employee": "people",
        "partners": "partners",
        "partner": "partners",
        "customers": "customers",
        "customer": "customers",
        "events": "events",
        "event": "events",
        "case_studies": "case_studies",
        "case_study": "case_studies",
    }
    return aliases.get(normalized, normalized)


def _structured_answer_from_entities(job_id: str, question: str) -> str:
    entities = _STORAGE.load_entities(job_id)
    if not entities:
        return ""

    buckets = _entity_bucket_order(question)
    lines: list[str] = []

    company = entities.get("company_profile", [])
    if company:
        profile = company[0]
        summary = _normalize_entity_value(profile.attributes.get("summary"))
        if summary:
            source = profile.source_urls[0] if profile.source_urls else ""
            lines.append(f"**{profile.display_name}**: {summary}" + (f" [Source]({source})" if source else ""))

    if "people" in buckets and entities.get("people"):
        lines.append("People found:")
        for person in entities["people"][: _ENTITY_LIMITS["people"]]:
            title = _normalize_entity_value(person.attributes.get("title")) or "Title not found"
            linkedin = _normalize_entity_value(person.attributes.get("linkedin_url")) or "LinkedIn URL not found in extracted content"
            source = person.source_urls[0] if person.source_urls else ""
            lines.append(
                f"- {person.display_name} — {title}. LinkedIn: {linkedin}"
                + (f" [Source]({source})" if source else "")
            )

    if "services" in buckets and entities.get("services"):
        lines.append("Services found:")
        for service in entities["services"][: _ENTITY_LIMITS["services"]]:
            source = service.source_urls[0] if service.source_urls else ""
            lines.append(f"- {service.display_name}" + (f" [Source]({source})" if source else ""))

    if "partners" in buckets and entities.get("partners"):
        lines.append("Partners found:")
        for partner in entities["partners"][: _ENTITY_LIMITS["partners"]]:
            source = partner.source_urls[0] if partner.source_urls else ""
            lines.append(f"- {partner.display_name}" + (f" [Source]({source})" if source else ""))

    if "events" in buckets and entities.get("events"):
        lines.append("Events found:")
        for event in entities["events"][: _ENTITY_LIMITS["events"]]:
            date = _normalize_entity_value(event.attributes.get("date"))
            location = _normalize_entity_value(event.attributes.get("location"))
            source = event.source_urls[0] if event.source_urls else ""
            details = " | ".join(filter(None, [date, location]))
            lines.append(
                f"- {event.display_name}" + (f" ({details})" if details else "") + (f" [Source]({source})" if source else "")
            )

    if "customers" in buckets and entities.get("customers"):
        lines.append("Customers found:")
        for customer in entities["customers"][: _ENTITY_LIMITS["customers"]]:
            source = customer.source_urls[0] if customer.source_urls else ""
            lines.append(f"- {customer.display_name}" + (f" [Source]({source})" if source else ""))

    if "case_studies" in buckets and entities.get("case_studies"):
        lines.append("Case studies found:")
        for case_study in entities["case_studies"][: _ENTITY_LIMITS["case_studies"]]:
            source = case_study.source_urls[0] if case_study.source_urls else ""
            lines.append(f"- {case_study.display_name}" + (f" [Source]({source})" if source else ""))

    return "\n".join(lines).strip()


def _is_generation_error(answer: str) -> bool:
    return answer.startswith("[Ollama error:") or answer.startswith("[OpenAI error:") or answer.startswith("[Anthropic error:")


def _retrieval_settings(active_target: dict, settings: dict) -> dict:
    backend = active_target.get("embedding_backend") or settings.get("embedding_backend", "ollama")
    return {
        "backend": backend,
        "api_key": settings.get("embedding_api_key", "") if backend == "openai" else "",
        "model": active_target.get("embedding_model") or settings.get("embedding_model", ""),
        "ollama_url": active_target.get("embedding_ollama_url") or settings.get("ollama_url", default_ollama_url()),
    }


def _backend_display_label(backend: str, model: str, ollama_url: str = "") -> str:
    if backend == "ollama":
        host = "Bundled Ollama" if ollama_url.rstrip("/") in {
            default_ollama_url().rstrip("/"),
            "http://localhost:11434",
            "http://ollama:11434",
        } else "Custom Ollama"
        return f"{host} | {model}"
    if backend == "openai":
        return f"OpenAI API | {model}"
    if backend == "anthropic":
        return f"Anthropic API | {model}"
    return f"Local model | {model}"


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
    st.session_state.indexed_targets = list(registry_targets)
    target_ids = {item.get("target_id", "") for item in registry_targets}
    active_target = st.session_state.get("active_rag_target_id", "")
    chat_target = st.session_state.get("chat_target_id", "")
    if active_target not in target_ids:
        st.session_state.active_rag_target_id = registry_targets[0]["target_id"] if registry_targets else ""
    if chat_target not in target_ids:
        st.session_state.chat_target_id = ""


def chat_page() -> None:
    _ensure_chat_state()

    st.title("Chat")
    st.caption("Ask questions against an indexed company-intel corpus.")

    # --- Settings from session (set by settings page) ---
    settings = ensure_session_settings(st.session_state)
    backend = settings.get("llm_backend", "ollama")
    api_key = settings.get("api_key", "")
    llm_model = settings.get("llm_model", "")
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
    qdrant_status = fetch_qdrant_collections_status(QDRANT_URL)
    collection_state = tracked_target_state(active_target, qdrant_status)
    if collection_state == STATE_UNAVAILABLE:
        st.error(f"Qdrant is unavailable at `{QDRANT_URL}`. Chat requires Qdrant to load indexed corpora.")
        if qdrant_status.error:
            st.caption(f"Qdrant error: {qdrant_status.error}")
        return
    if collection_state == STATE_MISSING:
        st.error(
            "The selected index is tracked in the registry, but the Qdrant collection is missing. "
            "Rebuild the search index from the Index page."
        )
        return
    retrieval = _retrieval_settings(active_target, settings)
    st.caption(f"Collection: `{collection_name}`")
    indexed_at = active_target.get("indexed_at", "")
    if indexed_at:
        st.caption(f"Indexed: `{_format_timestamp_local(indexed_at)}`")
    st.info(
        "Retrieval uses the embedding model that built this index. "
        "Answer generation uses your current chat model from Settings."
    )
    st.caption(
        f"Retrieval: `{_backend_display_label(retrieval['backend'], retrieval['model'], retrieval['ollama_url'])}`"
    )
    st.caption(
        f"Answer model: `{_backend_display_label(backend, llm_model, ollama_url)}`"
    )

    # Validate settings
    if backend in ("openai", "anthropic") and not api_key:
        st.warning(f"Configure your {backend.capitalize()} API key in the Settings page.")
        return
    if retrieval["backend"] == "openai" and not retrieval["api_key"]:
        st.warning("This indexed corpus requires the OpenAI embedding API key used for retrieval. Configure it in Settings.")
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
                    embedder = Embedder(
                        backend=retrieval["backend"],
                        api_key=retrieval["api_key"] or None,
                        model=retrieval["model"] or None,
                        ollama_url=retrieval["ollama_url"],
                    )

                    # Retrieve relevant chunks
                    retriever = Retriever(
                        collection_name=collection_name,
                        embedder=embedder,
                        qdrant_url=QDRANT_URL,
                        top_k_final=5,
                        use_reranker=False,  # skip reranker for speed; reranker model may not be downloaded
                    )
                    chunks = retriever.retrieve(question)
                    if retriever.last_error:
                        error_msg = (
                            f"Retrieval failed during {retriever.last_stage.replace('_', ' ')}: "
                            f"{retriever.last_error}"
                        )
                        st.error(error_msg)
                        st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
                        log_activity(
                            st.session_state,
                            "chat",
                            f"Retrieval failed for `{collection_name}`",
                            level="error",
                            details=error_msg,
                        )
                        return
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

                    entity_sources = _entity_sources_for_question(
                        active_target.get("job_id", ""),
                        question,
                    )
                    vector_sources = [
                        {
                            "url": c.url,
                            "title": c.title,
                            "text": c.text,
                            "page_type": c.page_type,
                            "source_type": c.source_type,
                        }
                        for c in chunks
                    ]
                    if entity_sources:
                        vector_sources = vector_sources[:2]
                    combined_sources = entity_sources + vector_sources
                    if entity_sources:
                        log_activity(
                            st.session_state,
                            "chat",
                            f"Loaded {len(entity_sources)} structured entity sources for `{collection_name}`",
                            details=_chunk_log_summary(entity_sources),
                        )

                    entities = _STORAGE.load_entities(active_target.get("job_id", ""))
                    structured_answer = _structured_answer_from_entities(
                        active_target.get("job_id", ""),
                        question,
                    )
                    if structured_answer and (_is_entity_focused_question(question) or not chunks):
                        st.markdown(structured_answer)
                        st.session_state.chat_history.append({"role": "assistant", "content": structured_answer})
                        st.session_state.last_sources = combined_sources
                        log_activity(
                            st.session_state,
                            "chat",
                            f"Answered from structured entities for `{collection_name}`",
                            level="success",
                            details=(
                                f"Structured sources: {len(entity_sources)} | "
                                f"Vector hits: {len(chunks)} | "
                                f"Question: {_truncate_for_log(question)}"
                            ),
                        )
                        return

                    def search_company_corpus(query: str, limit: int = 5) -> str:
                        """
                        Search the indexed company vector database for relevant scraped content.

                        Args:
                            query: Search query describing the information needed.
                            limit: Maximum number of matching passages to return.
                        """
                        tool_chunks = retriever.retrieve(query)
                        rows = [
                            {
                                "title": chunk.title,
                                "url": chunk.url,
                                "page_type": chunk.page_type,
                                "text": chunk.text,
                            }
                            for chunk in tool_chunks[: max(1, min(limit, 5))]
                        ]
                        return json.dumps(rows, indent=2)

                    def lookup_company_entities(entity_type: str = "company_profile", limit: int = 10) -> str:
                        """
                        Inspect structured entities extracted from the scraped company site.

                        Args:
                            entity_type: One of company_profile, services, case_studies, partners, customers, people, or events.
                            limit: Maximum number of entities to return.
                        """
                        bucket = _entity_bucket_alias(entity_type)
                        values = entities.get(bucket, [])
                        rows = [
                            {
                                "display_name": entity.display_name,
                                "attributes": entity.attributes,
                                "source_urls": entity.source_urls,
                                "evidence_snippets": entity.evidence_snippets[:2],
                            }
                            for entity in values[: max(1, min(limit, 15))]
                        ]
                        return json.dumps(rows, indent=2)

                    # Generate answer
                    gen_kwargs = {"backend": backend, "ollama_url": ollama_url}
                    if api_key:
                        gen_kwargs["api_key"] = api_key
                    if llm_model:
                        gen_kwargs["model"] = llm_model
                    generator = Generator(**gen_kwargs)
                    answer = generator.generate(
                        question=question,
                        context_chunks=combined_sources,
                        history=st.session_state.chat_history[:-1][-10:],
                        tools={
                            "search_company_corpus": search_company_corpus,
                            "lookup_company_entities": lookup_company_entities,
                        } if backend == "ollama" else None,
                    )
                    if _looks_like_unknown_answer(answer) and structured_answer:
                        answer = structured_answer

                    if _is_generation_error(answer):
                        st.error(answer)
                    else:
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
                            details=(
                                f"Structured sources: {len(entity_sources)} | "
                                f"Vector hits: {len(chunks)} | "
                                f"Question: {_truncate_for_log(question)}"
                            ),
                        )

                    # Save sources for display
                    st.session_state.last_sources = combined_sources

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
