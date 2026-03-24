from runtime_badges import build_runtime_badges


def test_build_runtime_badges_for_bundled_ollama():
    settings = {
        "llm_backend": "ollama",
        "llm_model": "llama3.2:3b",
        "ollama_url": "http://ollama:11434",
        "embedding_backend": "ollama",
        "embedding_model": "nomic-embed-text",
    }

    badges = build_runtime_badges(settings)

    assert badges[0]["value"] == "Hybrid crawler"
    assert badges[1]["value"] == "Bundled Ollama | nomic-embed-text"
    assert badges[2]["value"] == "Bundled Ollama | llama3.2:3b"


def test_build_runtime_badges_for_external_apis_with_missing_keys():
    settings = {
        "llm_backend": "openai",
        "llm_model": "gpt-4o-mini",
        "embedding_backend": "openai",
        "embedding_model": "text-embedding-3-small",
        "api_key": "",
        "embedding_api_key": "",
    }

    badges = build_runtime_badges(settings)

    assert badges[1]["value"] == "OpenAI API | text-embedding-3-small | missing key"
    assert badges[2]["value"] == "OpenAI API | gpt-4o-mini | missing key"


def test_build_runtime_badges_for_custom_ollama_endpoint():
    settings = {
        "llm_backend": "anthropic",
        "llm_model": "claude-haiku-4-5",
        "api_key": "ant-test",
        "embedding_backend": "ollama",
        "embedding_model": "nomic-embed-text",
        "ollama_url": "http://remote-ollama:11434",
    }

    badges = build_runtime_badges(settings)

    assert badges[1]["value"] == "Custom Ollama | nomic-embed-text"
    assert badges[2]["value"] == "Anthropic API | claude-haiku-4-5"
