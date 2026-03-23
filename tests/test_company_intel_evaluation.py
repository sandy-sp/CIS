import json

from company_intel.evaluation import (
    BenchmarkCase,
    build_benchmark_draft,
    build_job_benchmark_draft,
    evaluate_entities,
    evaluate_job,
    write_report,
)
from company_intel.models import CrawlSettings, ExtractedEntity
from company_intel.storage import JobStorage


def test_evaluate_entities_scores_matches_and_attribute_checks():
    benchmark = BenchmarkCase.from_dict({
        "name": "Example Benchmark",
        "company_domain": "example.com",
        "entities": {
            "services": [
                {
                    "name": "Data Platform Services",
                    "attribute_checks": {
                        "summary": {"contains": "scientific data platform"},
                    },
                    "source_url_contains": ["/services/data-platform"],
                }
            ],
            "people": [
                {
                    "name": "Christopher McClure",
                    "aliases": ["Chris McClure"],
                    "attribute_checks": {
                        "title": {"contains": "Director"},
                        "linkedin_url": {"contains": "linkedin.com/in/"},
                    },
                }
            ],
        },
    })
    predicted = {
        "services": [
            ExtractedEntity(
                entity_type="service",
                normalized_key="data-platform-services",
                display_name="Data Platform Services",
                attributes={"summary": "Build a modern scientific data platform for regulated teams."},
                source_urls=["https://example.com/services/data-platform"],
                confidence="high",
            ),
            ExtractedEntity(
                entity_type="service",
                normalized_key="managed-lims",
                display_name="Managed LIMS",
                attributes={"summary": "Unexpected extra service."},
                source_urls=["https://example.com/services/managed-lims"],
                confidence="medium",
            ),
        ],
        "people": [
            ExtractedEntity(
                entity_type="person",
                normalized_key="christopher-mcclure",
                display_name="Chris McClure",
                attributes={
                    "title": "Director, Sales & BD",
                    "linkedin_url": "https://www.linkedin.com/in/christopher-mcclure-123456/",
                },
                source_urls=["https://example.com/our-people"],
                confidence="high",
            )
        ],
    }

    report = evaluate_entities(predicted, benchmark, job_id="job-123")

    overall = report.overall()
    assert overall["gold_count"] == 2
    assert overall["predicted_count"] == 3
    assert overall["matched_count"] == 2
    assert overall["precision"] == 0.6667
    assert overall["recall"] == 1.0
    assert overall["attribute_accuracy"] == 1.0
    assert overall["source_url_accuracy"] == 1.0
    assert report.entity_types["services"].unexpected == ["Managed LIMS"]
    assert report.entity_types["people"].matches[0].predicted_name == "Chris McClure"


def test_evaluate_job_reads_entities_from_storage_and_writes_reports(tmp_path):
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

    benchmark = BenchmarkCase.from_dict({
        "name": "Stored Benchmark",
        "company_domain": "example.com",
        "entities": {
            "services": [
                {
                    "name": "Data Platform Services",
                    "attribute_checks": {
                        "summary": {"contains": "data platform"},
                    },
                }
            ]
        },
    })

    report = evaluate_job(job.job_id, benchmark, storage=storage)
    json_path, md_path = write_report(report, storage.job_dir(job.job_id) / "exports" / "evaluation")

    assert report.job_id == job.job_id
    assert json_path.exists()
    assert md_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["overall"]["matched_count"] == 1
    assert "Stored Benchmark" in md_path.read_text(encoding="utf-8")


def test_build_benchmark_draft_seeds_reviewable_checks():
    predicted = {
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
        ],
        "events": [
            ExtractedEntity(
                entity_type="event",
                normalized_key="future-labs-2026",
                display_name="Future Labs 2026",
                attributes={"date": "March 24, 2026", "location": "Boston"},
                source_urls=["https://example.com/events/future-labs-2026"],
                confidence="high",
            )
        ],
    }

    benchmark = build_benchmark_draft(
        predicted,
        name="Draft",
        company_domain="example.com",
    )

    person = benchmark.entities["people"][0]
    event = benchmark.entities["events"][0]

    assert person.attribute_checks["title"]["contains"] == "Director, Sales & BD"
    assert person.attribute_checks["linkedin_url"]["contains"].startswith("https://www.linkedin.com/")
    assert person.source_url_contains == ["/our-people"]
    assert event.attribute_checks["location"]["equals"] == "Boston"
    assert event.source_url_contains == ["/events/future-labs-2026"]


def test_build_job_benchmark_draft_uses_saved_entities(tmp_path):
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

    benchmark = build_job_benchmark_draft(job.job_id, storage=storage, limit_per_type=10)

    assert benchmark.company_domain == "example.com"
    assert benchmark.name == "example.com Benchmark Draft"
    assert benchmark.entities["services"][0].source_url_contains == ["/services/data-platform"]


def test_benchmark_case_preserves_explicit_empty_entity_types():
    benchmark = BenchmarkCase.from_dict({
        "name": "Empty Types",
        "entities": {
            "customers": [],
            "case_studies": [],
        },
    })

    assert benchmark.entities["customers"] == []
    assert benchmark.entities["case_studies"] == []


def test_evaluate_entities_penalizes_predictions_for_explicit_empty_types():
    benchmark = BenchmarkCase.from_dict({
        "name": "Explicitly Empty Customers",
        "entities": {
            "customers": [],
        },
    })
    predicted = {
        "customers": [
            ExtractedEntity(
                entity_type="customer",
                normalized_key="acme-biotech",
                display_name="Acme Biotech",
                source_urls=["https://example.com/case-studies/acme"],
            )
        ]
    }

    report = evaluate_entities(predicted, benchmark)

    assert report.entity_types["customers"].gold_count == 0
    assert report.entity_types["customers"].predicted_count == 1
    assert report.entity_types["customers"].unexpected == ["Acme Biotech"]
