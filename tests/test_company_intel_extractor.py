from company_intel.extractor import UniversalExtractor
from company_intel.models import PageRecord


def test_universal_extractor_builds_core_entities():
    records = [
        PageRecord(
            url="https://example.com/",
            normalized_url="https://example.com/",
            domain="example.com",
            path="/",
            title="Example Biotech | Example",
            description="Example is a biotech informatics company.",
            markdown="# Example\n\nExample is a biotech informatics company.",
            clean_text="Example is a biotech informatics company.",
            page_category="homepage",
            status="success",
            word_count=7,
        ),
        PageRecord(
            url="https://example.com/services/data-platform",
            normalized_url="https://example.com/services/data-platform",
            domain="example.com",
            path="/services/data-platform",
            title="Data Platform Services | Example",
            description="Build a modern scientific data platform.",
            markdown="# Data Platform Services\n\nBuild a modern scientific data platform.",
            clean_text="Build a modern scientific data platform.",
            page_category="services",
            status="success",
            word_count=7,
        ),
        PageRecord(
            url="https://example.com/partners",
            normalized_url="https://example.com/partners",
            domain="example.com",
            path="/partners",
            title="Partners | Example",
            markdown="## Analytics\n* Benchling\n## Project Inquiry\n* Contact",
            clean_text="Analytics Benchling Project Inquiry Contact",
            page_category="partners",
            status="success",
            word_count=5,
        ),
        PageRecord(
            url="https://example.com/our-people",
            normalized_url="https://example.com/our-people",
            domain="example.com",
            path="/our-people",
            title="Our People | Example",
            markdown=(
                "# Our People\n\n"
                "Christopher McClure\n"
                "Director, Sales & BD\n"
                "[Christopher McClure](https://www.linkedin.com/in/christopher-mcclure-123456/)"
            ),
            clean_text="Christopher McClure Director, Sales & BD",
            page_category="people",
            status="success",
            word_count=6,
        ),
        PageRecord(
            url="https://example.com/event/future-labs-2026",
            normalized_url="https://example.com/event/future-labs-2026",
            domain="example.com",
            path="/event/future-labs-2026",
            title="Future Labs 2026 | Boston",
            description="Join us in Boston on March 24, 2026.",
            markdown="# Future Labs 2026\n\nJoin us in Boston on March 24, 2026.",
            clean_text="Join us in Boston on March 24, 2026.",
            page_category="events",
            status="success",
            word_count=9,
        ),
        PageRecord(
            url="https://example.com/case-studies/acme",
            normalized_url="https://example.com/case-studies/acme",
            domain="example.com",
            path="/case-studies/acme",
            title="Acme Transformation Case Study",
            description="Customer: Acme Biotech",
            markdown="# Acme Transformation Case Study\n\nCustomer: Acme Biotech",
            clean_text="Customer: Acme Biotech",
            page_category="case-studies",
            status="success",
            word_count=4,
        ),
    ]

    entities = UniversalExtractor().extract(records, "example.com")

    assert len(entities["company_profile"]) == 1
    assert len(entities["services"]) == 1
    assert entities["partners"][0].display_name == "Benchling"
    assert entities["people"][0].display_name == "Christopher McClure"
    assert entities["people"][0].attributes["title"] == "Director, Sales & BD"
    assert entities["events"][0].attributes["location"] == "Boston"
    assert any(entity.display_name == "Acme Biotech" for entity in entities["customers"])
