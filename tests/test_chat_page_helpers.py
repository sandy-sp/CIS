from chat.retriever import RetrievedChunk
from pages.chat_page import (
    _chunk_log_summary,
    _is_generation_error,
    _truncate_for_log,
)


def test_truncate_for_log_compacts_whitespace():
    assert _truncate_for_log("hello   world\nfrom\tchat") == "hello world from chat"


def test_truncate_for_log_shortens_long_text():
    result = _truncate_for_log("a" * 20, limit=10)
    assert result == "aaaaaaa..."


def test_chunk_log_summary_uses_titles_for_retrieved_chunks():
    chunks = [
        RetrievedChunk(
            url="https://example.com/about",
            title="About Example Company",
            text="About text",
            section_heading="",
            score=0.9,
        ),
        RetrievedChunk(
            url="https://example.com/services",
            title="Services",
            text="Services text",
            section_heading="",
            score=0.8,
        ),
    ]

    assert _chunk_log_summary(chunks) == "About Example Company, Services"


def test_chunk_log_summary_supports_dict_chunks_and_url_fallback():
    chunks = [
        {"title": "", "url": "https://example.com/a"},
        {"title": "Resource Library", "url": "https://example.com/resources"},
    ]

    assert _chunk_log_summary(chunks) == "https://example.com/a, Resource Library"


def test_is_generation_error_detects_known_backends():
    assert _is_generation_error("[Ollama error: timed out]") is True
    assert _is_generation_error("[OpenAI error: invalid api key]") is True
    assert _is_generation_error("[Anthropic error: unavailable]") is True
    assert _is_generation_error("Normal answer text") is False
