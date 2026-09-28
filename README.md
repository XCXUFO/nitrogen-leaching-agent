# Nitrogen Leaching Risk Decision Agent

An agricultural model learning and usage assistant, built on a literature RAG
prototype. WHCNS is the first model targeted for substantive support.

This repository contains an end-to-end research prototype that combines local
paper ingestion, vector retrieval, optional reranking, an LLM chat API, and a
minimal web UI with citations.

## Status

Implemented baseline: **M1.6 agronomy RAG**. Next milestone: **M2.0 model
understanding and usage assistance** (in progress: material intake and a local
WHCNS result reader are available; guided UI and review workflows are pending).

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

## Next milestone: M2.0

Help beginners understand a model's purpose, assess prerequisites, prepare
materials, and interpret one real case with traceable evidence. The assistant
must work independently of the original platform; the existing LLM API remains
an external dependency, so this does not mean fully offline operation.

The first release focuses on three tasks: **understand WHCNS**, **prepare to use
it**, and **interpret case results**. It includes reviewed model documentation,
guided task state, clearer citations, one file-checking or result-reading tool,
and a small reviewer interface. Online WHCNS execution is an optional later
extension, not a release prerequisite.

See the [M2.0 scope and acceptance plan](docs/iterations/2026-09-26-m2-0-model-assistant/spec.md).
The existing 24-question M1.6 set is a regression baseline after targeted tuning;
its 21/24 demo-usable result is an initial self-review, not held-out accuracy.

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
- **Local WHCNS result reader**: inspect the supplied nitrogen/water balance
  spreadsheets with file hashes, unit checks and cell-level traceability.
  This is a CLI tool; chat integration and model execution are not implemented.
  See [usage](backend/src/model_tools/README.md).

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
- [Stage check report / 阶段性检查说明](docs/STAGE_CHECK_REPORT.md)

## License

MIT
