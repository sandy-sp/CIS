# pages/index_page.py
"""Step 3 — Vector Indexing: embed clean chunks and store in Qdrant."""
import os
import streamlit as st
from pathlib import Path

from indexer.embedder import Embedder
from indexer.pipeline import IndexerPipeline


QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")


def index_page() -> None:
    st.title("Index")
    st.caption("Embed cleaned chunks into a Qdrant vector database.")

    clean_dir = Path("data/clean")
    chunk_files = sorted(clean_dir.glob("*.md")) if clean_dir.exists() else []

    st.info(f"Found **{len(chunk_files)}** chunk files in `data/clean/`.")

    if not chunk_files:
        st.warning("No chunk files found. Run the Clean step first.")
        return

    # --- Settings ---
    st.subheader("Embedding Settings")
    backend = st.radio("Backend", ["Local (BGE-M3)", "OpenAI API"], horizontal=True)

    api_key = None
    if backend == "OpenAI API":
        api_key = st.text_input("OpenAI API Key", type="password",
                                placeholder="sk-...")
        if not api_key:
            st.warning("Enter your OpenAI API key to proceed.")
            return

    collection_name = st.session_state.get("domain", "rag-collection")

    if st.button("Run Indexing Pipeline", type="primary"):
        embedder_backend = "local" if backend == "Local (BGE-M3)" else "openai"
        embedder = Embedder(backend=embedder_backend, api_key=api_key)
        pipeline = IndexerPipeline(
            collection_name=collection_name,
            embedder=embedder,
            clean_dir=clean_dir,
            qdrant_url=QDRANT_URL,
        )

        progress_bar = st.progress(0)
        status_text = st.empty()

        for progress in pipeline.run(chunk_files):
            if progress.error:
                st.error(f"Indexing error: {progress.error}")
                break
            pct = progress.chunks_done / progress.chunks_total if progress.chunks_total else 0
            progress_bar.progress(pct)
            status_text.text(f"Indexed {progress.chunks_done}/{progress.chunks_total} chunks")

        progress_bar.progress(1.0)
        status_text.text("Indexing complete!")

        # Show collection stats
        try:
            stats = pipeline.get_stats()
            col1, col2, col3 = st.columns(3)
            col1.metric("Total vectors", stats["total_vectors"])
            col2.metric("Dimensions", stats["dimensions"])
            col3.metric("Collection", stats["collection_name"])
        except Exception as exc:
            st.warning(f"Could not fetch collection stats: {exc}")
