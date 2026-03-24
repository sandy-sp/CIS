import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ollama_status import pull_ollama_models


def _wait_for_ollama(ollama_url: str, timeout_seconds: int = 180) -> None:
    deadline = time.time() + timeout_seconds
    endpoint = f"{ollama_url.rstrip('/')}/api/tags"
    last_error = ""
    while time.time() < deadline:
        try:
            response = requests.get(endpoint, timeout=5)
            response.raise_for_status()
            return
        except Exception as exc:  # pragma: no cover - exercised in container startup
            last_error = str(exc)
            time.sleep(2)
    raise RuntimeError(f"Ollama did not become ready at {ollama_url}: {last_error}")


def main() -> int:
    ollama_url = os.environ.get("OLLAMA_URL", "http://ollama:11434")
    models = [
        model.strip()
        for model in os.environ.get("OLLAMA_BOOTSTRAP_MODELS", "").split(",")
        if model.strip()
    ]

    if not models:
        print("No Ollama bootstrap models configured; skipping.")
        return 0

    print(f"Waiting for Ollama at {ollama_url}...")
    _wait_for_ollama(ollama_url)
    print(f"Pulling Ollama models: {', '.join(models)}")
    result = pull_ollama_models(ollama_url=ollama_url, models=models)

    if result.get("pulled_models"):
        print(f"Pulled models: {', '.join(result['pulled_models'])}")
    if result.get("failed_models"):
        for model, error in result["failed_models"].items():
            print(f"Failed to pull {model}: {error}", file=sys.stderr)
        return 1

    print("Ollama bootstrap complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
