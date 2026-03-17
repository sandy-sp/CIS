# tests/test_chunker.py
import pytest
from processor.chunker import Chunker, Chunk, _CHUNK_SIZE


@pytest.fixture
def chunker():
    return Chunker()


SHORT_TEXT = "This is a short text with fewer than fifty words total."

LONG_TEXT = """
# Introduction

This section introduces the company and its core mission. We are dedicated to providing
excellent services to our clients across multiple industries. Our team consists of highly
skilled professionals with decades of combined experience in technology and consulting.

## Our Services

We offer a wide range of services including cloud migration, digital transformation,
strategic consulting, and custom software development. Each engagement is tailored to
the specific needs of our clients.

We work with businesses of all sizes, from startups to Fortune 500 companies. Our
methodology is proven and our results speak for themselves with a 95% client retention rate.

## Our Team

Our team is our greatest asset. We bring together experts from diverse backgrounds
including engineering, business strategy, design, and operations. This diversity allows
us to approach problems from multiple angles and deliver comprehensive solutions.
"""


def test_chunk_returns_list_of_chunks(chunker):
    result = chunker.chunk(LONG_TEXT, url="https://example.com/about", title="About")
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(c, Chunk) for c in result)


def test_chunk_preserves_metadata(chunker):
    result = chunker.chunk(LONG_TEXT, url="https://example.com/about",
                           title="About", page_type="about")
    assert all(c.url == "https://example.com/about" for c in result)
    assert all(c.title == "About" for c in result)
    assert all(c.page_type == "about" for c in result)


def test_chunk_indices_are_sequential(chunker):
    result = chunker.chunk(LONG_TEXT)
    for i, chunk in enumerate(result):
        assert chunk.chunk_index == i
    assert result[-1].chunk_total == len(result)


def test_chunk_section_headings_extracted(chunker):
    result = chunker.chunk(LONG_TEXT)
    headings = {c.section_heading for c in result if c.section_heading}
    # Should have at least one heading extracted
    assert len(headings) > 0


def test_chunk_empty_text_returns_empty(chunker):
    assert chunker.chunk("") == []
    assert chunker.chunk("   ") == []


def test_chunk_long_text_splits(chunker):
    # A text longer than CHUNK_SIZE should produce multiple chunks
    long = "word " * 400  # ~2000 chars
    result = chunker.chunk(long)
    assert len(result) > 1


def test_chunk_each_chunk_within_size_limit(chunker):
    long = "word " * 400
    result = chunker.chunk(long)
    # Allow some tolerance for overlap and boundary adjustments
    for c in result:
        assert len(c.text) <= _CHUNK_SIZE * 1.5
