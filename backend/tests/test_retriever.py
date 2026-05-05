from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from src.rag.base import Embedder
from src.rag.retriever import RetrievalResult, Retriever

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("chromadb") is None,
    reason="chromadb optional dependency missing; run `uv sync --extra rag` to enable",
)

# Late import: only safe once the skipif above has gated the module
from src.storage.chroma_store import ChromaStore  # noqa: E402


class FakeEmbedder(Embedder):
    """Deterministic 4-dim embedder for tests.

    Maps each input to an L2-normalized vector based on a small lookup so
    we can pre-engineer which seeded chunk a query should be closest to.
    """

    _DIM = 4
    _LOOKUP: dict[str, list[float]] = {
        "alpha": [1.0, 0.0, 0.0, 0.0],
        "beta": [0.0, 1.0, 0.0, 0.0],
        "gamma": [0.0, 0.0, 1.0, 0.0],
        "delta": [0.0, 0.0, 0.0, 1.0],
        "alpha-prime": [0.99, 0.01, 0.0, 0.0],
    }

    @property
    def dim(self) -> int:
        return self._DIM

    def _vec(self, text: str) -> list[float]:
        if text in self._LOOKUP:
            v = self._LOOKUP[text]
        else:
            # Fallback: a stable but arbitrary unit vector
            v = [1.0, 0.0, 0.0, 0.0]
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


@pytest.fixture
def store(tmp_path: Path) -> ChromaStore:
    return ChromaStore(tmp_path / "chroma", "test-collection")


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


def _seed(store: ChromaStore, embedder: FakeEmbedder, items: list[tuple[str, str, dict]]) -> None:
    ids = [i[0] for i in items]
    docs = [i[1] for i in items]
    metas = [i[2] for i in items]
    vectors = embedder.embed_documents(docs)
    store.add(ids=ids, documents=docs, embeddings=vectors, metadatas=metas)


def test_retrieve_empty_query_returns_empty_list(
    store: ChromaStore, embedder: FakeEmbedder
) -> None:
    r = Retriever(embedder, store)
    assert r.retrieve("", k=5) == []
    assert r.retrieve("   \n\t  ", k=5) == []


def test_retrieve_invalid_k_raises(store: ChromaStore, embedder: FakeEmbedder) -> None:
    r = Retriever(embedder, store)
    with pytest.raises(ValueError):
        r.retrieve("alpha", k=0)
    with pytest.raises(ValueError):
        r.retrieve("alpha", k=-3)


def test_retrieve_returns_results_in_score_order(
    store: ChromaStore, embedder: FakeEmbedder
) -> None:
    _seed(
        store,
        embedder,
        [
            ("c0", "alpha", {"source": "doc-a"}),
            ("c1", "beta", {"source": "doc-b"}),
            ("c2", "gamma", {"source": "doc-c"}),
        ],
    )
    r = Retriever(embedder, store)
    results = r.retrieve("beta", k=3)

    assert len(results) == 3
    # Top hit should be the seeded "beta" chunk
    assert results[0].chunk_id == "c1"
    # Scores must be monotonically non-increasing
    scores = [hit.score for hit in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_passes_through_metadata(
    store: ChromaStore, embedder: FakeEmbedder
) -> None:
    _seed(
        store,
        embedder,
        [
            (
                "doc-001::0000",
                "alpha",
                {
                    "source": "papers/sample.txt",
                    "document_id": "doc-001",
                    "chunk_index": 0,
                    "char_start": 0,
                    "char_end": 100,
                },
            ),
        ],
    )
    r = Retriever(embedder, store)
    results = r.retrieve("alpha", k=1)
    assert len(results) == 1
    hit = results[0]
    assert hit.chunk_id == "doc-001::0000"
    assert hit.document == "alpha"
    assert hit.metadata["source"] == "papers/sample.txt"
    assert hit.metadata["chunk_index"] == 0
    assert hit.metadata["char_start"] == 0
    assert hit.metadata["char_end"] == 100


def test_retrieve_score_is_one_for_identical_vector(
    store: ChromaStore, embedder: FakeEmbedder
) -> None:
    """For an L2-normalized exact match, score should be ~1.0."""
    _seed(store, embedder, [("c0", "alpha", {"source": "a"})])
    r = Retriever(embedder, store)
    results = r.retrieve("alpha", k=1)
    assert len(results) == 1
    assert results[0].score == pytest.approx(1.0, abs=1e-5)


def test_retrieve_on_empty_collection_returns_empty_list(
    store: ChromaStore, embedder: FakeEmbedder
) -> None:
    r = Retriever(embedder, store)
    results = r.retrieve("anything", k=5)
    assert results == []


def test_retrieval_result_is_frozen() -> None:
    hit = RetrievalResult(chunk_id="x", document="y", score=0.5, metadata={"k": "v"})
    with pytest.raises(Exception):
        hit.score = 0.9  # type: ignore[misc]
