"""
Orchestrates the embedding and indexing pipeline:
  1. Load clean Markdown chunk files from data/clean/
  2. Parse YAML frontmatter to extract chunk metadata
  3. Embed chunk text using Embedder
  4. Upsert into Qdrant via VectorStore
  5. Update SQLite pipeline.db with indexed_at

Yields progress events for Streamlit UI to display.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional
import yaml

from indexer.embedder import Embedder
from indexer.vector_store import VectorStore
from scraper.pipeline_db import PipelineDB


_CLEAN_DIR = Path("data/clean")
_BATCH_SIZE = 32  # embed N chunks at a time


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_chunk_file(path: Path) -> Optional[dict]:
    """Parse a chunk Markdown file. Returns dict with text + metadata or None on error."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None

    if not content.startswith("---"):
        return {"text": content.strip(), "url": "", "title": "", "page_type": "other",
                "chunk_index": 0, "chunk_total": 1, "section_heading": ""}

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None

    return {
        "text": parts[2].strip(),
        "url": meta.get("url", ""),
        "title": meta.get("title", ""),
        "page_type": meta.get("page_type", "other"),
        "chunk_index": meta.get("chunk_index", 0),
        "chunk_total": meta.get("chunk_total", 1),
        "section_heading": meta.get("section_heading", ""),
    }


@dataclass
class IndexProgress:
    """Progress event yielded during indexing."""
    chunks_done: int
    chunks_total: int
    current_url: str = ""
    error: str = ""


class IndexerPipeline:
    """Embeds and indexes clean chunks into Qdrant."""

    def __init__(self, collection_name: str, embedder: Embedder,
                 clean_dir: Path = _CLEAN_DIR,
                 qdrant_url: Optional[str] = None,
                 in_memory: bool = False,
                 db: Optional[PipelineDB] = None):
        self.collection_name = collection_name
        self.embedder = embedder
        self.clean_dir = clean_dir
        self._store = VectorStore(
            collection_name=collection_name,
            dimensions=embedder.dimensions,
            url=qdrant_url,
            in_memory=in_memory,
        )
        self._db = db or PipelineDB()

    def run(self, chunk_files: Optional[list[Path]] = None) -> Generator[IndexProgress, None, None]:
        """
        Embed and index chunk files. If chunk_files is None, uses data/clean/*.md.
        Yields IndexProgress events for progress tracking.
        """
        if chunk_files is None:
            chunk_files = sorted(self.clean_dir.glob("*.md"))

        # Parse all chunk files
        parsed = []
        for f in chunk_files:
            chunk_data = _parse_chunk_file(f)
            if chunk_data and chunk_data["text"]:
                parsed.append(chunk_data)

        total = len(parsed)

        # Embed + upsert in batches
        done = 0
        for batch_start in range(0, total, _BATCH_SIZE):
            batch = parsed[batch_start:batch_start + _BATCH_SIZE]
            texts = [c["text"] for c in batch]

            try:
                vectors = self.embedder.embed(texts)
            except Exception as exc:
                yield IndexProgress(chunks_done=done, chunks_total=total, error=str(exc))
                return

            chunks_for_upsert = []
            for chunk_data, vector in zip(batch, vectors):
                chunk_id = f"{chunk_data['url']}#{chunk_data['chunk_index']}"
                chunks_for_upsert.append({
                    "id": chunk_id,
                    "vector": vector,
                    "payload": chunk_data,
                })

            self._store.upsert(chunks_for_upsert)

            # Track URLs indexed for SQLite update
            urls_in_batch = {c["url"] for c in batch if c["url"]}
            for url in urls_in_batch:
                self._db.mark_indexed(url, _utcnow_iso())

            done += len(batch)
            current_url = batch[-1]["url"] if batch else ""
            yield IndexProgress(chunks_done=done, chunks_total=total, current_url=current_url)

    def get_stats(self) -> dict:
        """Return collection stats from Qdrant."""
        return self._store.get_collection_stats()
