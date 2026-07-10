# Nitrogen Leaching Risk Decision Agent

An LLM-based RAG prototype for farmland nitrogen leaching risk decision support.

This repository contains an end-to-end research prototype that combines local
paper ingestion, vector retrieval, optional reranking, an LLM chat API, and a
minimal web UI with citations.

## Status

The project currently provides a working foundation for RAG-based agronomy QA:

- local corpus ingestion and chunking
- BGE embedding and Chroma vector search
- optional cross-encoder reranking
- FastAPI chat endpoint
- Next.js multi-turn chat UI
- citation display
- retrieval debugging and mini-evaluation utilities

This is a research and engineering prototype. It is not a production decision
support system and should not be used as the sole basis for agricultural,
environmental, or regulatory decisions.

## Capabilities

- **RAG chat**: answer single-turn and recent-history follow-up questions using
  a local paper knowledge base.
- **Citations**: return source snippets with each answer.
- **Retrieval diagnostics**: inspect embedding-only and reranked retrieval
  outputs.
- **Evaluation workflow**: run a frozen mini eval set and record manual
  judgement results.
- **Frontend UI**: keep a running conversation and inspect per-answer citations
  and backend health.

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | DeepSeek API-compatible chat client |
| Embedding | BGE-large-zh-v1.5 |
| Reranker | BAAI/bge-reranker-v2-m3 |
| Vector store | Chroma |
| Backend | Python 3.11 + FastAPI |
| Frontend | Next.js 16 + TypeScript + Tailwind 4 + shadcn/ui |
| Evaluation | JSONL mini eval + YAML manual judgement |

## Repository Layout

```text
.
├── backend/        # FastAPI backend, RAG, LLM client, eval scripts
├── frontend/       # Next.js chat UI
├── data/           # paper/eval metadata committed to repo
├── docs/           # architecture, iteration notes, release notes
└── scripts/        # model download helpers
```

## Quick Start

### Backend

```bash
cd backend
uv sync --extra rag
cp ../.env.example .env
# edit .env: DEEPSEEK_API_KEY, RAG_ENABLED, RAG_CHROMA_DIR
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

See [backend/README.md](backend/README.md) for model download, indexing, RAG,
and reranker setup.

### Frontend

```bash
cd frontend
pnpm install
cp .env.local.example .env.local
pnpm dev
```

Open <http://localhost:3000>.

## Safety and Scope

- The system can make mistakes, miss relevant evidence, or produce incomplete
  answers.
- Generated answers should be reviewed against the cited sources.
- API keys and local model weights are not committed to this repository.
- Runtime artifacts such as Chroma indexes and eval outputs belong under local
  ignored directories like `backend/var/`.

## Documentation

- [Backend setup](backend/README.md)
- [Frontend setup](frontend/README.md)
- [Development guide](docs/development.md)

## License

MIT
