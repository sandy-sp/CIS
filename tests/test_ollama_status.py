import sys
from unittest.mock import MagicMock, patch

from ollama_status import _extract_model_names, get_ollama_status, pull_ollama_models


def test_extract_model_names_supports_dict_and_object_shapes():
    response = {
        "models": [
            {"model": "qwen3:4b-instruct"},
            {"name": "nomic-embed-text"},
            {"model": "qwen3:4b-instruct"},
        ]
    }

    names = _extract_model_names(response)

    assert names == ["nomic-embed-text", "qwen3:4b-instruct"]


def test_get_ollama_status_reports_reachable_and_installed_models():
    mock_ollama = MagicMock()
    mock_client = MagicMock()
    mock_client.list.return_value = {
        "models": [
            {"model": "qwen3:4b-instruct"},
            {"model": "nomic-embed-text"},
        ]
    }
    mock_ollama.Client.return_value = mock_client

    with patch.dict(sys.modules, {"ollama": mock_ollama}):
        status = get_ollama_status(
            ollama_url="http://ollama:11434",
            chat_model="qwen3:4b-instruct",
            embedding_model="nomic-embed-text",
        )

    assert status["reachable"] is True
    assert status["ready_for_chat"] is True
    assert status["ready_for_indexing"] is True
    assert status["installed_count"] == 2
    assert status["installed_models"] == ["nomic-embed-text", "qwen3:4b-instruct"]


def test_get_ollama_status_falls_back_to_show_when_model_list_is_empty():
    mock_ollama = MagicMock()
    mock_client = MagicMock()
    mock_client.list.return_value = {"models": []}
    mock_ollama.Client.return_value = mock_client

    with patch.dict(sys.modules, {"ollama": mock_ollama}):
        status = get_ollama_status(
            ollama_url="http://ollama:11434",
            chat_model="qwen3:4b-instruct",
            embedding_model="nomic-embed-text",
        )

    assert status["reachable"] is True
    assert status["chat_model_available"] is True
    assert status["embedding_model_available"] is True
    assert status["installed_models"] == ["nomic-embed-text", "qwen3:4b-instruct"]
    assert mock_client.show.call_count == 2


def test_get_ollama_status_reports_connection_error():
    mock_ollama = MagicMock()
    mock_ollama.Client.side_effect = RuntimeError("connection refused")

    with patch.dict(sys.modules, {"ollama": mock_ollama}):
        status = get_ollama_status(
            ollama_url="http://ollama:11434",
            chat_model="qwen3:4b-instruct",
            embedding_model="nomic-embed-text",
        )

    assert status["reachable"] is False
    assert status["ready_for_chat"] is False
    assert "connection refused" in status["error"]


def test_pull_ollama_models_pulls_each_missing_model_once():
    mock_ollama = MagicMock()
    mock_client = MagicMock()
    mock_client.pull.return_value = {"status": "success"}
    mock_ollama.Client.return_value = mock_client

    with patch.dict(sys.modules, {"ollama": mock_ollama}):
        result = pull_ollama_models(
            ollama_url="http://ollama:11434",
            models=["qwen3:4b-instruct", "nomic-embed-text", "qwen3:4b-instruct"],
        )

    assert result["pulled_models"] == ["nomic-embed-text", "qwen3:4b-instruct"]
    assert result["failed_models"] == {}
    assert mock_client.pull.call_count == 2


def test_pull_ollama_models_collects_partial_failures():
    mock_ollama = MagicMock()
    mock_client = MagicMock()

    def pull_side_effect(*, model, stream=False):
        if model == "qwen3:4b-instruct":
            return {"status": "success"}
        raise RuntimeError("disk full")

    mock_client.pull.side_effect = pull_side_effect
    mock_ollama.Client.return_value = mock_client

    with patch.dict(sys.modules, {"ollama": mock_ollama}):
        result = pull_ollama_models(
            ollama_url="http://ollama:11434",
            models=["qwen3:4b-instruct", "nomic-embed-text"],
        )

    assert result["pulled_models"] == ["qwen3:4b-instruct"]
    assert result["failed_models"] == {"nomic-embed-text": "disk full"}
