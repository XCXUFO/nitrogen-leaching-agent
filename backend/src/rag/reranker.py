from __future__ import annotations

from typing import TYPE_CHECKING

from src.rag.retriever import RetrievalResult

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder


class Reranker:
    """Cross-encoder reranker for query-passage relevance scoring.

    Wraps ``BAAI/bge-reranker-v2-m3`` (multilingual XLM-RoBERTa cross-encoder).
    Used as the second stage after embedding recall: the embedder pulls
    ``top_k_recall`` candidates by cosine similarity, then this reranker
    re-scores each (query, passage) pair with a full attention pass and
    re-sorts.

    Score note: cross-encoder logits are unbounded (typically in roughly
    [-10, +10] for v2-m3), unlike the cosine ``score`` returned by the
    embedding path which lives in [0, 1]. Downstream UI must not assume
    a specific scale — only the ranking is portable.
    """

    def __init__(
        self,
        model_id: str = "BAAI/bge-reranker-v2-m3",
        device: str = "cpu",
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._model: CrossEncoder | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    def _ensure_loaded(self) -> CrossEncoder:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed. "
                    "Run `uv sync --extra rag` in backend/ before using Reranker."
                ) from exc

            self._model = CrossEncoder(self._model_id, device=self._device)
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        """Re-score and sort ``candidates`` by query-passage relevance.

        Returns a new list. The original embedding-stage ``score`` is
        replaced by the reranker logit; ``chunk_id`` / ``document`` /
        ``metadata`` are preserved verbatim.
        """
        if not candidates:
            return []

        model = self._ensure_loaded()
        pairs = [[query, c.document] for c in candidates]
        scores = model.predict(pairs)

        ranked = sorted(
            zip(scores, candidates),
            key=lambda pair: float(pair[0]),
            reverse=True,
        )
        return [
            RetrievalResult(
                chunk_id=c.chunk_id,
                document=c.document,
                score=float(s),
                metadata=c.metadata,
            )
            for s, c in ranked
        ]
