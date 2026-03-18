# pages/chat_page.py
"""Step 4 — RAG Chat: ask questions about scraped business content."""
import os
import streamlit as st

from chat.generator import Generator
from chat.retriever import Retriever
from indexer.embedder import Embedder


QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")


def chat_page() -> None:
    st.title("Chat")
    st.caption("Ask questions about your scraped business content.")

    # --- Session state ---
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []  # list of {"role": ..., "content": ...}
    if "last_sources" not in st.session_state:
        st.session_state.last_sources = []

    # --- Settings from session (set by settings page) ---
    settings = st.session_state.get("settings", {})
    backend = settings.get("llm_backend", "ollama")
    api_key = settings.get("api_key", "")
    embedding_backend = settings.get("embedding_backend", "local")
    embedding_api_key = settings.get("embedding_api_key", "")
    ollama_url = settings.get("ollama_url", "http://localhost:11434")
    collection_name = st.session_state.get("domain", "rag-collection")

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
                st.caption(src["text"][:200] + "..." if len(src["text"]) > 200 else src["text"])

    # --- Chat input ---
    if question := st.chat_input("Ask a question about the scraped content..."):
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

                    # Generate answer
                    gen_kwargs = {"backend": backend, "ollama_url": ollama_url}
                    if api_key:
                        gen_kwargs["api_key"] = api_key
                    generator = Generator(**gen_kwargs)
                    answer = generator.generate(
                        question=question,
                        context_chunks=chunks,
                        history=st.session_state.chat_history[-10:],
                    )

                    st.markdown(answer)
                    st.session_state.chat_history.append({"role": "assistant", "content": answer})

                    # Save sources for display
                    st.session_state.last_sources = [
                        {"url": c.url, "title": c.title, "text": c.text}
                        for c in chunks
                    ]

                except Exception as exc:
                    error_msg = f"Error: {exc}"
                    st.error(error_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": error_msg})

    # --- Clear chat button ---
    if st.session_state.chat_history:
        if st.button("Clear chat"):
            st.session_state.chat_history = []
            st.session_state.last_sources = []
            st.rerun()
