from company_intel.models import CrawlJob, CrawlSettings
from indexer.qdrant_status import QdrantCollectionsStatus
from pages.index_page import _job_index_status_rows


def _job(job_id: str, domain: str) -> CrawlJob:
    return CrawlJob(
        job_id=job_id,
        domain=domain,
        settings=CrawlSettings(start_url=f"https://{domain}"),
        status="completed",
        pages_scraped=42,
    )


def test_job_index_status_rows_marks_internal_and_full_targets():
    jobs = [_job("job-1", "example.com"), _job("job-2", "acme.com")]
    indexed_targets = [
        {
            "job_id": "job-1",
            "include_external": False,
            "collection_name": "job-1-internal",
            "indexed_at": "2026-03-25T14:00:00+00:00",
        },
        {
            "job_id": "job-1",
            "include_external": True,
            "collection_name": "job-1-full",
            "indexed_at": "2026-03-25T14:05:00+00:00",
        },
    ]

    rows = _job_index_status_rows(
        jobs,
        indexed_targets,
        QdrantCollectionsStatus(reachable=True, collections=frozenset({"job-1-internal", "job-1-full"})),
    )

    assert rows[0]["Internal Only"] == "Indexed"
    assert rows[0]["Internal + External"] == "Indexed"
    assert rows[0]["Last Indexed"] == "2026-03-25 10:05:00 EDT"
    assert rows[1]["Internal Only"] == "Not indexed"
    assert rows[1]["Internal + External"] == "Not indexed"


def test_job_index_status_rows_marks_missing_and_unavailable_states():
    jobs = [_job("job-1", "example.com")]
    indexed_targets = [
        {
            "job_id": "job-1",
            "include_external": False,
            "collection_name": "job-1-internal",
            "indexed_at": "2026-03-25T14:00:00+00:00",
        },
        {
            "job_id": "job-1",
            "include_external": True,
            "collection_name": "job-1-full",
            "indexed_at": "2026-03-25T14:05:00+00:00",
        },
    ]

    missing_rows = _job_index_status_rows(
        jobs,
        indexed_targets,
        QdrantCollectionsStatus(reachable=True, collections=frozenset({"job-1-internal"})),
    )
    unavailable_rows = _job_index_status_rows(
        jobs,
        indexed_targets,
        QdrantCollectionsStatus(reachable=False, collections=frozenset(), error="connection refused"),
    )

    assert missing_rows[0]["Internal Only"] == "Indexed"
    assert missing_rows[0]["Internal + External"] == "Missing in Qdrant"
    assert unavailable_rows[0]["Internal Only"] == "Qdrant unavailable"
    assert unavailable_rows[0]["Internal + External"] == "Qdrant unavailable"
