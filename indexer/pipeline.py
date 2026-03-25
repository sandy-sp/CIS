"""Embed cleaned company-intel page records into Qdrant."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator, Optional

from company_intel.models import PageRecord
from company_intel.review import is_record_approved_for_outputs
from company_intel.storage import JobStorage
from indexer.embedder import Embedder
from indexer.vector_store import VectorStore
from processor.chunker import Chunker
from scraper.pipeline_db import PipelineDB


_BATCH_SIZE = 32  # embed N chunks at a time


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

def _is_indexable_record(record: PageRecord, include_external: bool = True) -> bool:
    if record.status != "success" or record.is_noise or record.is_duplicate:
        return False
    if not include_external and record.source_type != "internal":
        return False
    if record.source_type == "external" and not is_record_approved_for_outputs(record):
        return False
    source_text = _record_source_text(record)
    return bool(source_text)


def _record_source_text(record: PageRecord) -> str:
    return (record.clean_text or record.raw_text or record.markdown or "").strip()


def _page_record_to_chunks(record: PageRecord, job_id: str = "") -> list[dict]:
    if not _is_indexable_record(record):
        return []

    chunker = Chunker()
    chunks = chunker.chunk(
        _record_source_text(record),
        url=record.url,
        title=record.title,
        page_type=record.page_category or "other",
    )
    payloads = []
    for chunk in chunks:
        payloads.append({
            "text": chunk.text,
            "url": record.url,
            "title": record.title,
            "page_type": record.page_category or "other",
            "page_category": record.page_category or "other",
            "page_subtype": record.page_subtype,
            "source_type": record.source_type,
            "domain": record.domain,
            "job_id": job_id,
            "chunk_index": chunk.chunk_index,
            "chunk_total": chunk.chunk_total,
            "section_heading": chunk.section_heading,
        })
    return payloads


@dataclass
class IndexProgress:
    """Progress event yielded during indexing."""
    chunks_done: int
    chunks_total: int
    current_url: str = ""
    error: str = ""


class IndexerPipeline:
    """Embeds and indexes cleaned company-intel page records into Qdrant."""

    def __init__(self, collection_name: str, embedder: Embedder,
                 qdrant_url: Optional[str] = None,
                 in_memory: bool = False,
                 db: Optional[PipelineDB] = None,
                 storage: Optional[JobStorage] = None):
        self.collection_name = collection_name
        self.embedder = embedder
        self._store = VectorStore(
            collection_name=collection_name,
            dimensions=embedder.dimensions,
            url=qdrant_url,
            in_memory=in_memory,
        )
        self._db = db or PipelineDB()
        self._storage = storage or JobStorage()

    def load_job_records(self, job_id: str, include_external: bool = True) -> list[PageRecord]:
        source_type = None if include_external else "internal"
        records = self._storage.load_page_records(job_id, source_type=source_type)
        return [record for record in records if _is_indexable_record(record, include_external=include_external)]

    def load_job_source_records(self, job_id: str, include_external: bool = True) -> list[PageRecord]:
        source_type = None if include_external else "internal"
        return self._storage.load_page_records(job_id, source_type=source_type)

    def run_job(self, job_id: str, include_external: bool = True) -> Generator[IndexProgress, None, None]:
        records = self.load_job_records(job_id, include_external=include_external)
        yield from self.run(page_records=records, job_id=job_id)

    def replace_job_collection(self, job_id: str, include_external: bool = True) -> Generator[IndexProgress, None, None]:
        all_source_records = self.load_job_source_records(job_id, include_external=include_external)
        for record in all_source_records:
            if record.url:
                self._store.delete_by_url(record.url)
        yield from self.run_job(job_id, include_external=include_external)

    def run(self, page_records: Optional[list[PageRecord]] = None,
            job_id: str = "") -> Generator[IndexProgress, None, None]:
        """Embed and index company-intel page records."""
        parsed = []
        for record in page_records or []:
            parsed.extend(_page_record_to_chunks(record, job_id=job_id))

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
