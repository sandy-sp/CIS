"""
Embedding abstraction supporting two backends:
  - "local": BAAI/bge-m3 via sentence-transformers (offline, ~570MB download)
  - "ollama": Local embedding models via Ollama
  - "openai": OpenAI text-embedding-3-small via API

Usage:
    embedder = Embedder(backend="local")   # or backend="ollama" / backend="openai", api_key="sk-..."
    vectors = embedder.embed(["chunk 1", "chunk 2"])
    # Returns list of float lists
"""
import os
from typing import Optional


class Embedder:
    """Unified embedding interface for local, Ollama, and OpenAI backends."""

    SUPPORTED_BACKENDS = ("local", "ollama", "openai")

    def __init__(self, backend: str = "local", api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 ollama_url: Optional[str] = None):
        """
        Args:
            backend: "local" for BGE-M3, "ollama" for local Ollama embeddings, or "openai"
            api_key: Required for "openai" backend
            model: Override default model.
                   Defaults: local="BAAI/bge-m3", ollama="nomic-embed-text", openai="text-embedding-3-small"
        """
        if backend not in self.SUPPORTED_BACKENDS:
            raise ValueError(f"backend must be one of {self.SUPPORTED_BACKENDS}, got {backend!r}")
        if backend == "openai" and not api_key:
            raise ValueError("api_key is required for openai backend")

        self.backend = backend
        self.api_key = api_key
        self.ollama_url = ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        self._model_name = model or self._default_model(backend)
        self._model = None  # lazy-loaded
        self._ollama_client = None
        self._inferred_dimensions: Optional[int] = None

    def _default_model(self, backend: str) -> str:
        defaults = {
            "local": os.environ.get("APP_DEFAULT_LOCAL_EMBEDDING_MODEL", "BAAI/bge-m3"),
            "ollama": os.environ.get("APP_DEFAULT_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
            "openai": os.environ.get("APP_DEFAULT_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        }
        return defaults[backend]

    @property
    def dimensions(self) -> int:
        """Return embedding dimensions for the current model."""
        _dims = {
            "BAAI/bge-m3": 1024,
            "nomic-embed-text": 768,
            "mxbai-embed-large": 1024,
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }
        if self._model_name in _dims:
            return _dims[self._model_name]
        if self.backend == "ollama":
            if self._inferred_dimensions is None:
                vectors = self._embed_ollama(["dimension probe"])
                self._inferred_dimensions = len(vectors[0]) if vectors and vectors[0] else 1024
            return self._inferred_dimensions
        return 1024

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts. Returns list of float vectors.
        Lazy-loads the model on first call.
        """
        if not texts:
            return []
        if self.backend == "local":
            return self._embed_local(texts)
        if self.backend == "ollama":
            return self._embed_ollama(texts)
        else:
            return self._embed_openai(texts)

    def health_check(self) -> dict:
        """Validate embedding access for the configured backend."""
        vectors = self.embed(["health check"])
        dimensions = len(vectors[0]) if vectors and vectors[0] else self.dimensions
        return {
            "backend": self.backend,
            "model": self._model_name,
            "dimensions": dimensions,
            "message": (
                f"Embedding backend '{self.backend}' is ready with model "
                f"'{self._model_name}' ({dimensions} dimensions)."
            ),
        }

    def _load_local_model(self):
        """Lazy-load sentence-transformers model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self._model_name)
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for local embedding. "
                    "Install with: pip install sentence-transformers>=3.0.0"
                )
        return self._model

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        model = self._load_local_model()
        embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [vec.tolist() for vec in embeddings]

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai package is required for OpenAI embedding. "
                "Install with: pip install openai>=1.30.0"
            )
        client = OpenAI(api_key=self.api_key)
        response = client.embeddings.create(input=texts, model=self._model_name)
        return [item.embedding for item in response.data]

    def _load_ollama_client(self):
        if self._ollama_client is None:
            try:
                import ollama
            except ImportError:
                raise ImportError(
                    "ollama package is required for Ollama embeddings. "
                    "Install with: pip install ollama>=0.2.0"
                )
            if hasattr(ollama, "Client"):
                self._ollama_client = ollama.Client(host=self.ollama_url)
            else:
                self._ollama_client = ollama
        return self._ollama_client

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        client = self._load_ollama_client()
        if hasattr(client, "embed"):
            response = client.embed(model=self._model_name, input=texts)
            embeddings = response.get("embeddings", [])
        elif hasattr(client, "embeddings"):
            embeddings = [
                client.embeddings(model=self._model_name, prompt=text).get("embedding", [])
                for text in texts
            ]
        else:
            raise RuntimeError("Configured ollama client does not support embeddings")
        return [list(embedding) for embedding in embeddings]
