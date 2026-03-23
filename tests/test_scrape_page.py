import json

from company_intel.models import CrawlSettings, ExtractedEntity
from company_intel.storage import JobStorage
from pages.scrape_page import (
    _benchmark_entity_detail,
    _benchmark_repo_file_name,
    _build_benchmark_draft_payload,
    _evaluate_benchmark_payload,
    _external_review_rows,
    _normalize_benchmark_payload,
    _save_curated_benchmark,
)


def test_external_review_rows_extract_metadata():
    rows = _external_review_rows([
        {
            "url": "https://www.linkedin.com/company/example",
            "domain": "linkedin.com",
            "source_type": "external",
            "discovered_via": "search",
            "page_category": "external-profile",
            "status": "success",
            "metadata": {
                "review_score": 91,
                "review_status": "approved",
                "review_reason": "Search-discovered on linkedin.com | query type: company_profile | rank 1",
                "search_provider": "duckduckgo",
                "search_kind": "company_profile",
                "search_rank": 1,
                "search_query": 'site:linkedin.com/company "Example"',
            },
        },
        {
            "url": "https://example.com/about",
            "domain": "example.com",
            "source_type": "internal",
            "discovered_via": "crawl",
            "page_category": "company",
            "status": "success",
            "metadata": {},
        },
    ])

    assert len(rows) == 1
    assert rows[0]["Domain"] == "linkedin.com"
    assert rows[0]["Score"] == 91
    assert rows[0]["Review Status"] == "approved"
    assert rows[0]["Query Type"] == "company_profile"


def test_build_benchmark_draft_payload_generates_downloadable_json(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    job.status = "completed"
    storage.save_job(job)
    storage.write_entities(job.job_id, {
        "people": [
            ExtractedEntity(
                entity_type="person",
                normalized_key="christopher-mcclure",
                display_name="Christopher McClure",
                attributes={
                    "title": "Director, Sales & BD",
                    "linkedin_url": "https://www.linkedin.com/in/christopher-mcclure-123456/",
                },
                source_urls=["https://example.com/our-people"],
                confidence="high",
            )
        ]
    })

    filename, payload, summary = _build_benchmark_draft_payload(
        job.job_id,
        limit_per_type=10,
        entity_types=["people"],
        storage=storage,
    )

    assert filename == "example.com-benchmark-draft.json"
    assert summary == {"people": 1}
    body = json.loads(payload.decode("utf-8"))
    assert body["company_domain"] == "example.com"
    assert body["entities"]["people"][0]["attribute_checks"]["title"]["contains"] == "Director, Sales & BD"


def test_evaluate_benchmark_payload_returns_report_artifacts(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    job.status = "completed"
    storage.save_job(job)
    storage.write_entities(job.job_id, {
        "services": [
            ExtractedEntity(
                entity_type="service",
                normalized_key="data-platform-services",
                display_name="Data Platform Services",
                attributes={"summary": "Scientific data platform delivery"},
                source_urls=["https://example.com/services/data-platform"],
                confidence="high",
            )
        ]
    })
    benchmark_payload = json.dumps({
        "name": "Example Benchmark",
        "company_domain": "example.com",
        "entities": {
            "services": [
                {
                    "name": "Data Platform Services",
                    "attribute_checks": {
                        "summary": {"contains": "data platform"}
                    },
                    "source_url_contains": ["/services/data-platform"]
                }
            ]
        }
    }).encode("utf-8")

    result = _evaluate_benchmark_payload(
        job.job_id,
        benchmark_payload,
        "example-benchmark.json",
        storage=storage,
    )

    assert result["benchmark_name"] == "Example Benchmark"
    assert result["overall"]["matched_count"] == 1
    assert result["overall"]["precision"] == 1.0
    assert result["rows"][0]["Entity Type"] == "services"
    assert "services" in result["details"]["entity_types"]
    assert "Benchmark Report" in result["markdown_bytes"].decode("utf-8")


def test_benchmark_entity_detail_formats_match_missing_and_unexpected_rows(tmp_path):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    job.status = "completed"
    storage.save_job(job)
    storage.write_entities(job.job_id, {
        "services": [
            ExtractedEntity(
                entity_type="service",
                normalized_key="data-platform-services",
                display_name="Data Platform Services",
                attributes={"summary": "Scientific data platform delivery"},
                source_urls=["https://example.com/services/data-platform"],
                confidence="high",
            ),
            ExtractedEntity(
                entity_type="service",
                normalized_key="validation-consulting",
                display_name="Validation Consulting",
                attributes={"summary": "Validation and quality consulting"},
                source_urls=["https://example.com/services/validation"],
                confidence="medium",
            ),
        ]
    })
    benchmark_payload = json.dumps({
        "name": "Example Benchmark",
        "company_domain": "example.com",
        "entities": {
            "services": [
                {
                    "name": "Data Platform Services",
                    "attribute_checks": {
                        "summary": {"contains": "data platform"}
                    },
                    "source_url_contains": ["/services/data-platform"],
                    "notes": "Primary service benchmark row",
                },
                {
                    "name": "Quality Engineering",
                    "attribute_checks": {
                        "summary": {"contains": "quality"}
                    },
                },
            ]
        }
    }).encode("utf-8")

    result = _evaluate_benchmark_payload(
        job.job_id,
        benchmark_payload,
        "example-benchmark.json",
        storage=storage,
    )
    detail = _benchmark_entity_detail(result["details"], "services")

    assert len(detail["matches"]) == 2
    assert detail["matches"][0]["Expected"] == "Data Platform Services"
    assert detail["matches"][0]["Predicted"] == "Data Platform Services"
    assert detail["matches"][0]["Matched"] == "yes"
    assert detail["matches"][0]["Checks Passed"] == "1/1"
    assert detail["matches"][0]["Source URL Checks"] == "1/1"
    assert detail["matches"][0]["Notes"] == "Primary service benchmark row"
    assert detail["matches"][1]["Expected"] == "Quality Engineering"
    assert detail["matches"][1]["Predicted"] == ""
    assert detail["matches"][1]["Matched"] == ""
    assert detail["missing"] == ["Quality Engineering"]
    assert detail["unexpected"] == ["Validation Consulting"]


def test_normalize_benchmark_payload_returns_summary_and_pretty_json():
    benchmark_payload = json.dumps({
        "name": "Example Benchmark",
        "company_domain": "example.com",
        "entities": {
            "services": [
                {"name": "Data Platform Services"},
                {"name": "Validation Consulting"},
            ],
            "people": [
                {"name": "Christopher McClure"},
            ],
        },
    }).encode("utf-8")

    benchmark, normalized, summary = _normalize_benchmark_payload(benchmark_payload)

    assert benchmark.name == "Example Benchmark"
    assert summary == {"people": 1, "services": 2}
    body = json.loads(normalized.decode("utf-8"))
    assert body["company_domain"] == "example.com"
    assert body["entities"]["services"][0]["name"] == "Data Platform Services"


def test_save_curated_benchmark_sanitizes_file_name_and_writes_json(tmp_path):
    benchmark_payload = json.dumps({
        "name": "Example Benchmark",
        "company_domain": "example.com",
        "entities": {
            "services": [
                {"name": "Data Platform Services"},
            ],
        },
    }).encode("utf-8")

    output_path, summary = _save_curated_benchmark(
        benchmark_payload,
        "../Example Benchmark v1.json",
        benchmarks_dir=tmp_path / "benchmarks",
    )

    assert output_path.name == _benchmark_repo_file_name("../Example Benchmark v1.json")
    assert summary == {"services": 1}
    body = json.loads(output_path.read_text(encoding="utf-8"))
    assert body["name"] == "Example Benchmark"
