import json

from app_settings import SettingsStore, default_settings, ensure_session_settings


def test_settings_store_save_and_load(tmp_path):
    store = SettingsStore(path=tmp_path / "app_settings.json")

    saved = store.save({
        "llm_backend": "openai",
        "api_key": "sk-test",
        "llm_model": "gpt-4o-mini",
        "ollama_url": "http://localhost:11434",
        "embedding_backend": "openai",
        "embedding_api_key": "sk-embed",
        "embedding_model": "text-embedding-3-small",
        "ignored_key": "ignored",
    })

    loaded = store.load()

    assert saved == loaded
    assert "ignored_key" not in loaded
    assert loaded["api_key"] == "sk-test"


def test_settings_store_load_invalid_payload_returns_empty(tmp_path):
    path = tmp_path / "app_settings.json"
    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    store = SettingsStore(path=path)

    loaded = store.load()
    assert loaded["llm_backend"] == "ollama"
    assert loaded["embedding_backend"] == "local"


def test_ensure_session_settings_loads_from_store(tmp_path):
    store = SettingsStore(path=tmp_path / "app_settings.json")
    store.save({
        "llm_backend": "ollama",
        "ollama_url": "http://localhost:11434",
    })

    session_state = {}
    settings = ensure_session_settings(session_state, store=store)

    assert settings["llm_backend"] == "ollama"
    assert session_state["settings"]["ollama_url"] == "http://localhost:11434"


def test_ensure_session_settings_preserves_existing_session_values(tmp_path):
    store = SettingsStore(path=tmp_path / "app_settings.json")
    store.save({
        "llm_backend": "openai",
        "api_key": "sk-test",
    })

    session_state = {"settings": {"llm_backend": "anthropic", "api_key": "ant-test"}}
    settings = ensure_session_settings(session_state, store=store)

    assert settings["llm_backend"] == "anthropic"
    assert settings["api_key"] == "ant-test"


def test_default_settings_respects_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434")
    monkeypatch.setenv("APP_DEFAULT_LLM_BACKEND", "ollama")
    monkeypatch.setenv("APP_DEFAULT_EMBEDDING_BACKEND", "ollama")
    monkeypatch.setenv("APP_DEFAULT_OLLAMA_LLM_MODEL", "llama3.2:3b")
    monkeypatch.setenv("APP_DEFAULT_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

    settings = default_settings()

    assert settings["ollama_url"] == "http://ollama:11434"
    assert settings["llm_model"] == "llama3.2:3b"
    assert settings["embedding_model"] == "nomic-embed-text"
    assert settings["embedding_backend"] == "ollama"
