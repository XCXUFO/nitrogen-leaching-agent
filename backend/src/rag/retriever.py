from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.rag.base import Embedder
from src.rag.numeric_boost import (
    DEFAULT_NUMERIC_BOOST_BAND,
    DEFAULT_NUMERIC_BOOST_WEIGHT,
    apply_numeric_boost,
)
from src.rag.reference_filter import filter_reference_chunks
from src.rag.source_labels import article_label
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


def describe_hits(results: list[RetrievalResult]) -> list[dict]:
    """Persist ordering and source identity without duplicating passage bodies."""
    snapshots = []
    for rank, item in enumerate(results, 1):
        identity = {key: item.metadata[key] for key in ('paper_id', 'title', 'source') if item.metadata.get(key)}
        if not identity.get('title') and identity.get('source'):
            try:
                title, _ = article_label(str(identity['source']))
                if title: identity['title'] = title
            except (OSError, ValueError, TypeError):
                pass  # An unavailable display-name manifest cannot block retrieval.
        snapshots.append({'chunk_id': item.chunk_id, 'rank': rank, 'score': item.score, **identity})
    return snapshots


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
       (2b. optional numeric/evidence boost re-orders the reranked pool before
            the top ``k`` cut when ``numeric_boost_enabled`` — M1.5-b)

    When ``reranker`` is None, behavior matches M1.3.x exactly: recall ``k``
    via embedding only.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: ChromaStore,
        reranker: "Reranker | None" = None,
        top_k_recall: int = 20,
        reference_filter_enabled: bool = False,
        reference_filter_min_keep: int = 1,
        reference_filter_overfetch: int = 2,
        numeric_boost_enabled: bool = False,
        numeric_boost_weight: float = DEFAULT_NUMERIC_BOOST_WEIGHT,
        numeric_boost_band: float = DEFAULT_NUMERIC_BOOST_BAND,
    ) -> None:
        if top_k_recall <= 0:
            raise ValueError(f"top_k_recall must be positive, got {top_k_recall}")
        if reference_filter_min_keep <= 0:
            raise ValueError(
                "reference_filter_min_keep must be positive, "
                f"got {reference_filter_min_keep}"
            )
        if reference_filter_overfetch <= 0:
            raise ValueError(
                "reference_filter_overfetch must be positive, "
                f"got {reference_filter_overfetch}"
            )
        self._embedder = embedder
        self._store = store
        self._reranker = reranker
        self._top_k_recall = top_k_recall
        self._reference_filter_enabled = reference_filter_enabled
        self._reference_filter_min_keep = reference_filter_min_keep
        self._reference_filter_overfetch = reference_filter_overfetch
        self._numeric_boost_enabled = numeric_boost_enabled
        self._numeric_boost_weight = numeric_boost_weight
        self._numeric_boost_band = numeric_boost_band

    def retrieve(self, query: str, k: int = 5, *,
                 eligibility_filter: Callable[[RetrievalResult], bool] | None = None,
                 diagnostics: dict | None = None, where: dict | None = None) -> list[RetrievalResult]:
        if not query.strip():
            return []
        if k <= 0:
            raise ValueError(f"k must be positive, got {k}")

        recall_k = max(self._top_k_recall, k) if self._reranker is not None else k

        raw_k = (
            recall_k * self._reference_filter_overfetch
            if self._reference_filter_enabled
            else recall_k
        )

        vector = self._embedder.embed_query(query)
        raw = self._store.query(vector, k=raw_k, **({'where':where} if where is not None else {}))

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

        if diagnostics is not None:
            diagnostics.update(recall=describe_hits(results), rerank_status='disabled' if self._reranker is None else 'no_candidates')

        # Exclude unavailable or outdated papers before spending cross-encoder
        # inference on them, and before a top-k cut can crowd out usable hits.
        if eligibility_filter is not None:
            results = [item for item in results if eligibility_filter(item)]

        if self._reference_filter_enabled and results:
            results, _ = filter_reference_chunks(
                results,
                min_keep=self._reference_filter_min_keep,
            )
            results = results[:recall_k]

        if self._reranker is not None and results:
            results = self._reranker.rerank(query, results)
            if diagnostics is not None:
                diagnostics.update(rerank_status='applied', reranked=describe_hits(results))
            # numeric/evidence boost is a reranker post-processing step — only
            # reachable on the reranker path, so non-reranker retrieval is
            # unchanged (M1.5-b). No-op unless enabled and the query is
            # quantitative (see apply_numeric_boost).
            if self._numeric_boost_enabled:
                results = apply_numeric_boost(
                    query,
                    results,
                    weight=self._numeric_boost_weight,
                    band=self._numeric_boost_band,
                )

        if diagnostics is not None:
            diagnostics.update(returned=describe_hits(results[:k]), numeric_boost_enabled=self._numeric_boost_enabled)
        return results[:k]
