from chat.retriever import RetrievedChunk
from pages.chat_page import (
    _backend_display_label,
    _chunk_log_summary,
    _is_generation_error,
    _retrieval_settings,
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


def test_retrieval_settings_prefers_index_metadata():
    target = {
        "embedding_backend": "ollama",
        "embedding_model": "nomic-embed-text",
        "embedding_ollama_url": "http://ollama:11434",
    }
    settings = {
        "embedding_backend": "openai",
        "embedding_model": "text-embedding-3-small",
        "embedding_api_key": "sk-embed",
        "ollama_url": "http://remote-ollama:11434",
    }

    retrieval = _retrieval_settings(target, settings)

    assert retrieval["backend"] == "ollama"
    assert retrieval["model"] == "nomic-embed-text"
    assert retrieval["api_key"] == ""
    assert retrieval["ollama_url"] == "http://ollama:11434"


def test_backend_display_label_formats_supported_backends():
    assert _backend_display_label("ollama", "llama3.2:3b", "http://ollama:11434") == "Bundled Ollama | llama3.2:3b"
    assert _backend_display_label("openai", "gpt-4o-mini") == "OpenAI API | gpt-4o-mini"
    assert _backend_display_label("local", "BAAI/bge-m3") == "Local model | BAAI/bge-m3"
