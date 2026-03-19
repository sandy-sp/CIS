from pathlib import Path

from indexer.registry import IndexRegistry


def test_registry_saves_and_lists_targets(tmp_path):
    registry = IndexRegistry(path=tmp_path / "index_registry.json")
    saved = registry.save_target({
        "target_id": "job:abc:full",
        "label": "example.com (internal + external)",
        "collection_name": "company-intel-example",
        "source_kind": "company_job",
    })

    targets = registry.list_targets()

    assert len(targets) == 1
    assert targets[0]["target_id"] == "job:abc:full"
    assert saved["indexed_at"]


def test_registry_updates_existing_target(tmp_path):
    registry = IndexRegistry(path=tmp_path / "index_registry.json")
    registry.save_target({
        "target_id": "job:abc:internal",
        "label": "example.com (internal only)",
        "collection_name": "company-intel-example",
        "source_kind": "company_job",
        "indexed_at": "2026-03-18T10:00:00+00:00",
    })
    registry.save_target({
        "target_id": "job:abc:internal",
        "label": "example.com (internal + reviewed externals)",
        "collection_name": "company-intel-example",
        "source_kind": "company_job",
        "indexed_at": "2026-03-18T11:00:00+00:00",
    })

    targets = registry.list_targets()

    assert len(targets) == 1
    assert targets[0]["label"] == "example.com (internal + reviewed externals)"
    assert targets[0]["indexed_at"] == "2026-03-18T11:00:00+00:00"


def test_registry_removes_target(tmp_path):
    registry = IndexRegistry(path=tmp_path / "index_registry.json")
    registry.save_target({
        "target_id": "job:abc:full",
        "label": "example.com",
        "collection_name": "company-intel-example",
        "source_kind": "company_job",
    })

    registry.remove_target("job:abc:full")

    assert registry.list_targets() == []
