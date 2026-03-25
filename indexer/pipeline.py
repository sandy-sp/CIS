"""Embed cleaned company-intel page records into Qdrant."""
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import Counter
from typing import Generator, Iterable, Optional

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
    pages_done: int = 0


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
        return list(self.iter_job_records(job_id, include_external=include_external))

    def iter_job_records(self, job_id: str, include_external: bool = True):
        source_type = None if include_external else "internal"
        for record in self._storage.iter_page_records(job_id, source_type=source_type):
            if _is_indexable_record(record, include_external=include_external):
                yield record

    def load_job_source_records(self, job_id: str, include_external: bool = True) -> list[PageRecord]:
        source_type = None if include_external else "internal"
        return list(self._storage.iter_page_records(job_id, source_type=source_type))

    def summarize_job(self, job_id: str, include_external: bool = True) -> dict:
        source_type = None if include_external else "internal"
        counts = Counter()
        indexable_pages = 0
        for record in self._storage.iter_page_records(job_id, source_type=source_type):
            if not _is_indexable_record(record, include_external=include_external):
                continue
            indexable_pages += 1
            counts[record.page_category or "other"] += 1
        return {
            "indexable_pages": indexable_pages,
            "category_counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
        }

    def count_job_chunks(self, job_id: str, include_external: bool = True) -> int:
        total = 0
        for record in self.iter_job_records(job_id, include_external=include_external):
            total += len(_page_record_to_chunks(record, job_id=job_id))
        return total

    def run_job(self, job_id: str, include_external: bool = True) -> Generator[IndexProgress, None, None]:
        yield from self._run_iterable(
            page_records=self.iter_job_records(job_id, include_external=include_external),
            job_id=job_id,
            total_chunks=0,
        )

    def replace_job_collection(self, job_id: str, include_external: bool = True) -> Generator[IndexProgress, None, None]:
        for record in self.load_job_source_records(job_id, include_external=include_external):
            if record.url:
                self._store.delete_by_url(record.url)
        yield from self.run_job(job_id, include_external=include_external)

    def run(self, page_records: Optional[list[PageRecord]] = None,
            job_id: str = "") -> Generator[IndexProgress, None, None]:
        """Embed and index company-intel page records."""
        records = list(page_records or [])
        total_chunks = sum(len(_page_record_to_chunks(record, job_id=job_id)) for record in records)
        yield from self._run_iterable(
            page_records=records,
            job_id=job_id,
            total_chunks=total_chunks,
        )

    def _run_iterable(
        self,
        page_records: Iterable[PageRecord],
        *,
        job_id: str,
        total_chunks: int,
    ) -> Generator[IndexProgress, None, None]:
        done = 0
        pages_done = 0
        batch: list[dict] = []
        current_url = ""

        for record in page_records:
            record_chunks = _page_record_to_chunks(record, job_id=job_id)
            if not record_chunks:
                continue
            current_url = record.url
            for chunk in record_chunks:
                batch.append(chunk)
                if len(batch) >= _BATCH_SIZE:
                    error = self._embed_and_upsert_batch(batch)
                    if error:
                        yield IndexProgress(
                            chunks_done=done,
                            chunks_total=total_chunks,
                            current_url=current_url,
                            error=error,
                            pages_done=pages_done,
                        )
                        return
                    done += len(batch)
                    for url in {item["url"] for item in batch if item.get("url")}:
                        self._db.mark_indexed(url, _utcnow_iso())
                    yield IndexProgress(
                        chunks_done=done,
                        chunks_total=total_chunks,
                        current_url=current_url,
                        pages_done=pages_done,
                    )
                    batch = []
            pages_done += 1

        if batch:
            error = self._embed_and_upsert_batch(batch)
            if error:
                yield IndexProgress(
                    chunks_done=done,
                    chunks_total=total_chunks,
                    current_url=current_url,
                    error=error,
                    pages_done=pages_done,
                )
                return
            done += len(batch)
            for url in {item["url"] for item in batch if item.get("url")}:
                self._db.mark_indexed(url, _utcnow_iso())
            yield IndexProgress(
                chunks_done=done,
                chunks_total=total_chunks,
                current_url=current_url,
                pages_done=pages_done,
            )

    def _embed_and_upsert_batch(self, batch: list[dict]) -> str:
        texts = [chunk["text"] for chunk in batch]
        try:
            vectors = self.embedder.embed(texts)
        except Exception as exc:
            return str(exc)

        chunks_for_upsert = []
        for chunk_data, vector in zip(batch, vectors):
            chunk_id = f"{chunk_data['url']}#{chunk_data['chunk_index']}"
            chunks_for_upsert.append({
                "id": chunk_id,
                "vector": vector,
                "payload": chunk_data,
            })
        self._store.upsert(chunks_for_upsert)
        return ""

    def get_stats(self) -> dict:
        """Return collection stats from Qdrant."""
        return self._store.get_collection_stats()
