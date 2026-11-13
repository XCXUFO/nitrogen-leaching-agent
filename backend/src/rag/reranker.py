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
        *,
        max_length: int = 512,
        batch_size: int = 2,
        cpu_quantization: str = "none",
    ) -> None:
        if max_length < 32 or batch_size < 1:
            raise ValueError("Invalid reranker sequence length or batch size")
        if cpu_quantization not in {"none", "int8"}:
            raise ValueError("Unsupported CPU quantization")
        if cpu_quantization != "none" and device != "cpu":
            raise ValueError("Dynamic INT8 quantization requires the CPU device")
        self._model_id = model_id
        self._device = device
        self._max_length = max_length
        self._batch_size = batch_size
        self._cpu_quantization = cpu_quantization
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

            model = CrossEncoder(self._model_id, device=self._device, max_length=self._max_length)
            if self._cpu_quantization == "int8":
                import torch
                # The model is newly created and exclusively owned here. Avoid
                # an extra full FP32 copy during startup on memory-limited CPUs.
                quantized = torch.ao.quantization.quantize_dynamic(
                    model.model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)
                # v5 exposes model as a read-only property over the first
                # Transformer module; v3 stores the transformer directly.
                if isinstance(getattr(type(model), "model", None), property):
                    model[0].model = quantized
                else:
                    model.model = quantized
            self._model = model
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
        scores = model.predict(pairs, batch_size=self._batch_size, show_progress_bar=False)

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
