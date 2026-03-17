# tests/test_page_processor.py
import pytest
from scraper.page_processor import PageProcessor
from models import PageResult


@pytest.fixture
def processor():
    return PageProcessor()


# --- page_type detection ---

def test_page_type_homepage(processor):
    assert processor.detect_page_type("https://example.com/") == "homepage"


def test_page_type_about(processor):
    assert processor.detect_page_type("https://example.com/about-us") == "about"
    assert processor.detect_page_type("https://example.com/our-team") == "about"
    assert processor.detect_page_type("https://example.com/company/who-we-are") == "about"


def test_page_type_services(processor):
    assert processor.detect_page_type("https://example.com/services/consulting") == "services"
    assert processor.detect_page_type("https://example.com/our-solutions") == "services"


def test_page_type_blog(processor):
    assert processor.detect_page_type("https://example.com/blog/my-post") == "blog"
    assert processor.detect_page_type("https://example.com/news/update") == "blog"
    assert processor.detect_page_type("https://example.com/insights/2026") == "blog"


def test_page_type_case_study(processor):
    assert processor.detect_page_type("https://example.com/case-studies/acme") == "case-study"
    assert processor.detect_page_type("https://example.com/work/project-x") == "case-study"


def test_page_type_contact(processor):
    assert processor.detect_page_type("https://example.com/contact") == "contact"
    assert processor.detect_page_type("https://example.com/get-in-touch") == "contact"


def test_page_type_other(processor):
    assert processor.detect_page_type("https://example.com/legal/privacy") == "other"


def test_page_type_priority_homepage_over_contact(processor):
    assert processor.detect_page_type("https://example.com/") == "homepage"


# --- heading extraction ---

def test_extract_headings_h1_and_h2(processor):
    html = "<h1>Main Title</h1><h2>Section A</h2><h2>Section B</h2>"
    result = processor.extract_headings(html)
    assert result == [{"h1": "Main Title"}, {"h2": "Section A"}, {"h2": "Section B"}]


def test_extract_headings_empty_when_none(processor):
    assert processor.extract_headings("<p>No headings</p>") == []


def test_extract_headings_preserves_order(processor):
    html = "<h2>First</h2><h1>Second</h1><h2>Third</h2>"
    result = processor.extract_headings(html)
    assert result == [{"h2": "First"}, {"h1": "Second"}, {"h2": "Third"}]


# --- word count ---

def test_word_count(processor):
    assert processor.count_words("one two three") == 3
    assert processor.count_words("  hello   world  ") == 2
    assert processor.count_words("") == 0


# --- full process() ---

def test_process_injects_frontmatter(processor, sample_page_result):
    result = processor.process(sample_page_result)
    assert result.markdown.startswith("---\n")
    assert "url: https://example.com/services\n" in result.markdown
    assert "page_type: services\n" in result.markdown
    assert "engine_used: crawl4ai\n" in result.markdown


def test_process_frontmatter_ends_with_separator(processor, sample_page_result):
    result = processor.process(sample_page_result)
    parts = result.markdown.split("---\n", 2)
    assert len(parts) == 3  # opening ---, frontmatter, closing ---


def test_process_sets_word_count(processor):
    result = PageResult(
        url="https://example.com",
        markdown="one two three four five",
    )
    processed = processor.process(result)
    assert processed.word_count == 5


def test_process_detects_page_type(processor):
    result = PageResult(url="https://example.com/services/consulting", markdown="content")
    processed = processor.process(result)
    assert processed.page_type == "services"


def test_process_extracts_headings(processor):
    result = PageResult(
        url="https://example.com/about",
        raw_html="<h1>About Us</h1><h2>Our Story</h2>",
        markdown="# About Us\n\n## Our Story",
    )
    processed = processor.process(result)
    assert {"h1": "About Us"} in processed.headings
    assert {"h2": "Our Story"} in processed.headings
