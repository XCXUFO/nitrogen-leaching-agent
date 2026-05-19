# 农田氮淋失风险决策 AI Agent

> An LLM-based RAG Agent prototype for farmland nitrogen leaching risk decision
> support.
>
> 中国农业大学资源与环境专业硕士毕业设计阶段性工程版本。

## 当前状态

当前仓库已完成一个可交付的基础版本：端到端 RAG 工程链路成立，可以从本地论文知识库检索、重排、调用 LLM 生成回答，并在前端展示 citations。

这个版本适合交付为 **RAG Agent 原型 / Walking Skeleton Plus**，但还不能声称专业问答质量已经达到 demo-ready。M1.4-b mini eval 的 answer-level 结果仍为 `usable_for_demo=2/10`，主要瓶颈在关键证据提取、数值事实定位和多源综合。

## 已完成能力

- 本地论文入库：PDF/text ingest、chunking、稳定 `chunk_id`。
- 向量检索：BGE large zh embedding + Chroma persistent index。
- 二阶段检索：`bge-reranker-v2-m3` reranker 可选启用。
- Chat API：`POST /api/chat` 返回 answer、citations、usage、model。
- 前端 UI：Next.js 单轮 Chat UI，支持 loading、错误态、citation 展示和 health debug。
- 评测闭环：mini eval runner、retrieval debug、judged YAML、iteration report/review。
- 拒答行为：对明显超出知识库的问题能保守拒答，不强行编造。

## 质量结论

| 项 | 结果 |
|---|---|
| 真实索引 | 8 篇 PDF / 1348 chunks |
| M1.4-a baseline | `usable_for_demo=2/10` |
| M1.4-b reranker | retrieval top5 expected-source hit `7/8` |
| M1.4-b answer-level | `usable_for_demo=2/10` |
| Refuse questions | `not_hallucinated=2/2` |
| 当前定位 | 基础链路完成，效果优化待后续迭代 |

Reranker 改善了检索命中和引用支持，但没有解决最终答案质量。后续 RAG 效果优化可在当前骨架上继续做，包括 query rewrite、source-aware context packing、chunk/evidence inspection、表格/数值抽取和更大题集评测。

## 技术栈

| 层 | 技术 |
|---|---|
| LLM | DeepSeek API |
| Embedding | BGE-large-zh-v1.5 |
| Reranker | BAAI/bge-reranker-v2-m3 |
| 向量库 | Chroma |
| 后端 | Python 3.11 + FastAPI |
| 前端 | Next.js 16 + TypeScript + Tailwind 4 + shadcn/ui |
| 评测 | JSONL mini eval + YAML manual judgement |

## 项目结构

```text
.
├── backend/        # FastAPI backend, RAG, LLM client, eval scripts
├── frontend/       # Next.js chat UI
├── data/           # paper/eval metadata committed to repo
├── docs/           # architecture, iteration docs, release notes
└── scripts/        # model download helpers
```

## 快速开始

### Backend

```bash
cd backend
uv sync --extra rag
cp ../.env.example .env
# edit .env: DEEPSEEK_API_KEY, RAG_ENABLED, RAG_CHROMA_DIR
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

RAG 与 reranker 的完整准备流程见 [backend/README.md](backend/README.md)。

### Frontend

```bash
cd frontend
pnpm install
cp .env.local.example .env.local
pnpm dev
```

打开 <http://localhost:3000> 使用单轮 Chat UI。

## 关键文档

- [M1.4-b reranker report](docs/iterations/2026-05-08-m1-4-b-retrieval-rerank/report.md)
- [M1.4-b reranker review](docs/iterations/2026-05-08-m1-4-b-retrieval-rerank/review.md)
- [M1.4-a real index mini eval report](docs/iterations/2026-05-07-m1-4-a-real-index-mini-eval/report.md)
- [M1.3.2 frontend chat UI report](docs/iterations/2026-05-06-m1-3-2-frontend-chat-ui/report.md)
- [Development guide](docs/development.md)

## Demo 边界

可以准备 curated demo questions 展示系统链路和引用能力，但这些问题不能替代 mini eval 结论。当前版本的诚实表述是：

> RAG Agent 基础工程闭环已经完成；reranker 证明能改善检索命中；专业答案质量仍未达到稳定 demo-ready，需要后续 RAG 效果优化。

## License

MIT
