# chat/generator.py
"""
LLM generator for company-intelligence chat. Supports three backends:
  - "ollama":    Local Ollama (default model: qwen3:4b-instruct)
  - "openai":    OpenAI API (default model: gpt-4o-mini)
  - "anthropic": Anthropic API (default model: claude-haiku-4-5)

Grounded prompt: answer ONLY from provided context and tool results. Cite sources. Say "I don't know" if not in context.
Multi-turn: accepts last 5 conversation turns as history.
"""
import os
from collections.abc import Callable
from typing import Optional


_RAG_SYSTEM_PROMPT = """You are a company intelligence assistant.

You answer questions using ONLY the scraped company corpus, structured extracted entities, and any tool results returned from the local vector database.

Rules:
- Use the provided context first.
- You may call tools to search the vector database or inspect structured extracted entities when the current context is incomplete.
- If only part of the answer is available, answer that part and clearly say which details were not found.
- Never claim that there is no scraped content unless the search tool and entity lookup both return nothing relevant.
- Cite factual claims with sources in markdown form like [Page Title](URL).
- If the answer truly is not supported by the scraped content, say: "I don't know based on the scraped content."
"""

_MAX_HISTORY_TURNS = 5
_MAX_TOOL_ROUNDS = 3


class Generator:
    SUPPORTED_BACKENDS = ("ollama", "openai", "anthropic")

    def __init__(self, backend: str = "ollama",
                 api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 ollama_url: Optional[str] = None):
        if backend not in self.SUPPORTED_BACKENDS:
            raise ValueError(f"backend must be one of {self.SUPPORTED_BACKENDS}, got {backend!r}")
        if backend in ("openai", "anthropic") and not api_key:
            raise ValueError(f"api_key is required for {backend} backend")

        self.backend = backend
        self.api_key = api_key
        self.ollama_url = ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        self._model = model or self._default_model(backend)
        self._ollama_client = None

    def _ollama_chat_options(self) -> dict:
        num_ctx_raw = os.environ.get("APP_OLLAMA_NUM_CTX", "2048")
        try:
            num_ctx = max(512, int(num_ctx_raw))
        except ValueError:
            num_ctx = 2048
        return {"num_ctx": num_ctx}

    def _default_model(self, backend: str) -> str:
        defaults = {
            "ollama": os.environ.get("APP_DEFAULT_OLLAMA_LLM_MODEL", "qwen3:4b-instruct"),
            "openai": os.environ.get("APP_DEFAULT_OPENAI_LLM_MODEL", "gpt-4o-mini"),
            "anthropic": os.environ.get("APP_DEFAULT_ANTHROPIC_LLM_MODEL", "claude-haiku-4-5"),
        }
        return defaults[backend]

    def generate(self, question: str, context_chunks: list,
                 history: Optional[list[dict]] = None,
                 tools: Optional[dict[str, Callable]] = None) -> str:
        """
        Generate a grounded answer from indexed source chunks.

        Args:
            question: User question
            context_chunks: List of RetrievedChunk objects (or dicts with url/title/text)
            history: List of {"role": "user"|"assistant", "content": str} dicts (last N turns)

        Returns answer string.
        """
        context = self._build_context(context_chunks)
        messages = self._build_messages(question, context, history or [])

        if self.backend == "ollama":
            return self._call_ollama(messages, tools=tools)
        elif self.backend == "openai":
            return self._call_openai(messages)
        else:
            return self._call_anthropic(messages)

    def health_check(self) -> dict:
        """Validate backend access for the configured model."""
        if self.backend == "ollama":
            return self._health_check_ollama()
        if self.backend == "openai":
            return self._health_check_openai()
        return self._health_check_anthropic()

    def _build_context(self, chunks: list) -> str:
        """Format chunks into a context string with source citations."""
        if not chunks:
            return "No direct context available yet. Use tools if needed."
        parts = []
        for chunk in chunks:
            # Support both RetrievedChunk objects and plain dicts
            if hasattr(chunk, "url"):
                url, title, text = chunk.url, chunk.title, chunk.text
            else:
                url = chunk.get("url", "")
                title = chunk.get("title", "")
                text = chunk.get("text", "")
            parts.append(f"Source: [{title}]({url})\n{text}")
        return "\n\n---\n\n".join(parts)

    def _build_messages(self, question: str, context: str,
                        history: list[dict]) -> list[dict]:
        """Build the messages list for the LLM API."""
        messages = [{"role": "system", "content": _RAG_SYSTEM_PROMPT}]

        # Add last N turns of history
        for turn in history[-_MAX_HISTORY_TURNS:]:
            messages.append(turn)

        # Current question with context
        user_content = f"Context:\n{context}\n\nQuestion: {question}"
        messages.append({"role": "user", "content": user_content})
        return messages

    def _load_ollama_client(self):
        if self._ollama_client is None:
            try:
                import ollama
            except ImportError:
                raise ImportError("ollama package required. Install with: pip install ollama>=0.2.0")
            if hasattr(ollama, "Client"):
                self._ollama_client = ollama.Client(host=self.ollama_url)
            else:
                self._ollama_client = ollama
        return self._ollama_client

    def _response_message(self, response):
        if isinstance(response, dict):
            return response.get("message", {}) or {}
        return getattr(response, "message", {}) or {}

    def _message_content(self, message) -> str:
        if isinstance(message, dict):
            return message.get("content", "") or ""
        return getattr(message, "content", "") or ""

    def _message_thinking(self, message) -> str:
        if isinstance(message, dict):
            return message.get("thinking", "") or ""
        return getattr(message, "thinking", "") or ""

    def _message_tool_calls(self, message) -> list:
        if isinstance(message, dict):
            return message.get("tool_calls", []) or []
        return getattr(message, "tool_calls", []) or []

    def _normalize_tool_calls(self, tool_calls: list) -> list[dict]:
        normalized = []
        for call in tool_calls or []:
            if isinstance(call, dict):
                function = call.get("function", {}) or {}
                normalized.append({
                    "function": {
                        "name": function.get("name", ""),
                        "arguments": function.get("arguments", {}) or {},
                    }
                })
                continue
            function = getattr(call, "function", None)
            if function is None:
                continue
            normalized.append({
                "function": {
                    "name": getattr(function, "name", ""),
                    "arguments": getattr(function, "arguments", {}) or {},
                }
            })
        return normalized

    def _message_payload(self, message) -> dict:
        payload = {
            "role": "assistant",
            "content": self._message_content(message),
        }
        thinking = self._message_thinking(message)
        if thinking:
            payload["thinking"] = thinking
        tool_calls = self._normalize_tool_calls(self._message_tool_calls(message))
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return payload

    def _execute_tool(self, tool_name: str, arguments: dict, tools: dict[str, Callable]) -> str:
        tool = tools.get(tool_name)
        if tool is None:
            return f"Tool '{tool_name}' is not available."
        try:
            result = tool(**arguments)
        except TypeError as exc:
            return f"Tool '{tool_name}' argument error: {exc}"
        except Exception as exc:
            return f"Tool '{tool_name}' failed: {exc}"
        return str(result)

    def _ollama_model_names(self, client) -> list[str]:
        if not hasattr(client, "list"):
            return []
        response = client.list()
        if isinstance(response, dict):
            models = response.get("models", [])
        else:
            models = getattr(response, "models", response)

        names = []
        for item in models or []:
            if isinstance(item, dict):
                name = item.get("model") or item.get("name")
            else:
                name = getattr(item, "model", None) or getattr(item, "name", None)
            if name:
                names.append(name)
        return names

    def _health_check_ollama(self) -> dict:
        client = self._load_ollama_client()
        model_names = self._ollama_model_names(client)
        if model_names and self._model not in model_names:
            raise ValueError(
                f"Ollama model '{self._model}' is not available at {self.ollama_url}"
            )
        if not model_names:
            if hasattr(client, "show"):
                client.show(model=self._model)
            elif hasattr(client, "chat"):
                client.chat(
                    model=self._model,
                    messages=[{"role": "user", "content": "Reply with OK."}],
                )
            else:
                raise RuntimeError("Unable to validate Ollama connectivity for the configured model")
        return {
            "backend": self.backend,
            "model": self._model,
            "message": f"Ollama is reachable at {self.ollama_url} and model '{self._model}' is available.",
        }

    def _health_check_openai(self) -> dict:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required. Install with: pip install openai>=1.30.0")

        client = OpenAI(api_key=self.api_key)
        response = client.models.retrieve(self._model)
        resolved_model = getattr(response, "id", self._model)
        return {
            "backend": self.backend,
            "model": resolved_model,
            "message": f"OpenAI model '{resolved_model}' is available.",
        }

    def _health_check_anthropic(self) -> dict:
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required. Install with: pip install anthropic>=0.28.0")

        client = anthropic.Anthropic(api_key=self.api_key)
        if hasattr(client, "models") and hasattr(client.models, "list"):
            response = client.models.list()
            models = getattr(response, "data", response)
            model_names = [getattr(item, "id", None) for item in models or [] if getattr(item, "id", None)]
            if model_names and self._model not in model_names:
                raise ValueError(f"Anthropic model '{self._model}' is not available for this API key")
            return {
                "backend": self.backend,
                "model": self._model,
                "message": f"Anthropic model '{self._model}' is available.",
            }

        response = client.messages.create(
            model=self._model,
            max_tokens=1,
            messages=[{"role": "user", "content": "Reply with OK."}],
        )
        _ = response  # Keep a reference to confirm the request succeeded.
        return {
            "backend": self.backend,
            "model": self._model,
            "message": f"Anthropic model '{self._model}' responded successfully.",
        }

    def _call_ollama(self, messages: list[dict], tools: Optional[dict[str, Callable]] = None) -> str:
        try:
            client = self._load_ollama_client()
            if not tools:
                response = client.chat(
                    model=self._model,
                    messages=messages,
                    options=self._ollama_chat_options(),
                )
                message = self._response_message(response)
                return self._message_content(message)

            tool_functions = list(tools.values())
            conversation = list(messages)
            final_content = ""
            for _ in range(_MAX_TOOL_ROUNDS):
                response = client.chat(
                    model=self._model,
                    messages=conversation,
                    tools=tool_functions,
                    stream=False,
                    options=self._ollama_chat_options(),
                )
                message = self._response_message(response)
                final_content = self._message_content(message) or final_content
                conversation.append(self._message_payload(message))
                tool_calls = self._normalize_tool_calls(self._message_tool_calls(message))
                if not tool_calls:
                    return final_content
                for call in tool_calls:
                    function = call.get("function", {}) or {}
                    name = function.get("name", "")
                    arguments = function.get("arguments", {}) or {}
                    result = self._execute_tool(name, arguments, tools)
                    conversation.append({
                        "role": "tool",
                        "tool_name": name,
                        "content": result,
                    })
            return final_content or "I don't know based on the scraped content."
        except ImportError:
            raise ImportError("ollama package required. Install with: pip install ollama>=0.2.0")
        except Exception as exc:
            return f"[Ollama error: {exc}]"

    def _call_openai(self, messages: list[dict]) -> str:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self._model,
                messages=messages,
            )
            return response.choices[0].message.content or ""
        except ImportError:
            raise ImportError("openai package required. Install with: pip install openai>=1.30.0")
        except Exception as exc:
            return f"[OpenAI error: {exc}]"

    def _call_anthropic(self, messages: list[dict]) -> str:
        try:
            import anthropic
            # Anthropic uses separate system param
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            non_system = [m for m in messages if m["role"] != "system"]
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=system,
                messages=non_system,
            )
            return response.content[0].text
        except ImportError:
            raise ImportError("anthropic package required. Install with: pip install anthropic>=0.28.0")
        except Exception as exc:
            return f"[Anthropic error: {exc}]"
