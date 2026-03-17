# tests/test_embedder.py
import sys
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from indexer.embedder import Embedder


def test_embedder_init_local_backend():
    embedder = Embedder(backend="local")
    assert embedder.backend == "local"
    assert embedder._model_name == "BAAI/bge-m3"
    assert embedder.dimensions == 1024


def test_embedder_init_openai_backend():
    embedder = Embedder(backend="openai", api_key="sk-test")
    assert embedder.backend == "openai"
    assert embedder._model_name == "text-embedding-3-small"
    assert embedder.dimensions == 1536


def test_embedder_invalid_backend_raises():
    with pytest.raises(ValueError, match="backend must be one of"):
        Embedder(backend="anthropic")


def test_embedder_openai_without_api_key_raises():
    with pytest.raises(ValueError, match="api_key is required"):
        Embedder(backend="openai")


def test_embedder_custom_model():
    embedder = Embedder(backend="openai", api_key="sk-test",
                        model="text-embedding-3-large")
    assert embedder._model_name == "text-embedding-3-large"
    assert embedder.dimensions == 3072


def test_embed_empty_list_returns_empty():
    embedder = Embedder(backend="local")
    result = embedder.embed([])
    assert result == []


def test_embed_local_calls_sentence_transformers():
    """Verify local embed calls SentenceTransformer.encode with correct args."""
    embedder = Embedder(backend="local")

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    embedder._model = mock_model  # inject mock directly

    result = embedder.embed(["text 1", "text 2"])

    mock_model.encode.assert_called_once_with(
        ["text 1", "text 2"],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    assert len(result) == 2
    assert result[0] == pytest.approx([0.1, 0.2, 0.3])


def test_embed_openai_calls_api():
    """Verify OpenAI embed calls the embeddings endpoint via sys.modules patch."""
    mock_openai = MagicMock()
    mock_client_instance = MagicMock()
    mock_response = MagicMock()
    mock_item_1 = MagicMock()
    mock_item_1.embedding = [0.1, 0.2, 0.3]
    mock_item_2 = MagicMock()
    mock_item_2.embedding = [0.4, 0.5, 0.6]
    mock_response.data = [mock_item_1, mock_item_2]
    mock_client_instance.embeddings.create.return_value = mock_response
    mock_openai.OpenAI.return_value = mock_client_instance

    with patch.dict(sys.modules, {"openai": mock_openai}):
        embedder = Embedder(backend="openai", api_key="sk-test")
        result = embedder.embed(["text 1", "text 2"])

    mock_client_instance.embeddings.create.assert_called_once_with(
        input=["text 1", "text 2"],
        model="text-embedding-3-small",
    )
    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_model_lazy_loads_on_first_embed():
    """Model should be None before first embed call."""
    embedder = Embedder(backend="local")
    assert embedder._model is None
    # After injecting a mock model, embed should work
    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([[0.1, 0.2]])
    embedder._model = mock_model
    embedder.embed(["test"])
    mock_model.encode.assert_called_once()


def test_embed_local_missing_sentence_transformers_raises():
    """ImportError is raised with helpful message if sentence-transformers absent."""
    embedder = Embedder(backend="local")
    # _model is None so _load_local_model will be called
    mock_st = MagicMock()
    mock_st.side_effect = ImportError("No module named 'sentence_transformers'")

    with patch.dict(sys.modules, {"sentence_transformers": None}):
        with pytest.raises(ImportError, match="sentence-transformers is required"):
            embedder.embed(["hello"])


def test_embed_openai_missing_openai_package_raises():
    """ImportError is raised with helpful message if openai package absent."""
    embedder = Embedder(backend="openai", api_key="sk-test")
    with patch.dict(sys.modules, {"openai": None}):
        with pytest.raises(ImportError, match="openai package is required"):
            embedder.embed(["hello"])


def test_default_model_local():
    embedder = Embedder(backend="local")
    assert embedder._default_model("local") == "BAAI/bge-m3"


def test_default_model_openai():
    embedder = Embedder(backend="openai", api_key="sk-test")
    assert embedder._default_model("openai") == "text-embedding-3-small"


def test_dimensions_unknown_model_defaults_to_1024():
    embedder = Embedder(backend="local", model="some-unknown-model")
    assert embedder.dimensions == 1024
