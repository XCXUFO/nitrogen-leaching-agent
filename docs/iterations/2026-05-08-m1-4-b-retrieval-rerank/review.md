# Review — M1.4-b Retrieval Rerank

## Conclusion

M1.4-b is complete as an engineering experiment, but it does not meet the
answer-level demo threshold.

The reranker improves retrieval diagnostics and expected-source placement:
q01-q08 reranked top5 hits `7/8`, above the `>= 6/8` retrieval DoD. It also
improves judged relevance and citation support. But `usable_for_demo` remains
`2/10`, the same as M1.4-a, so the answer-level DoD `>= 7/10` fails.

## Verified

| Item | Result |
|---|---|
| Live reranker model test | passed |
| Retrieval debug q01/q07 smoke | passed |
| Retrieval debug q01-q08 reranked run | `20260512-103608` |
| Backend reranker startup | passed |
| Health check | 200 OK |
| Mini eval reranker ON | `20260512-113851`, 10 OK / 0 error |
| Judgement file | `data/eval/mini_eval_20260512-113851_judged.yaml` |

## DoD Review

| DoD | Threshold | Actual | Status |
|---|---:|---:|---|
| `usable_for_demo` | >= 7 / 10 | 2 / 10 | fail |
| refuse `not_hallucinated` | 2 / 2 | 2 / 2 | pass |
| HTTP errors | <= 1 / 10 | 0 / 10 | pass |
| q01-q08 expected source in reranked top5 | >= 6 / 8 | 7 / 8 | pass |
| q07 synthesis diagnostic | >= 2 sources | 3 sources | pass |

## Findings

1. Retrieval got better, but answer extraction did not keep up.

   q05, q06, q07, and q08 show the pattern clearly: the correct source is in
   reranked top5, often rank 1, but the answer still misses required numeric
   points or multi-source synthesis.

2. q04 remains a pure retrieval miss.

   Expected [79] Huang 2024 does not enter reranked top5. The top5 is all [41],
   so the model correctly refuses from the wrong context.

3. q02 is a comparison-target failure.

   The model cites [43] but returns 87% / 74%, while the expected D vs F answer
   is 41% / 60% / 68% / 68%. This is not solved by better source-level recall
   alone.

4. CPU latency is high.

   The full run completed without HTTP errors, but each question took roughly
   25-51 seconds. That is acceptable for offline evaluation, not for demo UX.

## Implementation Note

`backend/scripts/retrieval_debug.py` needed a stability fix: in rerank mode it
now recalls embedding candidates first, releases the embedder, then loads the
reranker. This keeps the offline diagnostic script usable on CPU-only machines.
The production `Retriever` path was smoke-tested separately and left unchanged.

## Risk Boundary

This is an in-sample result on the frozen 10-question M1.4-a set. The result is
useful for comparing reranker ON vs the official baseline, but it must not be
presented as a general quality claim. Generalization remains M1.4-c.

## Recommendation

Do not spend the next iteration only tuning reranker parameters. Keep reranker
as a retrieval component, then move to evidence-focused retrieval and context
packing:

- query rewrite or query expansion for q01/q03/q04 style numeric facts
- source-aware context packing so rank 5 evidence is not lost behind broad
  source matches
- chunk/evidence inspection for WHCNS table and metrics content
- larger 20-50 question eval before any HR demo quality claim
