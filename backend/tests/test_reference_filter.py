from __future__ import annotations

import pytest

from src.rag.base import Embedder
from src.rag.reference_filter import filter_reference_chunks, is_reference_chunk
from src.rag.retriever import RetrievalResult, Retriever


REFERENCE_TEXT = """
Liang, X., Xu, L., Li, H., He, M., Qian, Y., Liu, J., 2011. Influence
of N fertilization rates, rainfall, and temperature on nitrate leaching.
Phys. Chem. Earth 36, 395-400.
Zhang, L., Zhai, L., Zhou, F., Ye, Y., 2019. Effects and potential of
water-saving irrigation. Agric. Water Manage. 208, 1-10.
https://doi.org/10.1016/j.agwat.2019.01.001
"""

BODY_TEXT = """
The subsurface N flux was 2-fold larger than surface runoff during the rice
growing season. Lateral seepage contributed 33% of the subsurface N loss,
indicating that optimized irrigation management is important.
"""


def test_is_reference_chunk_detects_bibliography_entries() -> None:
    assert is_reference_chunk(REFERENCE_TEXT)


def test_is_reference_chunk_keeps_body_evidence_with_citations() -> None:
    body_with_citation = (
        BODY_TEXT
        + " Similar leaching behavior was also discussed by Yang et al. (2015)."
    )

    assert not is_reference_chunk(body_with_citation)


def test_filter_reference_chunks_drops_refs_when_enough_body_candidates() -> None:
    ref = RetrievalResult("ref", REFERENCE_TEXT, 1.0, {"source": "a"})
    body_a = RetrievalResult("body-a", BODY_TEXT, 0.9, {"source": "a"})
    body_b = RetrievalResult("body-b", "Observed leaching was 6.2 kg N ha-1.", 0.8, {})

    kept, removed = filter_reference_chunks([ref, body_a, body_b], min_keep=2)

    assert [h.chunk_id for h in kept] == ["body-a", "body-b"]
    assert [h.chunk_id for h in removed] == ["ref"]


def test_filter_reference_chunks_restores_refs_to_min_keep() -> None:
    ref_a = RetrievalResult("ref-a", REFERENCE_TEXT, 1.0, {})
    ref_b = RetrievalResult("ref-b", REFERENCE_TEXT, 0.9, {})

    kept, removed = filter_reference_chunks([ref_a, ref_b], min_keep=1)

    assert [h.chunk_id for h in kept] == ["ref-a"]
    assert [h.chunk_id for h in removed] == ["ref-b"]


class _FakeEmbedder(Embedder):
    @property
    def dim(self) -> int:
        return 1

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0]


class _FakeStore:
    def __init__(self) -> None:
        self.query_k: int | None = None

    def query(self, embedding: list[float], k: int = 5) -> dict:
        self.query_k = k
        return {
            "ids": [["ref", "body-a", "body-b"]],
            "documents": [[REFERENCE_TEXT, BODY_TEXT, "Observed 6.2 kg N ha-1."]],
            "distances": [[0.0, 0.2, 0.4]],
            "metadatas": [[{"source": "r"}, {"source": "a"}, {"source": "b"}]],
        }


def test_retriever_filters_references_before_final_k() -> None:
    store = _FakeStore()
    retriever = Retriever(
        _FakeEmbedder(),
        store,  # type: ignore[arg-type]
        reference_filter_enabled=True,
        reference_filter_min_keep=2,
        reference_filter_overfetch=3,
    )

    results = retriever.retrieve("subsurface runoff", k=2)

    assert store.query_k == 6
    assert [h.chunk_id for h in results] == ["body-a", "body-b"]


def test_retriever_reference_filter_validation() -> None:
    with pytest.raises(ValueError):
        Retriever(
            _FakeEmbedder(),
            _FakeStore(),  # type: ignore[arg-type]
            reference_filter_min_keep=0,
        )
    with pytest.raises(ValueError):
        Retriever(
            _FakeEmbedder(),
            _FakeStore(),  # type: ignore[arg-type]
            reference_filter_overfetch=0,
        )
