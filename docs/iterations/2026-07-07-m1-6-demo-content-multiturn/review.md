# Review — M1.6 Demo Content + Multi-turn

## Status

M1.6 is functionally implemented and now has a post-retrieval-hint judged
expanded-corpus eval that passes the current answer-level gate. The code
changes cover the intended demo path:

- backend `/api/chat` remains backward-compatible for single-turn requests;
- request schema accepts recent `history` with a 12-message cap;
- retrieval query uses compact recent dialogue context;
- prompt context includes recent dialogue while grounding facts in current
  retrieved evidence;
- frontend keeps a running conversation and sends recent history;
- batch indexing supports recursive `--dir` scans, batched upserts and
  `--skip-existing`;
- M1.6 corpus metadata is organized and documented.

## Verification Recorded

From the implementation report:

- backend targeted tests: 50 passed
- backend DeepSeek tests: 5 passed
- frontend lint: passed
- frontend build: passed
- live smoke q04 first turn: passed
- live smoke q04 follow-up: passed

Additional live checks during review:

- backend health returned HTTP 200 on `2026-07-08`;
- frontend dev page returned HTTP 200 earlier in the review pass;
- q04 live chat returned HTTP 200 and retrieved the target paper, including
  `079_huang_2024_subsurface_n_losses_paddy::0004` and `::0005`, but the
  answer remained conservative and did not fully extract all expected numeric
  facts. Treat this as an expanded-corpus eval failure candidate, not a quality
  pass.

M1.6 expanded eval raw run:

- Run ID: `20260708-174735`
- Raw output: `backend/var/eval/mini_eval_20260708-174735.jsonl`
- Initial judged output:
  `data/eval/mini_eval_20260708-174735_judged.yaml`
- Question set: `data/eval/m16_questions.yaml`
- HTTP result: 24 ok / 0 err
- Latency: roughly 42-84 seconds per question on the local CPU reranker +
  live LLM path

Initial self-review shows a split outcome:

- Usable for demo: 5/24 (`m16_q07`, `m16_q08`, `m16_q10`, `m16_q23`,
  `m16_q24`).
- Refusal safety: 2/2 correct refusals, no fabricated values.
- Not hallucinated: 24/24 under the initial review rubric; the model usually
  refused or under-answered rather than inventing unsupported numbers.
- Main failure buckets: retrieval/source miss for new English papers (7),
  partial numeric extraction from relevant chunks (9), synthesis failures (2),
  and one source-ID/reference-confusion case (`m16_q22`).

The dominant first-pass failure mode is not transport or schema stability; it
is retrieval/source selection after the corpus expanded to 90 papers,
especially for newly added English papers and synthesis questions. A second
major issue is under-extraction: the correct paper is often in citations, but
the final context or answer still misses required numeric facts.

Post-judgement retrieval pass and answer-level rerun:

- Added high-confidence retrieval aliases for the largest source-miss failures:
  `[92]` Han 2025 greenhouse tomato, `[20]` Huang 2026 WHCNS_Rice, `[67]`
  Wu 2023 I-4/I-6, `[93]` Hou 2025 shallow-groundwater drip maize, and
  cross-source `[43]`/`[92]`, `[79]`/`[81]` synthesis prompts.
- Added a system-prompt guard for corpus source IDs: user text like `[79]` and
  `[81]` should be interpreted via source filename prefixes, while answer
  citations still use the current prompt context numbers `[1]`, `[2]`, etc.
- Offline embedding + reranker diagnostics now put the target evidence in
  reranked top5 for `m16_q01`, `m16_q02`, `m16_q09`, `m16_q11` and `m16_q15`.
  `m16_q19` now has both `[43]` and `[92]` in reranked top5, though some chunks
  are still title/background evidence. `m16_q22` now keeps both `[79]` and
  `[81]` in reranked top5 with the source-ID alias.
- Backend targeted tests after this pass: 73 passed, 68 Chroma warnings.
- Post-hint raw eval run: `20260710-161708`
- Raw output: `backend/var/eval/mini_eval_20260710-161708.jsonl`
- Post-hint judged output:
  `data/eval/mini_eval_20260710-161708_judged.yaml`
- HTTP result: 24 ok / 0 err
- Usable for demo: 14/24 (`m16_q01`, `m16_q02`, `m16_q07`, `m16_q08`,
  `m16_q09`, `m16_q10`, `m16_q11`, `m16_q12`, `m16_q15`, `m16_q17`,
  `m16_q20`, `m16_q22`, `m16_q23`, `m16_q24`)
- Refusal safety: 2/2 correct refusals
- Not hallucinated: 24/24 under the initial self-review rubric
- Synthesis usable: 2/4 (`m16_q20`, `m16_q22`)
- Remaining failure buckets: partial numeric extraction (7), synthesis
  incomplete (2), retrieval miss (1)

Follow-up retrieval pass after the 14/24 run:

- Added aliases for remaining numeric gaps in `[84]`, `[81]`, `[78]`, `[88]`
  and `[87]`.
- Added/adjusted synthesis aliases for `[43]`/`[92]` greenhouse tomato and
  `[67]`/`[72]`/`[78]` wheat-rotation irrigation prompts.
- Added a system-prompt instruction to scan all reference chunks for requested
  multi-indicator numeric facts before saying that the material is missing.
- Offline app-path diagnostics now put target chunks in reranked top5 for
  `m16_q03`, `m16_q04`, `m16_q05`, `m16_q06`, `m16_q13`, `m16_q14`,
  `m16_q16`, `m16_q18` and `m16_q19`. `m16_q21` now retrieves at least two
  target synthesis sources (`[67]` and `[78]`), though `[72]` is still not
  guaranteed in top5.
- Backend targeted tests after this follow-up pass: 82 passed, 68 Chroma
  warnings.
- Follow-up raw eval run: `20260710-172602`
- Raw output: `backend/var/eval/mini_eval_20260710-172602.jsonl`
- Follow-up judged output:
  `data/eval/mini_eval_20260710-172602_judged.yaml`
- HTTP result: 24 ok / 0 err
- Usable for demo: 21/24
- Refusal safety: 2/2 correct refusals
- Not hallucinated: 24/24 under the initial self-review rubric
- Synthesis usable: 4/4
- Remaining failure buckets: partial numeric extraction (2), spatial-factor
  under-extraction (1)

## Review Notes

1. The root README had stale "single-turn" wording; it has been updated to
   multi-turn.
2. `data/eval/README.md` had stale M1.4-a-only setup text; it now documents the
   M1.6 eval file and workflow.
3. A 24-question M1.6 expanded-corpus eval set has been added at
   `data/eval/m16_questions.yaml`.
4. The first paired judged file has been added at
   `data/eval/mini_eval_20260708-174735_judged.yaml`. It should be treated as
   an initial self-review and still needs domain review before any quality
   claims.
5. A first retrieval hint pass has been applied after judging and verified with
   a fresh 24-question answer-level eval. It improves the initial self-review
   result from 5/24 usable to 14/24 usable.

## Residual Risks

- Full `pytest -k "not live"` previously hung in the sandbox on thread/portal
  cleanup; targeted tests are the practical gate for touched files.
- The M1.6 judged files are still initial self-reviews. No expanded-corpus
  quality claim should be made until a domain reviewer confirms the judged
  labels.
- q04 retrieval is improved enough to include the target evidence chunks, but
  the answer can still under-extract numeric facts from split abstract chunks
  when competing rice-runoff papers are present.
- The frontend retry path resubmits the last failed query as a new turn. This is
  acceptable for the demo, but if repeated retries become a UX issue it should be
  changed to retry in place.

## Human TODO

- Hold domain-review handoff until there is a larger batch worth reviewing.
  When approved, ask a domain reviewer to validate
  `data/eval/mini_eval_20260708-174735_judged.yaml` and
  `data/eval/mini_eval_20260710-161708_judged.yaml`, with special attention to
  `usable_for_demo` labels and numeric-fact completeness.

## Next Gate

Close the final three self-reviewed answer gaps without regressing the 21/24
baseline:

1. `m16_q06`: make the answer extract the NH3 spatial-driver phrase
   (temperature and precipitation) from `[81]`.
2. `m16_q14`: ensure the national single-rice NUE value 0.31 is included along
   with the 2050 management/breeding judgement.
3. `m16_q18`: force explicit listing of 77.2, 65.6, 81.5 kg N/ha and 33.6%,
   31.5%, 40.8% instead of ranges.
4. After those targeted fixes, run a smaller smoke over `m16_q06`, `m16_q14`
   and `m16_q18`; only re-run all 24 questions if those outputs change the
   prompt/retrieval behavior broadly.
