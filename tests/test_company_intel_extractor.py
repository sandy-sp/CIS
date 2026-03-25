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


def test_universal_extractor_filters_noise_from_people_and_partners():
    records = [
        PageRecord(
            url="https://example.com/partners",
            normalized_url="https://example.com/partners",
            domain="example.com",
            path="/partners",
            title="Our Partnerships | Example",
            markdown=(
                "# Our Partnerships\n\n"
                "## AI & Semantics\n"
                "* SciBite\n"
                "* Smartlogic\n"
                "## Interested in partnering with Zifo?\n"
                "[ Know More ](/contact)\n"
            ),
            clean_text="SciBite Smartlogic",
            page_category="partners",
            status="success",
            word_count=15,
        ),
        PageRecord(
            url="https://example.com/our-people",
            normalized_url="https://example.com/our-people",
            domain="example.com",
            path="/our-people",
            title="Our People | Example",
            markdown=(
                "# Our People\n\n"
                "* Careers\n"
                "* Employee Stories\n"
                "Christopher McClure\n"
                "Director, Sales & BD\n"
                "Suchitra Ramaswamy (Suchi)\n"
                "Client Partner\n"
                "[ Know More ](/our-culture)\n"
            ),
            clean_text="Christopher McClure Director, Sales & BD Suchitra Ramaswamy Client Partner",
            page_category="people",
            status="success",
            word_count=20,
        ),
        PageRecord(
            url="https://example.com/blogs/launch",
            normalized_url="https://example.com/blogs/launch",
            domain="example.com",
            path="/blogs/launch",
            title="Launch News",
            markdown="[About Zifo](https://example.com/about)\n[Contact Us](https://example.com/contact)",
            clean_text="About Zifo Contact Us",
            page_category="resources",
            status="success",
            word_count=5,
        ),
    ]

    entities = UniversalExtractor().extract(records, "example.com")

    assert [entity.display_name for entity in entities["partners"]] == ["SciBite", "Smartlogic"]
    assert [entity.display_name for entity in entities["people"]] == [
        "Christopher McClure",
        "Suchitra Ramaswamy (Suchi)",
    ]


def test_universal_extractor_extracts_multiple_events_from_listing_page():
    record = PageRecord(
        url="https://example.com/events",
        normalized_url="https://example.com/events",
        domain="example.com",
        path="/events",
        title="Events | Example",
        description="Join us at leading science and data events.",
        markdown=(
            "## Scientific Informatics Experience Exchange (SiEE) | Boston April 14, 2026\n"
            "Join us in Boston.\n"
            "14\n"
            "Apr\n"
            "[Zifo Signature Event](https://example.com/events/category/zifo-signature-event/)\n"
            "Scientific Informatics Experience Exchange (SiEE) | Boston April 14, 2026\n"
            "Boston, MA\n"
            "[View Details →](https://example.com/event/siee-boston-2026/)\n"
            "07\n"
            "Feb\n"
            "[Industry Event](https://example.com/events/category/industry-event/)\n"
            "SLAS 2026 International Conference & Exhibition\n"
            "Boston, MA\n"
            "[View Details →](https://example.com/event/slas-2026-international-conference-exhibition/)\n"
        ),
        clean_text="Scientific Informatics Experience Exchange Boston SLAS 2026 International Conference Exhibition",
        page_category="events",
        page_subtype="event",
        status="success",
        word_count=60,
    )

    entities = UniversalExtractor().extract([record], "example.com")

    assert [entity.display_name for entity in entities["events"]] == [
        "Scientific Informatics Experience Exchange (SiEE) | Boston April 14, 2026",
        "SLAS 2026 International Conference & Exhibition",
    ]
    assert entities["events"][0].attributes["event_type"] == "company-hosted"
    assert entities["events"][1].attributes["location"] == "Boston, MA"


def test_universal_extractor_customers_require_case_study_evidence():
    records = [
        PageRecord(
            url="https://example.com/blogs/vendor-selection",
            normalized_url="https://example.com/blogs/vendor-selection",
            domain="example.com",
            path="/blogs/vendor-selection",
            title="Vendor Selection",
            markdown="# Vendor Selection\n\nPartnered with Large Language Models",
            clean_text="Partnered with Large Language Models",
            page_category="resources",
            status="success",
            word_count=6,
        ),
        PageRecord(
            url="https://example.com/case-studies/acme",
            normalized_url="https://example.com/case-studies/acme",
            domain="example.com",
            path="/case-studies/acme",
            title="Acme Transformation Case Study",
            markdown="# Acme Transformation Case Study\n\nCustomer: Acme Biotech",
            clean_text="Customer: Acme Biotech",
            page_category="case-studies",
            status="success",
            word_count=4,
        ),
    ]

    entities = UniversalExtractor().extract(records, "example.com")

    assert [entity.display_name for entity in entities["customers"]] == ["Acme Biotech"]


def test_universal_extractor_parses_meet_the_expert_headings():
    record = PageRecord(
        url="https://example.com/thought-leadership/meet-the-expert-amy-scalise",
        normalized_url="https://example.com/thought-leadership/meet-the-expert-amy-scalise",
        domain="example.com",
        path="/thought-leadership/meet-the-expert-amy-scalise",
        title="Meet the Expert: Amy Scalise",
        markdown=(
            'Our "Meet the Expert" series.\n'
            "## Meet Amy Scalise, Associate Director, Decentralized Clinical Trial Management\n"
            "### What do you do at Example?\n"
        ),
        clean_text="Meet Amy Scalise, Associate Director, Decentralized Clinical Trial Management",
        page_category="people",
        status="success",
        word_count=18,
    )

    entities = UniversalExtractor().extract([record], "example.com")

    assert [entity.display_name for entity in entities["people"]] == ["Amy Scalise"]
    assert entities["people"][0].attributes["title"] == "Associate Director, Decentralized Clinical Trial Management"


def test_universal_extractor_handles_nullable_text_fields():
    record = PageRecord(
        url="https://example.com/blogs/launch",
        normalized_url="https://example.com/blogs/launch",
        domain="example.com",
        path="/blogs/launch",
        title="Launch Update",
        description=None,
        markdown="# Launch Update\n\nMarch 24, 2026 launch announcement.",
        clean_text="March 24, 2026 launch announcement.",
        page_category="resources",
        status="success",
        word_count=5,
    )

    entities = UniversalExtractor().extract([record], "example.com")

    assert [entity.display_name for entity in entities["resources"]] == ["Launch Update"]
    assert entities["resources"][0].attributes["date"] == "March 24, 2026"


def test_universal_extractor_filters_non_primary_language_records():
    records = [
        PageRecord(
            url="https://example.com/services/data-platform",
            normalized_url="https://example.com/services/data-platform",
            domain="example.com",
            path="/services/data-platform",
            title="Data Platform Services",
            markdown="# Data Platform Services",
            clean_text="Data Platform Services",
            page_category="services",
            language="en",
            status="success",
            word_count=3,
        ),
        PageRecord(
            url="https://example.com/ja/services/data-platform",
            normalized_url="https://example.com/ja/services/data-platform",
            domain="example.com",
            path="/ja/services/data-platform",
            title="データプラットフォームサービス",
            markdown="# データプラットフォームサービス",
            clean_text="データプラットフォームサービス",
            page_category="services",
            language="ja",
            status="success",
            word_count=1,
        ),
    ]

    entities = UniversalExtractor().extract(records, "example.com")

    assert [entity.display_name for entity in entities["services"]] == ["Data Platform Services"]


def test_universal_extractor_skips_event_resource_and_meeting_pages():
    records = [
        PageRecord(
            url="https://example.com/event/bio-it-world-2024-resources",
            normalized_url="https://example.com/event/bio-it-world-2024-resources",
            domain="example.com",
            path="/event/bio-it-world-2024-resources",
            title="Bio-IT World 2024 Resources",
            markdown="# Bio-IT World 2024 Resources",
            clean_text="Bio-IT World 2024 Resources",
            page_category="events",
            status="success",
            word_count=5,
        ),
        PageRecord(
            url="https://example.com/event/bio-it-world-2024-meet-with-example",
            normalized_url="https://example.com/event/bio-it-world-2024-meet-with-example",
            domain="example.com",
            path="/event/bio-it-world-2024-meet-with-example",
            title="Bio-IT World 2024 | Meet with Example",
            markdown="# Bio-IT World 2024 | Meet with Example",
            clean_text="Bio-IT World 2024 | Meet with Example",
            page_category="events",
            status="success",
            word_count=7,
        ),
        PageRecord(
            url="https://example.com/event/bio-it-world",
            normalized_url="https://example.com/event/bio-it-world",
            domain="example.com",
            path="/event/bio-it-world",
            title="Bio-IT World 2024",
            description="Join us on April 15, 2024.",
            markdown="# Bio-IT World 2024\n\nJoin us on April 15, 2024.",
            clean_text="Join us on April 15, 2024.",
            page_category="events",
            status="success",
            word_count=8,
        ),
    ]

    entities = UniversalExtractor().extract(records, "example.com")

    assert [entity.display_name for entity in entities["events"]] == ["Bio-IT World 2024"]


def test_universal_extractor_skips_marketing_solution_pages_without_service_hints():
    records = [
        PageRecord(
            url="https://example.com/solutions/development",
            normalized_url="https://example.com/solutions/development",
            domain="example.com",
            path="/solutions/development",
            title="Head of Development",
            markdown="# Get access to better data",
            clean_text="Get access to better data",
            page_category="services",
            status="success",
            word_count=6,
        ),
        PageRecord(
            url="https://example.com/services/professional-services",
            normalized_url="https://example.com/services/professional-services",
            domain="example.com",
            path="/services/professional-services",
            title="Professional Services",
            markdown="# Professional Services",
            clean_text="Professional Services",
            page_category="services",
            status="success",
            word_count=4,
        ),
    ]

    entities = UniversalExtractor().extract(records, "example.com")

    assert [entity.display_name for entity in entities["services"]] == ["Professional Services"]


def test_universal_extractor_skips_non_person_tag_links_in_people_pages():
    record = PageRecord(
        url="https://example.com/thought-leadership/meet-the-expert-amy-scalise",
        normalized_url="https://example.com/thought-leadership/meet-the-expert-amy-scalise",
        domain="example.com",
        path="/thought-leadership/meet-the-expert-amy-scalise",
        title="Meet the Expert: Amy Scalise",
        markdown=(
            "## Meet Amy Scalise, Associate Director\n"
            "[Clinical Research Solutions](https://example.com/thought-leadership/tag/clinical-research-solutions)\n"
            "Why Partner with a CRO that has In-House DCT Capabilities?\n"
        ),
        clean_text="Meet Amy Scalise, Associate Director Clinical Research Solutions",
        page_category="resources",
        status="success",
        word_count=12,
    )

    entities = UniversalExtractor().extract([record], "example.com")

    assert [entity.display_name for entity in entities["people"]] == ["Amy Scalise"]
