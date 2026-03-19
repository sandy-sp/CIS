from company_intel.models import PageRecord
from company_intel.review import external_review_status, filter_records_for_outputs, set_external_review_status


def test_external_review_status_defaults_by_discovery_mode():
    site_link = PageRecord(
        url="https://linkedin.com/company/example",
        normalized_url="https://linkedin.com/company/example",
        domain="linkedin.com",
        path="/company/example",
        source_type="external",
        discovered_via="site-external-link",
        metadata={},
    )
    search_hit = PageRecord(
        url="https://news.example.org/example",
        normalized_url="https://news.example.org/example",
        domain="news.example.org",
        path="/example",
        source_type="external",
        discovered_via="search",
        metadata={},
    )

    assert external_review_status(site_link) == "approved"
    assert external_review_status(search_hit) == "pending"


def test_filter_records_for_outputs_only_keeps_approved_external():
    internal = PageRecord(
        url="https://example.com/about",
        normalized_url="https://example.com/about",
        domain="example.com",
        path="/about",
        source_type="internal",
    )
    approved_external = PageRecord(
        url="https://linkedin.com/company/example",
        normalized_url="https://linkedin.com/company/example",
        domain="linkedin.com",
        path="/company/example",
        source_type="external",
        metadata={"review_status": "approved"},
    )
    pending_external = PageRecord(
        url="https://news.example.org/example",
        normalized_url="https://news.example.org/example",
        domain="news.example.org",
        path="/example",
        source_type="external",
        metadata={"review_status": "pending"},
    )

    records = filter_records_for_outputs([internal, approved_external, pending_external])

    assert internal in records
    assert approved_external in records
    assert pending_external not in records


def test_set_external_review_status_marks_record():
    record = PageRecord(
        url="https://news.example.org/example",
        normalized_url="https://news.example.org/example",
        domain="news.example.org",
        path="/example",
        source_type="external",
        metadata={},
    )

    set_external_review_status(record, "rejected")

    assert record.metadata["review_status"] == "rejected"
    assert record.metadata["review_source"] == "manual"
    assert record.metadata["reviewed_at"]
