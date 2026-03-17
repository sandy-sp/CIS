# pages/clean_page.py
"""Step 2 — Data Cleaning: clean, dedup, and chunk raw Markdown files."""
import streamlit as st
from pathlib import Path

from processor.pipeline import Pipeline


def clean_page() -> None:
    st.title("Clean")
    st.caption("Clean and chunk scraped Markdown files for RAG processing.")

    # --- Session state ---
    if "clean_results" not in st.session_state:
        st.session_state.clean_results = []

    raw_dir = Path("data/raw")
    raw_files = sorted(raw_dir.glob("*.md")) if raw_dir.exists() else []

    st.info(f"Found **{len(raw_files)}** raw Markdown files in `data/raw/`.")

    if not raw_files:
        st.warning("No raw files found. Run the Scrape step first and download/extract the ZIP to `data/raw/`.")
        return

    if st.button("Run Cleaning Pipeline", type="primary"):
        with st.spinner("Cleaning and chunking pages..."):
            pipeline = Pipeline()
            results = pipeline.run(raw_files)
            st.session_state.clean_results = results

    if st.session_state.clean_results:
        results = st.session_state.clean_results
        total = len(results)
        skipped = sum(1 for r in results if r.skipped)
        processed = total - skipped
        total_chunks = sum(r.chunk_count for r in results)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total files", total)
        col2.metric("Processed", processed)
        col3.metric("Skipped", skipped)
        col4.metric("Total chunks", total_chunks)

        # Table of results
        st.subheader("Results")
        table_data = []
        for r in results:
            table_data.append({
                "URL": r.url[:60] + "..." if len(r.url) > 60 else r.url,
                "Original words": r.original_word_count,
                "Clean words": r.clean_word_count,
                "Chunks": r.chunk_count,
                "Status": "skipped" if r.skipped else "ok",
                "Skip reason": r.skip_reason,
            })
        st.dataframe(table_data, use_container_width=True)

        # High-noise flagged
        high_noise = [r for r in results if r.skipped and r.skip_reason in ("too-short", "noise-url")]
        if high_noise:
            with st.expander(f"High-noise pages ({len(high_noise)}) — flagged for review"):
                for r in high_noise:
                    st.write(f"- `{r.url}` — {r.skip_reason}")
