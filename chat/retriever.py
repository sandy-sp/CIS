# chat/retriever.py
from dataclasses import dataclass
from typing import Optional
from indexer.embedder import Embedder
from indexer.vector_store import VectorStore


@dataclass
class RetrievedChunk:
    url: str
    title: str
    text: str
    section_heading: str
    score: float
    chunk_index: int = 0
    page_type: str = ""
    source_type: str = ""
    job_id: str = ""


class Retriever:
    def __init__(self, collection_name: str, embedder: Embedder,
                 qdrant_url: Optional[str] = None,
                 in_memory: bool = False,
                 top_k_candidates: int = 50,
                 top_k_final: int = 5,
                 use_reranker: bool = True):
        self.collection_name = collection_name
        self.embedder = embedder
        self.top_k_candidates = top_k_candidates
        self.top_k_final = top_k_final
        self.use_reranker = use_reranker
        self.last_error = ""
        self.last_stage = ""
        self._store = VectorStore(
            collection_name=collection_name,
            dimensions=embedder.dimensions,
            url=qdrant_url,
            in_memory=in_memory,
            ensure_collection=in_memory,
        )
        self._reranker = None

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        """Embed query, search Qdrant, optionally rerank. Returns top_k_final chunks."""
        self.last_error = ""
        self.last_stage = ""
        try:
            query_vectors = self.embedder.embed([query])
        except Exception as exc:
            self.last_error = str(exc)
            self.last_stage = "embedding"
            return []
        if not query_vectors:
            return []

        try:
            candidates_raw = self._store.search(
                query_vector=query_vectors[0],
                top_k=self.top_k_candidates,
            )
        except Exception as exc:
            self.last_error = str(exc)
            self.last_stage = "vector_store"
            return []
        if not candidates_raw:
            return []

        candidates = [
            RetrievedChunk(
                url=c.get("url", ""),
                title=c.get("title", ""),
                text=c.get("text", ""),
                section_heading=c.get("section_heading", ""),
                score=c.get("score", 0.0),
                chunk_index=c.get("chunk_index", 0),
                page_type=c.get("page_type", ""),
                source_type=c.get("source_type", ""),
                job_id=c.get("job_id", ""),
            )
            for c in candidates_raw
        ]

        if self.use_reranker and len(candidates) > 1:
            candidates = self._rerank(query, candidates)

        return candidates[:self.top_k_final]

    def _load_reranker(self):
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            except ImportError:
                return None
        return self._reranker

    def _rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        reranker = self._load_reranker()
        if reranker is None:
            return candidates
        try:
            scores = reranker.predict([(query, c.text) for c in candidates])
            for chunk, score in zip(candidates, scores):
                chunk.score = float(score)
            return sorted(candidates, key=lambda c: c.score, reverse=True)
        except Exception:
            return candidates
