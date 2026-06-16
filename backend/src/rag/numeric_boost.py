"""Numeric / evidence boost — a post-rerank re-score that lifts numeric and
statistical *data* chunks the cross-encoder tends to underweight.

Motivation (M1.5-b): the ``bge-reranker-v2-m3`` cross-encoder rewards narrative
relevance and routinely ranks a paper's *statistics* paragraph (model accuracy
metrics, measured quantities, result tables) below its narrative summary. For a
quantitative question this buries the exact chunk that carries the answer's
numbers below ``top_n`` — e.g. q08's ``026::0172`` (R²/RMSE/IA) sits at rerank
rank 13 under the A2 default while five narrative chunks take the top slots.

Design constraints (M1.5-b spec §4.2, user hard boundary — anti-overfit):

- The signal is derived **only** from generic ``query`` × ``chunk`` features:
  a *quantitative-intent* gate on the query, and a *numeric/statistical/table
  evidence density* on the chunk. No question id, no target chunk id, no
  expected-answer literal appears anywhere here.
- ``weight`` is the single tunable knob, calibrated to the minimum that lifts
  the target into ``top_n`` plus a small margin (spec §4.3). It lives in
  ``DEFAULT_NUMERIC_BOOST_WEIGHT`` as the single source of truth.

This is a pure module (regex + arithmetic, no model), shared by the production
``Retriever`` path and ``scripts/context_debug.py`` so the offline A/B gate
measures the same ordering production produces (mirrors ``reference_filter``).

Score note: it operates on reranker logits (unbounded, ≈ [-10, 10]); the boost
is added in that same logit space, so ``weight`` is a logit-space increment.
"""
from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.rag.retriever import RetrievalResult

# First-candidate default from the q08 calibration scan (spec §4.3): the
# minimum weight that puts 026::0172 into top_n was 0.395; +0.05 margin lands
# mid-plateau (stable r5 across 0.40–0.70). NOT the final demo default until
# DoD-2 (q01–q10 on/off regression) passes — production stays off until then.
DEFAULT_NUMERIC_BOOST_WEIGHT = 0.445

# --- query side: quantitative-intent gate ------------------------------------
# Fires when the query explicitly asks for a quantity / magnitude / metric.
# Deliberately excludes bare "浓度"/"高于" so mechanism questions ("why is the
# concentration higher", q06) do NOT fire, and excludes q08 wording (WHCNS /
# 华北平原 / 产量) so the gate is not tuned to the target question.
_QUANT_QUERY_RE = re.compile(
    r"(多少|几多|范围|量级|比例|占比|贡献(?:率|度)?|百分[之比]|几?倍|"
    r"系数|误差|精度|准确度?|精确度?|显著性?|"
    r"how\s+much|how\s+many|accuracy|precision|\bRMSE\b|R²|R\^?2|"
    r"coefficient|\brate\b|\bratio\b)",
    re.IGNORECASE,
)

# --- chunk side: numeric / statistical / table evidence density --------------
# General statistics-evaluation vocabulary (NOT q08 wording): model-fit metrics
# and significance markers that signal a results/data paragraph.
_STAT_RE = re.compile(
    r"(R²|R\^?2|\bRMSE\b|\bIA\b|\bNSE\b|\bMAE\b|\bRRMSE\b|\bd-index\b|"
    r"determination coefficient|coefficient of determination|"
    r"index of agreement|root mean square|"
    r"决定系数|相关系数|均方根|一致性指数|拟合优度|显著性|"
    r"\bp\s*[<>=]|\br\s*=)",
    re.IGNORECASE,
)
# Numeric tokens: integers, decimals, thousands — the raw "this chunk carries
# numbers" signal.
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
# Units that typically attach to quantitative evidence in this corpus.
_UNIT_RE = re.compile(
    r"(kg\s*ha|mg\s*L|kg\s*N|t\s*ha|m3|mm\b|%|‰|±|ha[-−]?1|L[-−]?1)",
    re.IGNORECASE,
)
# Structured-evidence markers (results tables).
_TBL_RE = re.compile(r"(Table|表\s*\d|Tab\.)", re.IGNORECASE)

# Component blend weights (sum to 1.0); each component is normalized to ~[0,1]
# so density(chunk) ∈ [0,1]. Tuned by the general goal "surface data paragraphs
# over narrative", not fit to make 026::0172 win (that is the weight's job).
_W_STAT, _W_NUM, _W_UNIT, _W_TBL = 0.45, 0.30, 0.15, 0.10


def is_quantitative_query(query: str) -> bool:
    """True when the query explicitly asks for a quantity, magnitude or metric.

    Gate for the boost: when False the boost is a no-op, so conceptual /
    mechanism / synthesis questions keep the cross-encoder's ordering verbatim.
    """
    return bool(_QUANT_QUERY_RE.search(query or ""))


def numeric_evidence_density(text: str) -> float:
    """Density of numeric / statistical / table evidence in ``text``, in [0, 1].

    A blend of: statistical-metric vocabulary, numeric-token density per 100
    chars, unit hits, and table markers. Higher == more "this is a data/results
    paragraph". Pure function of the chunk text — no query, no corpus state.
    """
    if not text:
        return 0.0
    length = len(text)
    per100 = 100.0 / length

    c_stat = min(len(_STAT_RE.findall(text)), 4) / 4.0
    c_num = min(len(_NUM_RE.findall(text)) * per100 / 3.0, 1.0)
    c_unit = min(len(_UNIT_RE.findall(text)), 4) / 4.0
    c_tbl = min(len(_TBL_RE.findall(text)), 2) / 2.0

    return _W_STAT * c_stat + _W_NUM * c_num + _W_UNIT * c_unit + _W_TBL * c_tbl


def apply_numeric_boost(
    query: str,
    reranked: list["RetrievalResult"],
    *,
    weight: float,
) -> list["RetrievalResult"]:
    """Re-score reranked candidates by ``score + weight·density`` and re-sort.

    No-op (returns the input order, a shallow copy, untouched) when
    ``weight <= 0`` or the query is not quantitative — zero behaviour change for
    the non-quantitative path.

    Otherwise returns **new** ``RetrievalResult`` objects (the dataclass is
    frozen) via ``dataclasses.replace``, with ``score`` set to the boosted value
    and three audit fields stamped into ``metadata`` for debug/DoD-2 tracing:
    ``numeric_boost_raw_score`` (original reranker logit),
    ``numeric_boost_density``, ``numeric_boost_delta`` (= weight·density).
    The production prompt ignores these fields (``format_context`` reads only
    ``document`` + ``metadata['source']``), so they are debug-only.
    """
    if weight <= 0 or not reranked or not is_quantitative_query(query):
        return list(reranked)

    boosted: list[RetrievalResult] = []
    for result in reranked:
        density = numeric_evidence_density(result.document)
        delta = weight * density
        new_meta = dict(result.metadata)
        new_meta["numeric_boost_raw_score"] = result.score
        new_meta["numeric_boost_density"] = density
        new_meta["numeric_boost_delta"] = delta
        boosted.append(
            dataclasses.replace(
                result,
                score=result.score + delta,
                metadata=new_meta,
            )
        )

    boosted.sort(key=lambda r: r.score, reverse=True)
    return boosted
