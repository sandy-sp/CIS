from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, MutableMapping


_DEFAULT_PATH = Path("data/app_settings.json")
_LLM_BACKENDS = {"ollama", "openai", "anthropic"}
_EMBEDDING_BACKENDS = {"local", "ollama", "openai"}
_ALLOWED_KEYS = {
    "llm_backend",
    "api_key",
    "llm_model",
    "ollama_url",
    "embedding_backend",
    "embedding_api_key",
    "embedding_model",
}


def default_ollama_url() -> str:
    return os.environ.get("OLLAMA_URL", "http://localhost:11434")


def llm_model_defaults() -> dict[str, str]:
    return {
        "ollama": os.environ.get("APP_DEFAULT_OLLAMA_LLM_MODEL", "qwen3:4b-instruct"),
        "openai": os.environ.get("APP_DEFAULT_OPENAI_LLM_MODEL", "gpt-4o-mini"),
        "anthropic": os.environ.get("APP_DEFAULT_ANTHROPIC_LLM_MODEL", "claude-haiku-4-5"),
    }


def embedding_model_defaults() -> dict[str, str]:
    return {
        "local": os.environ.get("APP_DEFAULT_LOCAL_EMBEDDING_MODEL", "BAAI/bge-m3"),
        "ollama": os.environ.get("APP_DEFAULT_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
        "openai": os.environ.get("APP_DEFAULT_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    }


def default_settings() -> dict[str, str]:
    llm_backend = os.environ.get("APP_DEFAULT_LLM_BACKEND", "ollama")
    if llm_backend not in _LLM_BACKENDS:
        llm_backend = "ollama"

    embedding_backend = os.environ.get("APP_DEFAULT_EMBEDDING_BACKEND", "ollama")
    if embedding_backend not in _EMBEDDING_BACKENDS:
        embedding_backend = "ollama"

    llm_defaults = llm_model_defaults()
    embedding_defaults = embedding_model_defaults()
    return {
        "llm_backend": llm_backend,
        "api_key": "",
        "llm_model": llm_defaults[llm_backend],
        "ollama_url": default_ollama_url(),
        "embedding_backend": embedding_backend,
        "embedding_api_key": "",
        "embedding_model": embedding_defaults[embedding_backend],
    }


class SettingsStore:
    def __init__(self, path: Path = _DEFAULT_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, str]:
        defaults = default_settings()
        if not self.path.exists():
            return defaults
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return defaults
        if not isinstance(data, dict):
            return defaults
        cleaned = dict(defaults)
        for key, value in data.items():
            if key in _ALLOWED_KEYS and isinstance(value, str):
                cleaned[key] = value
        return cleaned

    def save(self, settings: dict[str, Any]) -> dict[str, str]:
        cleaned = {
            key: str(settings.get(key, "") or "")
            for key in _ALLOWED_KEYS
        }
        self.path.write_text(
            json.dumps(cleaned, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return cleaned

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def ensure_session_settings(
    session_state: MutableMapping[str, Any],
    store: SettingsStore | None = None,
) -> dict[str, str]:
    settings_store = store or SettingsStore()
    current = session_state.get("settings")
    if not isinstance(current, dict):
        current = settings_store.load()
    else:
        merged = settings_store.load()
        for key, value in current.items():
            if key in _ALLOWED_KEYS and isinstance(value, str):
                merged[key] = value
        current = merged
    session_state["settings"] = current
    return current
