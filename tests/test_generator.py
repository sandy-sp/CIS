# tests/test_generator.py
import sys
import pytest
from unittest.mock import MagicMock, patch
from chat.generator import Generator


def test_generator_init_ollama():
    g = Generator(backend="ollama")
    assert g.backend == "ollama"
    assert g._model == "llama3.1:8b"


def test_generator_init_openai():
    g = Generator(backend="openai", api_key="sk-test")
    assert g.backend == "openai"
    assert g._model == "gpt-4o-mini"


def test_generator_init_anthropic():
    g = Generator(backend="anthropic", api_key="ant-test")
    assert g.backend == "anthropic"
    assert g._model == "claude-haiku-4-5"


def test_generator_invalid_backend():
    with pytest.raises(ValueError, match="backend must be one of"):
        Generator(backend="gemini")


def test_generator_api_backend_without_key():
    with pytest.raises(ValueError, match="api_key is required"):
        Generator(backend="openai")


def test_build_context_with_chunks():
    g = Generator(backend="ollama")
    chunks = [
        {"url": "https://ex.com/a", "title": "About", "text": "We help businesses grow."},
        {"url": "https://ex.com/b", "title": "Services", "text": "We offer cloud services."},
    ]
    ctx = g._build_context(chunks)
    assert "About" in ctx
    assert "We help businesses grow" in ctx
    assert "https://ex.com/a" in ctx


def test_build_context_empty():
    g = Generator(backend="ollama")
    ctx = g._build_context([])
    assert "No context available" in ctx


def test_build_messages_structure():
    g = Generator(backend="ollama")
    chunks = [{"url": "https://ex.com", "title": "T", "text": "Content."}]
    msgs = g._build_messages("What do you offer?", g._build_context(chunks), [])
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"
    assert "What do you offer?" in msgs[-1]["content"]


def test_build_messages_includes_history():
    g = Generator(backend="ollama")
    history = [
        {"role": "user", "content": "Previous question"},
        {"role": "assistant", "content": "Previous answer"},
    ]
    msgs = g._build_messages("New question", "context", history)
    roles = [m["role"] for m in msgs]
    assert "user" in roles
    assert "assistant" in roles
    # History should be between system and final user message
    assert msgs[1]["content"] == "Previous question"


def test_build_messages_limits_history_to_5():
    g = Generator(backend="ollama")
    history = [{"role": "user", "content": f"q{i}"} for i in range(10)]
    msgs = g._build_messages("new q", "ctx", history)
    # system + last 5 history + 1 current = 7 total
    assert len(msgs) <= 7


def test_generate_ollama_mocked():
    mock_ollama = MagicMock()
    mock_ollama.chat.return_value = {"message": {"content": "Cloud services help businesses."}}

    with patch.dict(sys.modules, {"ollama": mock_ollama}):
        g = Generator(backend="ollama")
        chunks = [{"url": "https://ex.com", "title": "T", "text": "Cloud content."}]
        result = g.generate("What services?", chunks)

    assert result == "Cloud services help businesses."
    mock_ollama.chat.assert_called_once()


def test_generate_openai_mocked():
    mock_openai_module = MagicMock()
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "OpenAI answer about services."
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    mock_openai_module.OpenAI.return_value = mock_client

    with patch.dict(sys.modules, {"openai": mock_openai_module}):
        g = Generator(backend="openai", api_key="sk-test")
        result = g.generate("What services?", [])

    assert result == "OpenAI answer about services."


def test_generate_anthropic_mocked():
    mock_anthropic_module = MagicMock()
    mock_client = MagicMock()
    mock_content = MagicMock()
    mock_content.text = "Anthropic answer."
    mock_client.messages.create.return_value = MagicMock(content=[mock_content])
    mock_anthropic_module.Anthropic.return_value = mock_client

    with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
        g = Generator(backend="anthropic", api_key="ant-test")
        result = g.generate("What services?", [])

    assert result == "Anthropic answer."
