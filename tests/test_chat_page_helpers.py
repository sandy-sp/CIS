from company_intel.models import CrawlSettings, ExtractedEntity
from company_intel.storage import JobStorage
from chat.retriever import RetrievedChunk
from pages.chat_page import (
    _backend_display_label,
    _chunk_log_summary,
    _entity_bucket_order,
    _entity_sources_for_question,
    _is_entity_focused_question,
    _is_generation_error,
    _looks_like_unknown_answer,
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
    assert _backend_display_label("ollama", "qwen3:4b-instruct", "http://ollama:11434") == "Bundled Ollama | qwen3:4b-instruct"
    assert _backend_display_label("openai", "gpt-4o-mini") == "OpenAI API | gpt-4o-mini"
    assert _backend_display_label("local", "BAAI/bge-m3") == "Local model | BAAI/bge-m3"


def test_entity_bucket_order_prioritizes_people_questions():
    buckets = _entity_bucket_order("List the employee names and LinkedIn URLs.")

    assert buckets[0] == "company_profile"
    assert "people" in buckets


def test_is_entity_focused_question_detects_list_queries():
    assert _is_entity_focused_question("List the employee names and LinkedIn URLs.") is True
    assert _is_entity_focused_question("Tell me about the company mission.") is False


def test_looks_like_unknown_answer_detects_variants():
    assert _looks_like_unknown_answer("I don't know based on the scraped content.") is True
    assert _looks_like_unknown_answer("Unfortunately, I have no information to extract.") is True
    assert _looks_like_unknown_answer("Here are the people I found.") is False


def test_entity_sources_for_question_uses_saved_entities(tmp_path, monkeypatch):
    storage = JobStorage(base_dir=tmp_path / "jobs")
    job = storage.create_job(CrawlSettings(start_url="https://example.com"))
    storage.write_entities(
        job.job_id,
        {
            "company_profile": [
                ExtractedEntity(
                    entity_type="company_profile",
                    normalized_key="example",
                    display_name="Example Co",
                    attributes={"summary": "Example summary"},
                    source_urls=["https://example.com/"],
                )
            ],
            "people": [
                ExtractedEntity(
                    entity_type="person",
                    normalized_key="jane-doe",
                    display_name="Jane Doe",
                    attributes={"title": "Director", "linkedin_url": "https://linkedin.com/in/jane-doe"},
                    source_urls=["https://example.com/team"],
                )
            ],
        },
    )

    monkeypatch.setattr("pages.chat_page._STORAGE", storage)

    sources = _entity_sources_for_question(job.job_id, "List employee names and LinkedIn URLs")

    assert len(sources) == 2
    assert sources[0]["title"] == "Company Profile | Example Co"
    assert sources[1]["title"] == "People | Jane Doe"
    assert "Linkedin Url: https://linkedin.com/in/jane-doe" in sources[1]["text"]
