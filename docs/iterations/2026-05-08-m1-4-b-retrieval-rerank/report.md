# M1.4-b Retrieval Rerank Report

## 1. Metadata

| Field | Value |
|---|---|
| Iteration | M1.4-b retrieval rerank |
| Date | 2026-05-12 |
| Baseline | M1.4-a official run `20260507-164315` |
| Experiment | reranker ON run `20260512-113851` |
| Retrieval debug | `backend/var/retrieval/20260512-103608/` |
| Judgement | `data/eval/mini_eval_20260512-113851_judged.yaml` |
| Corpus | 8 PDFs / 1348 chunks |

This is an in-sample comparison against the same frozen 10-question set used by
M1.4-a. It is useful for isolating the reranker effect, but it is not a
generalization claim.

## 2. Setup

- `RAG_RERANKER_ENABLED=true`
- `RAG_RERANKER_MODEL=data/models/bge-reranker-v2-m3`
- `RAG_RERANKER_TOP_K_RECALL=20`
- `RAG_RERANKER_TOP_N=5`
- `run_mini_eval.py` used backend default `k`; no per-request `--k` override.
- Backend model stayed `deepseek-v4-flash`.
- Index, chunking, embedding model, prompt, and 10-question file were unchanged.

## 3. Verification

| Check | Result |
|---|---|
| Reranker model precheck | local 2.2 GB model present |
| Live reranker unit test | `1 passed in 39.91s` |
| `retrieval_debug.py --help` | supports `--rerank`, `--qids`, `--top-n` |
| `retrieval_debug.py` q01/q07 smoke | passed, run `20260511-214059` |
| Backend reranker startup | passed; log showed reranker ON, recall 20, top_k 5 |
| `/api/health` | 200 OK |
| Full mini eval | 10 OK / 0 error |

One implementation follow-up was needed before the full debug run:
`retrieval_debug.py --rerank` was changed to run embedding recall first, release
the embedder model, then load the 2.2 GB reranker. This avoids excessive memory
pressure in the offline diagnostic script. The production `Retriever` path was
not changed by that fix.

## 4. Results

### 4.1 Answer-level

| Metric | M1.4-a baseline | M1.4-b reranker | DoD |
|---|---:|---:|---|
| HTTP errors | 1 / 10 | 0 / 10 | pass |
| `usable_for_demo` | 2 / 10 | 2 / 10 | fail |
| refuse `not_hallucinated` | 2 / 2 | 2 / 2 | pass |
| `relevant` | 4 / 10 | 6 / 10 | improved |
| `cited` | 3 / 10 | 5 / 10 | improved |
| `not_hallucinated` | 7 / 10 | 9 / 10 | improved |

The reranker improves relevance and citation support, but it does not move the
demo usability threshold. The only `usable_for_demo=true` items remain q09 and
q10, the two refusal questions.

### 4.2 Retrieval-level

Reranked top5 expected-source hits for q01-q08:

| QID | Expected source | Result | Notes |
|---|---|---|---|
| q01 | [29] Liang 2017 | pass | Expected source appears at rank 5 |
| q02 | [43] Liang 2020 | pass | Expected source ranks 1, 2, and 4 |
| q03 | [63] Meng 2022 | pass | Expected source appears at rank 5 |
| q04 | [79] Huang 2024 | fail | top5 is all [41] |
| q05 | [26] Liang 2016 | pass | Expected source dominates top5 |
| q06 | [79] Huang 2024 | pass | Expected source rank 1 |
| q07 | synthesis | pass | top5 has 3 unique sources |
| q08 | [26] Liang 2016 | pass | Expected source dominates top5 |

Summary: `7/8`, passing the retrieval-level DoD of `>= 6/8`.

### 4.3 Latency

Full reranker run latencies:

| QID | Latency ms |
|---|---:|
| q01 | 45398 |
| q02 | 51285 |
| q03 | 33147 |
| q04 | 28919 |
| q05 | 25435 |
| q06 | 30850 |
| q07 | 32344 |
| q08 | 28161 |
| q09 | 39191 |
| q10 | 36190 |

CPU reranking is materially slower than the M1.4-a path. It is acceptable for
offline evaluation, but not yet acceptable as a production/demo latency target.

## 5. Case Notes

- q01: [29] enters reranked top5 only at rank 5, while the final citations are
  dominated by [41]/[43]. The model still refuses the Alxa maize question.
- q02: [43] is retrieved strongly, but the model answers the wrong comparison
  target: 87% / 74% instead of the expected 41% / 60% / 68% / 68%.
- q05: [26] is retrieved strongly and the model now gives the five WHCNS
  modules, but it still misses the source-model mapping.
- q06: [79] is retrieved at rank 1 and the model gives a plausible mechanism,
  but it misses 1.7 vs 0.7 mg N/L.
- q07: retrieval has 3 unique sources in top5, but synthesis still collapses to
  one green-manure measure from [60].
- q08: [26] dominates top5, but the answer says numeric metrics are absent and
  misses R2/RMSE/IA/DBW details.

## 6. Conclusion

M1.4-b passes the retrieval-level DoD but fails the answer-level DoD.

The reranker is worth keeping as an infrastructure improvement: it improves
expected-source placement, reduces HTTP/eval failure, and gives better partial
answers for q05/q06. However, it is not enough to reach the HR demo threshold.

Next work should not be another blind reranker tweak. The remaining failure is
evidence extraction and synthesis: key numeric facts are either outside the
final prompt window, buried in imperfect chunks, or not used by the model even
when a relevant source is present. M1.4-c should focus on query rewrite /
evidence-focused retrieval debug, source-aware context packing, and a larger
20-50 question evaluation set.
