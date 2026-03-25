from __future__ import annotations

from typing import Any

from app_settings import (
    default_ollama_url,
    embedding_model_defaults,
    llm_model_defaults,
)


def _normalize_ollama_url(ollama_url: str) -> str:
    return ollama_url.rstrip("/")


def _ollama_label(ollama_url: str) -> str:
    normalized = _normalize_ollama_url(ollama_url)
    bundled_urls = {
        _normalize_ollama_url(default_ollama_url()),
        "http://localhost:11434",
        "http://ollama:11434",
    }
    return "Bundled Ollama" if normalized in bundled_urls else "Custom Ollama"


def _llm_badge_value(settings: dict[str, Any]) -> str:
    backend = settings.get("llm_backend", "ollama")
    model = settings.get("llm_model", "") or llm_model_defaults()[backend]
    if backend == "ollama":
        ollama_url = settings.get("ollama_url", default_ollama_url())
        return f"{_ollama_label(ollama_url)} | {model}"
    if backend == "openai":
        suffix = "" if settings.get("api_key") else " | missing key"
        return f"OpenAI API | {model}{suffix}"
    if backend == "anthropic":
        suffix = "" if settings.get("api_key") else " | missing key"
        return f"Anthropic API | {model}{suffix}"
    return str(model)


def _embedding_badge_value(settings: dict[str, Any]) -> str:
    backend = settings.get("embedding_backend", "ollama")
    model = settings.get("embedding_model", "") or embedding_model_defaults()[backend]
    if backend == "local":
        return f"Local model | {model}"
    if backend == "ollama":
        ollama_url = settings.get("ollama_url", default_ollama_url())
        return f"{_ollama_label(ollama_url)} | {model}"
    if backend == "openai":
        suffix = "" if settings.get("embedding_api_key") else " | missing key"
        return f"OpenAI API | {model}{suffix}"
    return str(model)


def build_runtime_badges(settings: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"label": "Scrape", "value": "Static + Crawl4AI"},
        {"label": "Index", "value": _embedding_badge_value(settings)},
        {"label": "Chat", "value": _llm_badge_value(settings)},
    ]
