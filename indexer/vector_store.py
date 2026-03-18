# indexer/vector_store.py
"""
Qdrant vector store wrapper.

Provides upsert, hybrid search (dense), delete, and collection stats.
Uses qdrant-client's in-memory mode for testing.

Collection schema:
  - Vectors: dense, size=dimensions
  - Payload: url, title, page_type, chunk_index, section_heading, text
"""
import hashlib
from typing import Optional
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter,
    FieldCondition, MatchValue,
)


class VectorStore:
    """Qdrant-backed vector store for RAG chunks."""

    def __init__(self, collection_name: str, dimensions: int,
                 url: Optional[str] = None, in_memory: bool = False):
        """
        Args:
            collection_name: Qdrant collection name (e.g. domain slug)
            dimensions: Embedding vector size (e.g. 1024 for BGE-M3)
            url: Qdrant server URL (e.g. "http://localhost:6333")
                 If None and in_memory=False, defaults to "http://localhost:6333"
            in_memory: Use in-memory Qdrant (for testing, no server needed)
        """
        self.collection_name = collection_name
        self.dimensions = dimensions

        if in_memory:
            self._client = QdrantClient(":memory:")
        else:
            self._client = QdrantClient(url=url or "http://localhost:6333")

        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist."""
        existing = {c.name for c in self._client.get_collections().collections}
        if self.collection_name not in existing:
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self.dimensions, distance=Distance.COSINE),
            )

    def upsert(self, chunks: list[dict]) -> int:
        """
        Upsert chunks into Qdrant.

        Each chunk dict must have:
          - id: str (unique, e.g. url + chunk_index)
          - vector: list[float]
          - payload: dict with url, title, page_type, chunk_index, section_heading, text

        Returns number of chunks upserted.
        """
        if not chunks:
            return 0

        points = []
        for chunk in chunks:
            # Use deterministic SHA-256 hash of id string as integer point ID
            point_id = int(hashlib.sha256(chunk["id"].encode()).hexdigest()[:15], 16)
            points.append(PointStruct(
                id=point_id,
                vector=chunk["vector"],
                payload=chunk.get("payload", {}),
            ))

        self._client.upsert(collection_name=self.collection_name, points=points)
        return len(points)

    def search(self, query_vector: list[float], top_k: int = 10,
               filter_url: Optional[str] = None) -> list[dict]:
        """
        Search for similar chunks.

        Args:
            query_vector: Dense query embedding
            top_k: Number of results to return
            filter_url: If set, restrict to chunks from this URL

        Returns list of dicts with keys: score, url, title, page_type,
                chunk_index, section_heading, text
        """
        search_filter = None
        if filter_url:
            search_filter = Filter(
                must=[FieldCondition(key="url", match=MatchValue(value=filter_url))]
            )

        response = self._client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=search_filter,
            with_payload=True,
        )

        return [
            {
                "score": r.score,
                **r.payload,
            }
            for r in response.points
        ]

    def delete_by_url(self, url: str) -> None:
        """Delete all chunks for a given URL."""
        self._client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="url", match=MatchValue(value=url))]
            ),
        )

    def get_collection_stats(self) -> dict:
        """Return collection stats: total_vectors, dimensions, collection_name."""
        info = self._client.get_collection(self.collection_name)
        return {
            "collection_name": self.collection_name,
            "total_vectors": info.points_count or 0,
            "dimensions": self.dimensions,
            "status": str(info.status),
        }

    def count(self) -> int:
        """Return total number of vectors in the collection."""
        return self._client.count(self.collection_name).count
