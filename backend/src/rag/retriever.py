from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.rag.base import Embedder
from src.storage.chroma_store import ChromaStore

if TYPE_CHECKING:
    from src.rag.reranker import Reranker

ChunkMetaValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Query-time hit. Field naming aligns with chromadb (``documents``)
    so M1.3 chat routes can consume ``result.document`` and
    ``result.metadata["source"]`` without further adaptation.
    """

    chunk_id: str
    document: str
    score: float                                   # higher == more similar
    metadata: dict[str, ChunkMetaValue]


class Retriever:
    """Compose Embedder + ChromaStore (+ optional Reranker) into a query-time
    retrieval pipeline.

    Sync API. Async callers (e.g. FastAPI routes) must dispatch via
    ``asyncio.to_thread(retriever.retrieve, query, k)``. See M1.2.3 spec §3.9.

    Score conversion (spec §3.8): assumes embedder output is L2-normalized,
    so ``score = 1 - L2_squared / 2`` recovers cosine similarity in [0, 1].
    When a reranker is attached, the embedding score is replaced by the
    reranker logit (unbounded; only ranking is portable — see ``Reranker``).

    Two-stage flow when ``reranker`` is provided (M1.4-b):
        1. embedder + chroma recall ``max(top_k_recall, k)`` candidates
        2. reranker re-scores and sorts; top ``k`` are returned

    When ``reranker`` is None, behavior matches M1.3.x exactly: recall ``k``
    via embedding only.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: ChromaStore,
        reranker: "Reranker | None" = None,
        top_k_recall: int = 20,
    ) -> None:
        if top_k_recall <= 0:
            raise ValueError(f"top_k_recall must be positive, got {top_k_recall}")
        self._embedder = embedder
        self._store = store
        self._reranker = reranker
        self._top_k_recall = top_k_recall

    def retrieve(self, query: str, k: int = 5) -> list[RetrievalResult]:
        if not query.strip():
            return []
        if k <= 0:
            raise ValueError(f"k must be positive, got {k}")

        recall_k = max(self._top_k_recall, k) if self._reranker is not None else k

        vector = self._embedder.embed_query(query)
        raw = self._store.query(vector, k=recall_k)

        ids = (raw.get("ids") or [[]])[0]
        docs = (raw.get("documents") or [[]])[0]
        dists = (raw.get("distances") or [[]])[0]
        metas_raw = (raw.get("metadatas") or [[]])[0]
        metas = metas_raw if metas_raw else [{}] * len(ids)

        results: list[RetrievalResult] = []
        for cid, doc, dist, meta in zip(ids, docs, dists, metas):
            score = 1.0 - float(dist) / 2.0
            results.append(
                RetrievalResult(
                    chunk_id=cid,
                    document=doc,
                    score=score,
                    metadata=dict(meta) if meta else {},
                )
            )

        if self._reranker is not None and results:
            results = self._reranker.rerank(query, results)

        return results[:k]
