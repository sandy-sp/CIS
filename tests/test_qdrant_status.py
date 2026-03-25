from indexer.qdrant_status import (
    QdrantCollectionsStatus,
    STATE_INDEXED,
    STATE_MISSING,
    STATE_NOT_INDEXED,
    STATE_UNAVAILABLE,
    qdrant_state_label,
    stale_registry_target_ids,
    tracked_target_state,
)


def test_tracked_target_state_distinguishes_index_states():
    target = {"target_id": "job:abc:internal", "collection_name": "company-intel-abc"}
    reachable = QdrantCollectionsStatus(reachable=True, collections=frozenset({"company-intel-abc"}))
    missing = QdrantCollectionsStatus(reachable=True, collections=frozenset())
    unavailable = QdrantCollectionsStatus(reachable=False, collections=frozenset(), error="timeout")

    assert tracked_target_state(target, reachable) == STATE_INDEXED
    assert tracked_target_state(target, missing) == STATE_MISSING
    assert tracked_target_state(target, unavailable) == STATE_UNAVAILABLE
    assert tracked_target_state(None, reachable) == STATE_NOT_INDEXED


def test_qdrant_state_label_maps_states():
    assert qdrant_state_label(STATE_INDEXED) == "Indexed"
    assert qdrant_state_label(STATE_MISSING) == "Missing in Qdrant"
    assert qdrant_state_label(STATE_NOT_INDEXED) == "Not indexed"
    assert qdrant_state_label(STATE_UNAVAILABLE) == "Qdrant unavailable"


def test_stale_registry_target_ids_only_returns_missing_targets_when_reachable():
    targets = [
        {"target_id": "job:1:internal", "collection_name": "company-intel-1"},
        {"target_id": "job:2:internal", "collection_name": "company-intel-2"},
    ]

    reachable = QdrantCollectionsStatus(reachable=True, collections=frozenset({"company-intel-1"}))
    unavailable = QdrantCollectionsStatus(reachable=False, collections=frozenset(), error="connection refused")

    assert stale_registry_target_ids(targets, reachable) == ["job:2:internal"]
    assert stale_registry_target_ids(targets, unavailable) == []
