"""
Embedding abstraction supporting two backends:
  - "local": BAAI/bge-m3 via sentence-transformers (offline, ~570MB download)
  - "openai": OpenAI text-embedding-3-small via API

Usage:
    embedder = Embedder(backend="local")   # or backend="openai", api_key="sk-..."
    vectors = embedder.embed(["chunk 1", "chunk 2"])
    # Returns list of float lists
"""
from typing import Optional


class Embedder:
    """Unified embedding interface for local (BGE-M3) and API (OpenAI) backends."""

    SUPPORTED_BACKENDS = ("local", "openai")

    def __init__(self, backend: str = "local", api_key: Optional[str] = None,
                 model: Optional[str] = None):
        """
        Args:
            backend: "local" for BGE-M3 or "openai" for OpenAI API
            api_key: Required for "openai" backend
            model: Override default model. Defaults: local="BAAI/bge-m3", openai="text-embedding-3-small"
        """
        if backend not in self.SUPPORTED_BACKENDS:
            raise ValueError(f"backend must be one of {self.SUPPORTED_BACKENDS}, got {backend!r}")
        if backend == "openai" and not api_key:
            raise ValueError("api_key is required for openai backend")

        self.backend = backend
        self.api_key = api_key
        self._model_name = model or self._default_model(backend)
        self._model = None  # lazy-loaded

    def _default_model(self, backend: str) -> str:
        return "BAAI/bge-m3" if backend == "local" else "text-embedding-3-small"

    @property
    def dimensions(self) -> int:
        """Return embedding dimensions for the current model."""
        _dims = {
            "BAAI/bge-m3": 1024,
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }
        return _dims.get(self._model_name, 1024)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts. Returns list of float vectors.
        Lazy-loads the model on first call.
        """
        if not texts:
            return []
        if self.backend == "local":
            return self._embed_local(texts)
        else:
            return self._embed_openai(texts)

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
