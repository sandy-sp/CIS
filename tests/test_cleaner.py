# tests/test_cleaner.py
import pytest
from processor.cleaner import Cleaner, CleanResult


@pytest.fixture
def cleaner():
    return Cleaner()


SAMPLE_HTML = """
<html>
<head><title>Our Services</title></head>
<body>
  <nav><a href="/">Home</a> <a href="/about">About</a></nav>
  <main>
    <h1>Our Services</h1>
    <p>We provide comprehensive business consulting services to help companies grow.</p>
    <p>Our team of experts has over 20 years of experience in digital transformation,
    strategic planning, and operational efficiency. We work with businesses of all sizes
    to identify opportunities and implement solutions that drive real results.</p>
    <h2>Cloud Solutions</h2>
    <p>Migrate your infrastructure to the cloud with our proven methodology. We handle
    everything from initial assessment to full deployment and ongoing support.</p>
    <h2>Digital Strategy</h2>
    <p>Develop a comprehensive digital strategy that aligns with your business objectives.
    Our consultants work closely with your leadership team to define roadmaps and priorities.</p>
  </main>
  <footer><p>Privacy Policy | Terms of Service | © 2026</p></footer>
</body>
</html>
"""

SAMPLE_FRONTMATTER_MD = """---
url: https://example.com/services
title: Our Services
page_type: services
word_count: 150
scraped_at: 2026-03-17T10:00:00Z
engine_used: crawl4ai
---

# Our Services

We provide comprehensive business consulting services to help companies grow.

Our team of experts has over 20 years of experience in digital transformation,
strategic planning, and operational efficiency.

## Cloud Solutions

Migrate your infrastructure to the cloud with our proven methodology.

## Digital Strategy

Develop a comprehensive digital strategy that aligns with your business objectives.
"""


def test_clean_html_returns_clean_text(cleaner):
    result = cleaner.clean_html(SAMPLE_HTML, url="https://example.com/services")
    assert isinstance(result, CleanResult)
    assert result.clean_text  # should have content
    assert result.word_count > 20
    assert result.skip_reason == ""


def test_clean_html_strips_nav_and_footer(cleaner):
    result = cleaner.clean_html(SAMPLE_HTML, url="https://example.com/services")
    # Navigation and footer text should be stripped
    assert "Privacy Policy" not in result.clean_text
    assert "Terms of Service" not in result.clean_text


def test_clean_html_noise_url_returns_skip(cleaner):
    result = cleaner.clean_html(SAMPLE_HTML, url="https://example.com/privacy-policy")
    assert result.skip_reason == "noise-url"
    assert result.is_high_noise


def test_clean_html_too_short_returns_skip(cleaner):
    short_html = "<html><body><p>Hi</p></body></html>"
    result = cleaner.clean_html(short_html, url="https://example.com/page")
    assert result.skip_reason == "too-short"
    assert result.is_high_noise


def test_clean_markdown_file_extracts_metadata(cleaner):
    result = cleaner.clean_markdown_file(SAMPLE_FRONTMATTER_MD)
    assert result.url == "https://example.com/services"
    assert result.title == "Our Services"
    assert result.page_type == "services"


def test_clean_markdown_file_returns_clean_text(cleaner):
    result = cleaner.clean_markdown_file(SAMPLE_FRONTMATTER_MD)
    assert result.clean_text
    assert result.word_count > 20
    assert result.skip_reason == ""


def test_clean_markdown_noise_url_skipped(cleaner):
    md = SAMPLE_FRONTMATTER_MD.replace(
        "url: https://example.com/services",
        "url: https://example.com/privacy"
    )
    result = cleaner.clean_markdown_file(md)
    assert result.skip_reason == "noise-url"


def test_parse_frontmatter_no_yaml(cleaner):
    result = cleaner.clean_markdown_file("# Just markdown\n\nSome content here.")
    assert result.url == ""
    assert result.clean_text  # content extracted even without frontmatter
