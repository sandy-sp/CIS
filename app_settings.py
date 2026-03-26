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
    explicit = os.environ.get("OLLAMA_URL", "").strip()
    if explicit:
        return explicit
    if running_in_container():
        return "http://host.docker.internal:11434"
    return "http://localhost:11434"


def default_qdrant_url() -> str:
    explicit = os.environ.get("QDRANT_URL", "").strip()
    if explicit:
        return explicit
    if running_in_container():
        return "http://host.docker.internal:6333"
    return "http://localhost:6333"


def running_in_container() -> bool:
    override = os.environ.get("CIS_CONTAINERIZED", "").strip()
    if override == "1":
        return True
    if override == "0":
        return False
    return Path("/.dockerenv").exists()


def docker_runtime_mode() -> str:
    if not running_in_container():
        return "host"

    ollama_url = os.environ.get("OLLAMA_URL", "").strip().rstrip("/")
    qdrant_url = os.environ.get("QDRANT_URL", "").strip().rstrip("/")

    if not ollama_url and not qdrant_url:
        return "standalone"
    if ollama_url == "http://ollama:11434" and qdrant_url == "http://qdrant:6333":
        return "full_stack"
    return "custom"


def standalone_container_runtime_hint() -> str:
    if docker_runtime_mode() != "standalone":
        return ""
    return (
        "This CIS container is running by itself. Scrape and Jobs work in this mode, "
        "but Index and Chat require Ollama and Qdrant. Start the full stack with "
        "`docker compose -f docker-compose.dockerhub.yml up -d`, or run the app container "
        "with `OLLAMA_URL` and `QDRANT_URL` pointed at external services."
    )


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
