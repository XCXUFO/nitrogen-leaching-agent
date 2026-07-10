# Spec — M1.6 Demo Content + Multi-turn

## 1. Goal

M1.6 turns the prototype into a more mature demo by expanding the usable paper
corpus and enabling natural follow-up questions. This iteration is about demo
coverage and interaction quality, not another in-sample RAG tuning pass.

## 2. Scope

Included:

- Batch paper indexing workflow for already prepared PDFs.
- Minimal multi-turn chat: frontend keeps the conversation, backend accepts
  recent history, retrieval query includes short dialogue context, and answers
  still cite only the current retrieval evidence.
- Documentation for the M1.6 demo workflow and evaluation follow-up.

Excluded:

- New reranker model, embedding model, or numeric boost tuning.
- Persistent server-side chat memory.
- Streaming.
- Full 20-30 question external evaluation judgement.

## 3. Design

### 3.1 Content

Prepared PDFs live under `data/papers/` locally and remain gitignored. The
indexer supports recursive directory scanning:

```bash
cd backend
uv run python scripts/index_papers.py \
  --dir ../data/papers \
  --persist-dir var/chroma \
  --collection papers \
  --repo-root ..
```

For a clean demo corpus, remove the old Chroma directory before rebuilding:

```bash
rm -rf backend/var/chroma
```

After indexing, update `data/papers/sources.md` with the full local corpus
inventory and add 20-30 external eval questions before claiming quality
improvement.

### 3.2 Multi-turn

The frontend sends `history` as the recent user/assistant turns. The backend:

1. builds a retrieval query from recent dialogue + current query;
2. retrieves and reranks using the existing RAG defaults;
3. builds the answer prompt with current evidence plus recent dialogue;
4. requires answer facts to be grounded in current retrieved evidence.

This keeps demo follow-ups useful without introducing persistent memory or
allowing old assistant answers to become uncited evidence.

## 4. Acceptance

- Existing single-turn `/api/chat` clients still work without `history`.
- Multi-turn request body accepts up to 12 history messages.
- Frontend displays a conversation instead of replacing the previous turn.
- Existing non-live backend tests pass.
- Frontend lint/build pass.

## 5. Follow-up

After the prepared papers are indexed, create an M1.6 eval set with:

- factual questions from newly added papers;
- synthesis questions that require at least two sources;
- citation-check questions for table/numeric facts;
- refuse questions near the expanded corpus boundary.

Only after that run should RAG optimization resume, based on observed failure
categories.
