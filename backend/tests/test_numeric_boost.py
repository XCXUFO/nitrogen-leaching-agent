from __future__ import annotations

from src.rag.numeric_boost import (
    DEFAULT_NUMERIC_BOOST_BAND,
    DEFAULT_NUMERIC_BOOST_WEIGHT,
    apply_numeric_boost,
    is_quantitative_query,
    numeric_evidence_density,
)
from src.rag.retriever import RetrievalResult

# Synthetic chunks only — no real question id / target chunk id / expected
# answer literal appears here (M1.5-b anti-overfit boundary, DoD-4).

STAT_TEXT = (
    "The determination coefficient ranged from a to b. RMSE values ranged "
    "between two numbers like 240 and 1100 kg ha-1. The IA indices were all "
    "over 0.7 and NSE was close to 1.0."
)
NARRATIVE_TEXT = (
    "The model successfully simulated soil water content and crop development, "
    "and explained the difference under various management practices."
)


def _result(chunk_id: str, document: str, score: float) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        document=document,
        score=score,
        metadata={"source": "paper.pdf"},
    )


# --- gate ---------------------------------------------------------------------


def test_quantitative_gate_fires_on_quantity_questions() -> None:
    assert is_quantitative_query("淋失量分别是多少？")
    assert is_quantitative_query("两种处理的氮淋失量范围是多少？")
    assert is_quantitative_query("地下径流和地表径流相比量级如何？贡献多少？")
    assert is_quantitative_query("模拟作物产量的精度如何？")
    assert is_quantitative_query("How much nitrogen was leached and what is the RMSE?")


def test_quantitative_gate_silent_on_conceptual_questions() -> None:
    # mechanism / composition / synthesis — must keep cross-encoder order
    assert not is_quantitative_query("该模型由哪些主要模块组成？借鉴了哪些模型？")
    assert not is_quantitative_query("为什么侧向渗漏水的氮浓度高于垂直淋溶水？")
    assert not is_quantitative_query("相关研究提出过哪些可行的管理措施？")
    assert not is_quantitative_query("某奖项获得者的主要工作是什么？")


# --- density ------------------------------------------------------------------


def test_density_ranks_statistics_above_narrative() -> None:
    assert numeric_evidence_density(STAT_TEXT) > numeric_evidence_density(NARRATIVE_TEXT)


def test_density_bounds_and_empty() -> None:
    assert numeric_evidence_density("") == 0.0
    assert 0.0 <= numeric_evidence_density(STAT_TEXT) <= 1.0
    assert numeric_evidence_density(NARRATIVE_TEXT) == 0.0


# --- apply_numeric_boost: no-op paths ----------------------------------------


def test_boost_noop_when_weight_not_positive() -> None:
    cands = [_result("a::1", STAT_TEXT, 0.4), _result("b::1", NARRATIVE_TEXT, 0.9)]
    out = apply_numeric_boost("淋失量是多少？", cands, weight=0.0)
    assert [c.chunk_id for c in out] == ["a::1", "b::1"]
    assert "numeric_boost_delta" not in out[0].metadata


def test_boost_noop_when_query_not_quantitative() -> None:
    cands = [_result("a::1", NARRATIVE_TEXT, 0.9), _result("b::1", STAT_TEXT, 0.4)]
    out = apply_numeric_boost(
        "该模型由哪些模块组成？", cands, weight=DEFAULT_NUMERIC_BOOST_WEIGHT
    )
    assert [c.chunk_id for c in out] == ["a::1", "b::1"]
    assert all("numeric_boost_delta" not in c.metadata for c in out)


def test_boost_noop_on_empty() -> None:
    assert apply_numeric_boost("多少？", [], weight=0.5) == []


# --- apply_numeric_boost: active path ----------------------------------------


def test_boost_reorders_data_chunk_above_narrative() -> None:
    # narrative leads by reranker score but is within the relevance band of the
    # stats chunk; a large enough weight lifts the statistics chunk past it.
    narrative = _result("narr::1", NARRATIVE_TEXT, 0.90)
    stats = _result("stat::1", STAT_TEXT, 0.65)  # gap 0.25 < band 0.30 -> eligible
    out = apply_numeric_boost("精度是多少？", [narrative, stats], weight=2.0)
    assert out[0].chunk_id == "stat::1"
    assert out[0].metadata["numeric_boost_eligible"] is True


def test_boost_stamps_audit_metadata_and_keeps_payload() -> None:
    stats = _result("stat::1", STAT_TEXT, 0.60)
    out = apply_numeric_boost(
        "精度是多少？", [stats], weight=DEFAULT_NUMERIC_BOOST_WEIGHT
    )
    hit = out[0]
    assert hit.chunk_id == "stat::1"
    assert hit.document == STAT_TEXT
    assert hit.metadata["source"] == "paper.pdf"
    raw = hit.metadata["numeric_boost_raw_score"]
    density = hit.metadata["numeric_boost_density"]
    delta = hit.metadata["numeric_boost_delta"]
    assert raw == 0.60
    assert hit.metadata["numeric_boost_eligible"] is True  # sole chunk == leader
    assert hit.metadata["numeric_boost_band"] == DEFAULT_NUMERIC_BOOST_BAND
    assert delta == DEFAULT_NUMERIC_BOOST_WEIGHT * density
    assert hit.score == raw + delta


def test_boost_band_excludes_chunk_far_below_leader() -> None:
    # A numeric-dense chunk the reranker scored far below the leader (gap > band)
    # must NOT be resurrected on density alone — this is the q01 regression fix.
    leader = _result("lead::1", NARRATIVE_TEXT, 1.00)  # high relevance, no numbers
    far_stats = _result("far::1", STAT_TEXT, 0.50)  # gap 0.50 > band 0.30
    out = apply_numeric_boost("精度是多少？", [leader, far_stats], weight=2.0)
    assert [c.chunk_id for c in out] == ["lead::1", "far::1"]
    far = next(c for c in out if c.chunk_id == "far::1")
    assert far.metadata["numeric_boost_eligible"] is False
    assert far.metadata["numeric_boost_delta"] == 0.0
    assert far.score == far.metadata["numeric_boost_raw_score"]  # unchanged


def test_boost_does_not_mutate_input() -> None:
    stats = _result("stat::1", STAT_TEXT, 0.60)
    before_score, before_meta = stats.score, dict(stats.metadata)
    apply_numeric_boost("精度是多少？", [stats], weight=DEFAULT_NUMERIC_BOOST_WEIGHT)
    assert stats.score == before_score
    assert stats.metadata == before_meta
