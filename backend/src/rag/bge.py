from __future__ import annotations

from typing import TYPE_CHECKING

from src.rag.base import Embedder

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class BGEEmbedder(Embedder):
    """BGE-large-zh-v1.5 implementation.

    - dim = 1024 (fixed for this model)
    - v1.5 has no asymmetric query/passage prefix; both methods share one path
    - normalize_embeddings=True so cosine similarity equals dot product
    """

    _DIM = 1024

    def __init__(
        self,
        model_id: str = "BAAI/bge-large-zh-v1.5",
        device: str = "cpu",
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._model: SentenceTransformer | None = None

    @property
    def dim(self) -> int:
        return self._DIM

    def _ensure_loaded(self) -> SentenceTransformer:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed. "
                    "Run `uv sync --extra rag` in backend/ before using BGEEmbedder."
                ) from exc

            self._model = SentenceTransformer(self._model_id, device=self._device)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_loaded()
        vectors = model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        model = self._ensure_loaded()
        vector = model.encode([text], normalize_embeddings=True)[0]
        return vector.tolist()
