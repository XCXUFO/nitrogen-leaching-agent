from __future__ import annotations

import os

import pytest

from src.rag.reranker import Reranker
from src.rag.retriever import RetrievalResult


def _hit(cid: str, text: str, score: float = 0.5, src: str = "doc.pdf") -> RetrievalResult:
    return RetrievalResult(
        chunk_id=cid,
        document=text,
        score=score,
        metadata={"source": src, "char_start": 0, "char_end": len(text)},
    )


class FakeCrossEncoder:
    """Stand-in for ``sentence_transformers.CrossEncoder``.

    ``score_map`` keys are passage texts (or a fragment thereof matched via
    ``in``); ``predict`` looks up each (query, passage) pair and returns the
    matching score, defaulting to 0.0 when nothing matches. Lets tests
    pre-engineer the ranking the reranker should produce.
    """

    def __init__(self, score_map: dict[str, float]) -> None:
        self.score_map = score_map
        self.calls: list[list[list[str]]] = []

    def predict(self, pairs: list[list[str]]) -> list[float]:
        self.calls.append(pairs)
        out: list[float] = []
        for _query, passage in pairs:
            score = 0.0
            for needle, value in self.score_map.items():
                if needle in passage:
                    score = value
                    break
            out.append(score)
        return out


def _make_reranker(score_map: dict[str, float]) -> Reranker:
    """Reranker with ``_ensure_loaded`` bypassed to a fake cross-encoder."""
    rk = Reranker(model_id="fake://test-only")
    fake = FakeCrossEncoder(score_map)
    rk._model = fake  # type: ignore[assignment]
    return rk


def test_rerank_empty_candidates_returns_empty() -> None:
    rk = _make_reranker({})
    assert rk.rerank("any query", []) == []


def test_rerank_sorts_by_score_desc() -> None:
    rk = _make_reranker({"target": 9.0, "noise": 1.0, "filler": 5.0})
    candidates = [
        _hit("c0", "noise alpha"),
        _hit("c1", "target beta"),
        _hit("c2", "filler gamma"),
    ]
    out = rk.rerank("q", candidates)

    assert [c.chunk_id for c in out] == ["c1", "c2", "c0"]
    scores = [c.score for c in out]
    assert scores == sorted(scores, reverse=True)


def test_rerank_replaces_score_with_logit() -> None:
    rk = _make_reranker({"hot": 7.5})
    out = rk.rerank("q", [_hit("c0", "hot stuff", score=0.42)])

    assert out[0].chunk_id == "c0"
    # original embedding score (0.42) must be replaced
    assert out[0].score == pytest.approx(7.5)


def test_rerank_preserves_chunk_id_document_metadata() -> None:
    rk = _make_reranker({"foo": 1.0})
    candidates = [
        _hit(
            "doc-1::0007",
            "foo content here",
            score=0.3,
            src="papers/example.pdf",
        ),
    ]
    out = rk.rerank("q", candidates)

    assert out[0].chunk_id == "doc-1::0007"
    assert out[0].document == "foo content here"
    assert out[0].metadata["source"] == "papers/example.pdf"
    # metadata should be the same dict reference (preserved verbatim)
    assert out[0].metadata == candidates[0].metadata


def test_rerank_calls_predict_with_query_passage_pairs() -> None:
    rk = _make_reranker({"a": 1.0})
    candidates = [_hit("c0", "a one"), _hit("c1", "a two")]
    rk.rerank("the query", candidates)

    fake = rk._model  # type: ignore[assignment]
    assert isinstance(fake, FakeCrossEncoder)
    assert len(fake.calls) == 1
    pairs = fake.calls[0]
    assert pairs == [["the query", "a one"], ["the query", "a two"]]


def test_rerank_handles_negative_scores() -> None:
    rk = _make_reranker({"good": 4.2, "bad": -3.1})
    out = rk.rerank("q", [_hit("c0", "bad case"), _hit("c1", "good case")])

    assert [c.chunk_id for c in out] == ["c1", "c0"]
    assert out[0].score == pytest.approx(4.2)
    assert out[1].score == pytest.approx(-3.1)


# ---------------------------------------------------------------------------
# Live test (gated): hits the real bge-reranker-v2-m3 model on disk.
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_RERANK") != "1",
    reason="set RUN_LIVE_RERANK=1 to run the live reranker test (loads ~2.2 GB)",
)
def test_live_reranker_orders_relevant_higher() -> None:
    """Tiny end-to-end check: a clearly relevant passage must outrank noise."""
    rk = Reranker(model_id="data/models/bge-reranker-v2-m3")
    query = "硝态氮淋失是什么？"
    candidates = [
        _hit("c0", "今天天气很好，适合散步。"),
        _hit("c1", "硝态氮淋失指土壤中硝酸根离子随水流向下渗透流失的过程。"),
        _hit("c2", "我喜欢吃苹果。"),
    ]
    out = rk.rerank(query, candidates)
    assert out[0].chunk_id == "c1"
