from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from company_intel.job_runner import JobRunner
from company_intel.models import CrawlSettings, PageRecord
from company_intel.storage import JobStorage
from indexer.registry import IndexRegistry


def _make_record(url: str, source_type: str = "internal", status: str = "success") -> PageRecord:
    return PageRecord(
        url=url,
        normalized_url=url,
        domain="example.com",
        path="/",
        source_type=source_type,
        markdown="# Title\n\nContent",
        clean_text="Title Content",
        raw_text="Title Content",
        title="Title",
        page_category="company",
        status=status,
        word_count=2,
    )


def test_prepare_live_index_registers_target(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    registry = IndexRegistry(path=tmp_path / "index_registry.json")
    runner = JobRunner(storage=storage, index_registry=registry, qdrant_url="http://qdrant:6333")
    job = storage.create_job(CrawlSettings(start_url="https://example.com", enable_rag_index=True))

    class DummyEmbedder:
        dimensions = 1024
        _model_name = "nomic-embed-text"

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def health_check(self):
            return {"dimensions": self.dimensions}

    class DummyPipeline:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    settings_store = MagicMock()
    settings_store.load.return_value = {
        "embedding_backend": "ollama",
        "embedding_api_key": "",
        "embedding_model": "nomic-embed-text",
        "ollama_url": "http://ollama:11434",
    }

    with patch("company_intel.job_runner.SettingsStore", return_value=settings_store), \
         patch("company_intel.job_runner.Embedder", DummyEmbedder), \
         patch("company_intel.job_runner.IndexerPipeline", DummyPipeline):
        pipeline, target, warning = runner._prepare_live_index(job)

    assert warning == ""
    assert isinstance(pipeline, DummyPipeline)
    assert target is not None
    assert target["embedding_backend"] == "ollama"
    assert target["embedding_model"] == "nomic-embed-text"
    saved = registry.get_target(target["target_id"])
    assert saved is not None
    assert saved["collection_name"] == target["collection_name"]


def test_prepare_live_index_warns_when_openai_key_missing(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    registry = IndexRegistry(path=tmp_path / "index_registry.json")
    runner = JobRunner(storage=storage, index_registry=registry)
    job = storage.create_job(CrawlSettings(start_url="https://example.com", enable_rag_index=True))

    settings_store = MagicMock()
    settings_store.load.return_value = {
        "embedding_backend": "openai",
        "embedding_api_key": "",
        "embedding_model": "text-embedding-3-small",
        "ollama_url": "http://ollama:11434",
    }

    with patch("company_intel.job_runner.SettingsStore", return_value=settings_store):
        pipeline, target, warning = runner._prepare_live_index(job)

    assert pipeline is None
    assert target is None
    assert "no api key" in warning.lower()
    assert registry.list_targets() == []


def test_index_live_records_only_indexes_internal_success_records(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    runner = JobRunner(storage=storage, index_registry=IndexRegistry(path=tmp_path / "index_registry.json"))
    job = storage.create_job(CrawlSettings(start_url="https://example.com", enable_rag_index=True))

    pipeline = MagicMock()
    pipeline.run.return_value = iter([SimpleNamespace(error="")])

    internal_ok = _make_record("https://example.com/about")
    external_ok = _make_record("https://linkedin.com/company/example", source_type="external")
    internal_failed = _make_record("https://example.com/bad", status="failed")

    warning = runner._index_live_records(pipeline, job, [internal_ok, external_ok, internal_failed])

    assert warning == ""
    pipeline.run.assert_called_once()
    indexed_records = pipeline.run.call_args.kwargs["page_records"]
    assert indexed_records == [internal_ok]


def test_finalize_live_index_updates_registry_stats(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    registry = IndexRegistry(path=tmp_path / "index_registry.json")
    runner = JobRunner(storage=storage, index_registry=registry)
    job = storage.create_job(CrawlSettings(start_url="https://example.com", enable_rag_index=True))

    target = {
        "target_id": "job:test:full",
        "label": "example.com (internal + external)",
        "collection_name": "company-intel-example",
        "source_kind": "company_job",
        "job_id": job.job_id,
        "domain": job.domain,
        "include_external": True,
        "embedding_backend": "ollama",
        "embedding_model": "nomic-embed-text",
        "embedding_ollama_url": "http://ollama:11434",
        "dimensions": 1024,
    }

    pipeline = MagicMock()
    pipeline.replace_job_collection.return_value = iter([SimpleNamespace(error="")])
    pipeline.get_stats.return_value = {
        "collection_name": "company-intel-example",
        "total_vectors": 12,
        "dimensions": 1024,
    }

    warning = runner._finalize_live_index(job, pipeline, target)

    assert warning == ""
    saved = registry.get_target(target["target_id"])
    assert saved is not None
    assert saved["stats"]["total_vectors"] == 12
