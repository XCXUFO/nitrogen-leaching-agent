# Agricultural Model Assistant

An agricultural model assistant with one conversation window, built on a
literature RAG prototype. WHCNS is the first model targeted for substantive support.

This repository contains an end-to-end research prototype that combines local
paper ingestion, vector retrieval, optional reranking, an LLM chat API, and a
minimal web UI with citations.

## Status

Implemented baseline: **M1.6 agronomy RAG**. **M2.0 unified conversation** is
in progress: WHCNS output upload, deterministic extrema calculation, clarification
and cell-level evidence are available in the existing chat. Manual retrieval is
still pending.

The first **Agent Harness** increment adds a typed skill registry, conservative
intent routing, bounded task state, evidence IDs and persistent run traces.
Knowledge questions can be asked with an attachment still present. File follow-ups
can inherit a successfully queried metric within the same active conversation.
Uploads now defer domain validation until analysis. Supported extrema + mechanism
questions combine computed file facts with cited general mechanisms; failed steps
leave a clearly marked partial answer. An authenticated `/evaluation` workspace
now opens directly on saved conversations: approve an expected answer, mark a
specific turn for correction, update materials or prompts, and confirm a new
answer. One human reviewer is sufficient; collaborators can add a second opinion.
Materials and prompt iteration stay in the main navigation; legacy evaluation
features remain available under extra tools and history. See the
[lightweight review guide](docs/iterations/2026-10-18-lightweight-review/README.md).
Chat renders Markdown with navigable citations and supports attachment drag-and-drop,
upload progress and request retries.
See the [implementation scope](docs/iterations/2026-09-29-agent-harness/spec.md).

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

Users ask questions or provide files in one conversation. The backend retrieves
knowledge, calculates file results, or asks for missing information. Professional
explanations are provided as needed; there are no separate learning/task entrances
or systematic teaching flow. Professional review belongs to development validation.

WHCNS is the first supported model. Core workflows operate independently of the
original platform. Literature QA still needs the configured RAG and DeepSeek API;
file calculations work without them. Online WHCNS execution, automatic calibration
and fertilizer decisions are outside the current delivery scope.

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
  and file evidence.
- **Local WHCNS result reader**: inspect the supplied nitrogen/water balance
  spreadsheets with file hashes, unit checks and cell-level traceability.
  Available through the CLI and the chat attachment control; WHCNS is not executed.
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
uv sync --extra rag --extra model-tools
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

Open <http://localhost:3000>. Attach `Nbal_out.xls` and ask
“硝态氮淋失最大值及对应日序”. The response includes value, unit, model day,
value/day cells, data range and file hash. Nitrogen and water balance schemas are
validated by content. One explicit field and whole-table min/max are supported;
ambiguous fields, time subsets and seasonal totals require clarification.

Attachments are limited to 10 MiB and expire after 30 minutes. The prototype keeps
parsed content in process memory (maximum 32 files, single backend worker);
submitted originals are retained in the run database for authenticated review previews;
unsubmitted originals are deleted when their temporary file lease is released or expires. Files attach to one message and
leave the input area immediately after sending. Upload the file again to use it
in a later question; retrying or regenerating a message reuses its original valid
attachments. Refresh/restart requires re-upload for new file analysis.
Model version, calendar origin, input/output pairing and professional review remain
unconfirmed. Reading an output is not a reproduced simulation case.

Run traces are stored in `backend/var/agent/runs.sqlite3` by default. Configure
`AGENT_TRACE_DB` and set `AGENT_BUILD_VERSION` to the evaluated build/snapshot ID.
Signed-in users can restore their own saved conversations and continue chatting
after a reload or login. Guest pages retain recovery information for pending
requests within the recovery window. The workbench groups traces and human reviews
at `/evaluation/runs`; reviewing a conversation does not create a scored evaluation
Execution. Trace and review APIs require evaluator access.

## Safety and Scope

- The system can make mistakes, miss relevant evidence, or produce incomplete
  answers.
- Generated answers should be reviewed against the cited sources.
- API keys and local model weights are not committed to this repository.
- Runtime artifacts such as Chroma indexes and eval outputs belong under local
  ignored directories like `backend/var/`.

## Documentation

Public resume demo: `/` offers knowledge and case questions plus file upload; `/showcase` exposes
an explicitly selected read-only evidence snapshot plus isolated synthetic workflows
for literature AI processing, cases, shared tags and starred questions. Workflow edits
stay in page memory and reset on refresh. `/evaluation` remains
the authenticated management workspace. See [public demo setup](docs/public-demo.md)
for visitor isolation, request budgets, deployment settings and evidence scope.

- [Backend setup](backend/README.md)
- [Frontend setup](frontend/README.md)
- [Development guide](docs/development.md)
- [2026-11-13 封版审查与验证](docs/releases/2026-11-13-preseal-review.md)
- [2026-11-14 GitHub 后端 CI 修复](docs/releases/2026-11-14-backend-ci-repair.md)
- [1017 PRD 剩余开发交付与验收](docs/iterations/2026-10-17-prd-completion/README.md)
- [工具能力盘点归档：Skill、MCP 与后续优化候选（2026-10-16）](docs/iterations/2026-10-16-tool-capability-inventory/README.md)
- [工作台使用说明与文档导航](docs/iterations/2026-09-29-agent-harness/evaluation-guide.md)
- [资料管理使用说明：文献、AI 打标与结论、案例、星标问题](docs/iterations/2026-09-29-agent-harness/workbench-materials-guide.md)
- [工作台风险审查与修复验收（2026-10-16–17）](docs/iterations/2026-10-16-workday-risk-review/review.md)
- [Stage check report / 阶段性检查说明](docs/STAGE_CHECK_REPORT.md)

## License

MIT
