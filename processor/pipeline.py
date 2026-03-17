# processor/pipeline.py
"""
Orchestrates the full data cleaning pipeline:
  1. Load raw Markdown files from data/raw/ (or a provided list)
  2. Clean each file using Trafilatura (Cleaner)
  3. Remove near-duplicates using MinHash (Deduplicator)
  4. Chunk clean text (Chunker)
  5. Save chunks as Markdown files to data/clean/
  6. Update SQLite pipeline.db with cleaned_at + chunk_count
"""
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from processor.cleaner import Cleaner, CleanResult
from processor.chunker import Chunker, Chunk
from processor.deduplicator import Deduplicator
from scraper.pipeline_db import PipelineDB


_RAW_DIR = Path("data/raw")
_CLEAN_DIR = Path("data/clean")


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ProcessingResult:
    """Result of processing a single file."""
    def __init__(self, url: str, original_word_count: int, clean_word_count: int,
                 chunk_count: int, skipped: bool = False, skip_reason: str = ""):
        self.url = url
        self.original_word_count = original_word_count
        self.clean_word_count = clean_word_count
        self.chunk_count = chunk_count
        self.skipped = skipped
        self.skip_reason = skip_reason


class Pipeline:
    """Runs the full clean → dedup → chunk → save pipeline."""

    def __init__(self, raw_dir: Path = _RAW_DIR, clean_dir: Path = _CLEAN_DIR,
                 db: PipelineDB | None = None):
        self.raw_dir = raw_dir
        self.clean_dir = clean_dir
        self.clean_dir.mkdir(parents=True, exist_ok=True)
        self._cleaner = Cleaner()
        self._chunker = Chunker()
        self._deduplicator = Deduplicator()
        self._db = db or PipelineDB()

    def run(self, markdown_files: list[Path] | None = None) -> list[ProcessingResult]:
        """
        Process all markdown files. If markdown_files is None, processes data/raw/*.md.
        Returns list of ProcessingResult (one per input file).
        """
        if markdown_files is None:
            markdown_files = sorted(self.raw_dir.glob("*.md"))

        results = []
        for md_file in markdown_files:
            result = self._process_file(md_file)
            results.append(result)

        return results

    def _process_file(self, md_file: Path) -> ProcessingResult:
        """Process a single markdown file."""
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as exc:
            return ProcessingResult(
                url=str(md_file), original_word_count=0, clean_word_count=0,
                chunk_count=0, skipped=True, skip_reason=f"read-error: {exc}"
            )

        # Clean
        clean_result = self._cleaner.clean_markdown_file(content)
        if clean_result.skip_reason:
            return ProcessingResult(
                url=clean_result.url, original_word_count=clean_result.original_word_count,
                clean_word_count=0, chunk_count=0,
                skipped=True, skip_reason=clean_result.skip_reason,
            )

        # Chunk
        chunks = self._chunker.chunk(
            clean_result.clean_text,
            url=clean_result.url,
            title=clean_result.title,
            page_type=clean_result.page_type,
        )

        # Dedup (filter near-duplicate chunks within this page's chunks)
        chunks = self._deduplicator.deduplicate(chunks)

        # Save chunks to data/clean/
        self._save_chunks(chunks, md_file.stem)

        # Update SQLite
        if clean_result.url:
            self._db.mark_cleaned(
                url=clean_result.url,
                cleaned_at=_utcnow_iso(),
                chunk_count=len(chunks),
            )

        return ProcessingResult(
            url=clean_result.url or str(md_file),
            original_word_count=clean_result.original_word_count,
            clean_word_count=clean_result.word_count,
            chunk_count=len(chunks),
        )

    def _save_chunks(self, chunks: list[Chunk], file_stem: str) -> None:
        """Save chunks as individual Markdown files with YAML frontmatter."""
        for chunk in chunks:
            frontmatter = (
                f"---\n"
                f"url: {chunk.url}\n"
                f"title: {chunk.title}\n"
                f"page_type: {chunk.page_type}\n"
                f"chunk_index: {chunk.chunk_index}\n"
                f"chunk_total: {chunk.chunk_total}\n"
                f"section_heading: {chunk.section_heading!r}\n"
                f"word_count: {chunk.word_count}\n"
                f"---\n\n"
            )
            filename = f"{file_stem}_chunk_{chunk.chunk_index:03d}.md"
            (self.clean_dir / filename).write_text(
                frontmatter + chunk.text, encoding="utf-8"
            )
