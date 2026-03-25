from __future__ import annotations

from dataclasses import dataclass

from qdrant_client import QdrantClient


STATE_INDEXED = "indexed"
STATE_MISSING = "missing"
STATE_NOT_INDEXED = "not_indexed"
STATE_UNAVAILABLE = "unavailable"

_STATE_LABELS = {
    STATE_INDEXED: "Indexed",
    STATE_MISSING: "Missing in Qdrant",
    STATE_NOT_INDEXED: "Not indexed",
    STATE_UNAVAILABLE: "Qdrant unavailable",
}


@dataclass(frozen=True)
class QdrantCollectionsStatus:
    reachable: bool
    collections: frozenset[str]
    error: str = ""

    def collection_state(self, collection_name: str) -> str:
        if not self.reachable:
            return STATE_UNAVAILABLE
        if collection_name and collection_name in self.collections:
            return STATE_INDEXED
        return STATE_MISSING


def fetch_qdrant_collections_status(qdrant_url: str) -> QdrantCollectionsStatus:
    try:
        client = QdrantClient(url=qdrant_url)
        collections = frozenset(item.name for item in client.get_collections().collections)
        return QdrantCollectionsStatus(reachable=True, collections=collections)
    except Exception as exc:
        return QdrantCollectionsStatus(reachable=False, collections=frozenset(), error=str(exc))


def tracked_target_state(target: dict | None, qdrant_status: QdrantCollectionsStatus) -> str:
    if not target or not target.get("collection_name"):
        return STATE_NOT_INDEXED
    return qdrant_status.collection_state(str(target.get("collection_name") or ""))


def qdrant_state_label(state: str) -> str:
    return _STATE_LABELS.get(state, state)


def stale_registry_target_ids(targets: list[dict], qdrant_status: QdrantCollectionsStatus) -> list[str]:
    if not qdrant_status.reachable:
        return []
    stale_ids: list[str] = []
    for target in targets:
        target_id = str(target.get("target_id") or "").strip()
        if not target_id:
            continue
        if tracked_target_state(target, qdrant_status) == STATE_MISSING:
            stale_ids.append(target_id)
    return stale_ids
