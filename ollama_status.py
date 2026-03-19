from __future__ import annotations

from typing import Any


def _get_ollama_client(ollama_url: str):
    import ollama
    return ollama.Client(host=ollama_url) if hasattr(ollama, "Client") else ollama


def _extract_model_names(response: Any) -> list[str]:
    if isinstance(response, dict):
        models = response.get("models", [])
    else:
        models = getattr(response, "models", response)

    names: list[str] = []
    for item in models or []:
        if isinstance(item, dict):
            name = item.get("model") or item.get("name")
        else:
            name = getattr(item, "model", None) or getattr(item, "name", None)
        if isinstance(name, str) and name:
            names.append(name)
    return sorted(set(names))


def _model_available(client: Any, model: str, installed_models: list[str]) -> bool:
    if not model:
        return False
    if installed_models:
        return model in installed_models
    if hasattr(client, "show"):
        try:
            client.show(model=model)
            return True
        except Exception:
            return False
    return False


def _consume_pull_response(response: Any) -> None:
    if response is None or isinstance(response, (dict, str, bytes)):
        return
    if hasattr(response, "__iter__"):
        for _ in response:
            pass


def get_ollama_status(ollama_url: str, chat_model: str, embedding_model: str) -> dict[str, Any]:
    try:
        import ollama
    except ImportError:
        return {
            "reachable": False,
            "ollama_url": ollama_url,
            "installed_models": [],
            "installed_count": 0,
            "chat_model": chat_model,
            "chat_model_available": False,
            "embedding_model": embedding_model,
            "embedding_model_available": False,
            "ready_for_chat": False,
            "ready_for_indexing": False,
            "error": "ollama package is required. Install with: pip install ollama>=0.2.0",
        }

    try:
        client = _get_ollama_client(ollama_url)
        installed_models = _extract_model_names(client.list()) if hasattr(client, "list") else []
        chat_available = _model_available(client, chat_model, installed_models)
        embedding_available = _model_available(client, embedding_model, installed_models)
        if not installed_models:
            inferred_models = [model for model, available in [
                (chat_model, chat_available),
                (embedding_model, embedding_available),
            ] if available]
            installed_models = sorted(set(inferred_models))
        return {
            "reachable": True,
            "ollama_url": ollama_url,
            "installed_models": installed_models,
            "installed_count": len(installed_models),
            "chat_model": chat_model,
            "chat_model_available": chat_available,
            "embedding_model": embedding_model,
            "embedding_model_available": embedding_available,
            "ready_for_chat": chat_available,
            "ready_for_indexing": embedding_available,
            "error": "",
        }
    except Exception as exc:
        return {
            "reachable": False,
            "ollama_url": ollama_url,
            "installed_models": [],
            "installed_count": 0,
            "chat_model": chat_model,
            "chat_model_available": False,
            "embedding_model": embedding_model,
            "embedding_model_available": False,
            "ready_for_chat": False,
            "ready_for_indexing": False,
            "error": str(exc),
        }


def pull_ollama_models(ollama_url: str, models: list[str]) -> dict[str, Any]:
    try:
        import ollama  # noqa: F401
    except ImportError:
        return {
            "requested_models": [],
            "pulled_models": [],
            "failed_models": {},
            "error": "ollama package is required. Install with: pip install ollama>=0.2.0",
        }

    requested_models = sorted({model for model in models if model})
    if not requested_models:
        return {
            "requested_models": [],
            "pulled_models": [],
            "failed_models": {},
            "error": "",
        }

    try:
        client = _get_ollama_client(ollama_url)
    except Exception as exc:
        return {
            "requested_models": requested_models,
            "pulled_models": [],
            "failed_models": {model: str(exc) for model in requested_models},
            "error": str(exc),
        }

    pulled_models: list[str] = []
    failed_models: dict[str, str] = {}
    for model in requested_models:
        try:
            try:
                response = client.pull(model=model, stream=False)
            except TypeError:
                response = client.pull(model=model)
            _consume_pull_response(response)
            pulled_models.append(model)
        except Exception as exc:
            failed_models[model] = str(exc)

    error = ""
    if failed_models and not pulled_models:
        error = "; ".join(f"{model}: {message}" for model, message in failed_models.items())

    return {
        "requested_models": requested_models,
        "pulled_models": pulled_models,
        "failed_models": failed_models,
        "error": error,
    }
