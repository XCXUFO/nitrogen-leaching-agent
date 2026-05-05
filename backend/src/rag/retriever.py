from __future__ import annotations

from dataclasses import dataclass

from src.rag.base import Embedder
from src.storage.chroma_store import ChromaStore

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
    """Compose Embedder + ChromaStore into a query-time retrieval pipeline.

    Sync API. Async callers (e.g. FastAPI routes) must dispatch via
    ``asyncio.to_thread(retriever.retrieve, query, k)``. See M1.2.3 spec §3.9.

    Score conversion (spec §3.8): assumes embedder output is L2-normalized,
    so ``score = 1 - L2_squared / 2`` recovers cosine similarity in [0, 1].
    """

    def __init__(self, embedder: Embedder, store: ChromaStore) -> None:
        self._embedder = embedder
        self._store = store

    def retrieve(self, query: str, k: int = 5) -> list[RetrievalResult]:
        if not query.strip():
            return []
        if k <= 0:
            raise ValueError(f"k must be positive, got {k}")

        vector = self._embedder.embed_query(query)
        raw = self._store.query(vector, k=k)

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
        return results
