import io
import zipfile
from datetime import datetime, timezone
import pytest
from models import PageResult
from scraper.exporter import Exporter


@pytest.fixture
def pages():
    return [
        PageResult(
            url="https://example.com/",
            title="Home",
            markdown="---\npage_type: homepage\n---\n\n# Welcome",
            page_type="homepage",
            word_count=10,
            engine_used="crawl4ai",
            status="success",
            scraped_at=datetime(2026, 3, 17, tzinfo=timezone.utc),
        ),
        PageResult(
            url="https://example.com/services/consulting",
            title="Consulting",
            markdown="---\npage_type: services\n---\n\n# Consulting",
            page_type="services",
            word_count=50,
            engine_used="crawl4ai",
            status="success",
            scraped_at=datetime(2026, 3, 17, tzinfo=timezone.utc),
        ),
        PageResult(
            url="https://example.com/broken",
            status="failed",
            skip_reason="both engines failed",
        ),
    ]


@pytest.fixture
def external_links():
    return {
        "linkedin.com": ["https://linkedin.com/company/example"],
        "twitter.com": ["https://twitter.com/example"],
    }


def test_zip_contains_master_site_md(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    assert any("master_site.md" in n for n in names)


def test_zip_contains_individual_pages(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    assert any("individual_pages/" in n for n in names)
    assert any("homepage.md" in n for n in names)


def test_zip_contains_external_links(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        content = zf.read([n for n in zf.namelist() if "external_links" in n][0]).decode()
    assert "linkedin.com" in content
    assert "https://linkedin.com/company/example" in content


def test_zip_contains_crawl_report(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        content = zf.read([n for n in zf.namelist() if "crawl_report" in n][0]).decode()
    assert "| Pages scraped | 2 |" in content
    assert "| Pages failed | 1 |" in content


def test_slugify_url(pages, external_links):
    exporter = Exporter("example.com")
    assert exporter.slugify("https://example.com/services/consulting") == "services-consulting"
    assert exporter.slugify("https://example.com/") == "homepage"
    assert exporter.slugify("https://example.com/about-us/team") == "about-us-team"


def test_master_site_ordered_by_page_type(pages, external_links):
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages, external_links)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        content = zf.read([n for n in zf.namelist() if "master_site" in n][0]).decode()
    # homepage should appear before services in master_site.md
    assert content.index("homepage") < content.index("services")


def test_crawl_report_includes_skip_reasons():
    pages_with_skipped = [
        PageResult(url="https://example.com/a", status="success", markdown="x",
                   page_type="other", engine_used="crawl4ai"),
        PageResult(url="https://example.com/b", status="skipped", skip_reason="robots disallowed"),
        PageResult(url="https://example.com/c", status="skipped", skip_reason="robots disallowed"),
        PageResult(url="https://example.com/d", status="skipped", skip_reason="noindex"),
    ]
    exporter = Exporter("example.com")
    zip_bytes = exporter.build_zip(pages_with_skipped, {})
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        content = zf.read([n for n in zf.namelist() if "crawl_report" in n][0]).decode()
    assert "| Pages skipped | 3 |" in content
    assert "robots disallowed: 2" in content
    assert "noindex: 1" in content
