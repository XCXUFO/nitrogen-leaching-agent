# Review — M1.3.2 前端最小 Chat UI

> 注：本审查文档在 M1.4-a 之后回填整理。文中的 sample 4 chunks、
> `index_papers.py` 未读取 `settings.embedding_model` 等观察，是 M1.3.2
> 当时的前端 smoke 环境状态；M1.4-a 后续已修复 indexer 同源问题，并切换到
> 8 篇真实 PDF / 1348 chunks 的真实索引基线。

## 结论

M1.3.2 可以判定完成。

本轮目标是把 Walking Skeleton 前端从 health 探测页改造成单轮 Chat UI，并消费 M1.3.1 的 `POST /api/chat`。当前前端 `http://localhost:3000` 已由用户人工验证无明显问题；后端 health、OpenAPI、chat 成功路径与错误路径均有实测证据。

## 已验证

### 前端静态检查

| 项 | 结果 |
|---|---|
| `pnpm lint` | 通过，0 error |
| `pnpm build` | 通过；Compiled 4.2s，TypeScript 3.6s，4 个 static page |
| 新增 npm 依赖 | 0 |
| shadcn 组件增量 | 0，仅复用已有 `button.tsx` |

说明：第一次在 sandbox 内跑 `pnpm build` 时，Turbopack 因本地端口绑定受限报错；在沙箱外按同一命令复跑通过，属于执行环境限制，不是代码错误。

### 后端 / RAG 前置

| 项 | 结果 |
|---|---|
| `backend/.env` | 已配置 `RAG_ENABLED=true`、`RAG_CHROMA_DIR=./var/chroma` |
| 本地 BGE 模型 | 已存在于 `backend/data/models/bge-large-zh-v1.5/` |
| Chroma collection | `papers` |
| Chroma embeddings | 4 |
| 后端启动 | `http://127.0.0.1:8000`，RAG enabled |

### HTTP smoke

| 项 | 结果 |
|---|---|
| `GET /api/health` | 200，`{"status":"ok","service":"nitrogen-leaching-agent-backend","version":"0.1.0"}` |
| `GET /` | 404 `{"detail":"Not Found"}`，符合预期；后端未定义根路由 |
| `GET /api/chat` | 405 `Method Not Allowed`，符合预期；chat 只接受 POST |
| `GET /openapi.json` | 200，能看到 `/api/health` 与 `POST /api/chat` schema |
| `POST /api/chat` | 200；返回 answer、4 条 citations、usage、model=`deepseek-v4-flash` |
| `POST /api/chat` 上游异常 | 502 `llm_unreachable` 可复现；前端错误态覆盖该路径 |

### 浏览器 smoke

| 项 | 结果 |
|---|---|
| 打开 `http://localhost:3000` | 用户人工验证可用 |
| 前端提交 chat | 用户人工验证无明显问题 |
| citation 展示 | 后端返回 4 条 citations，前端已接入 `CitationList` |
| 底部 health 调试入口 | 后端 health 已通过；前端保留折叠入口 |
| `/docs` | 返回 200，但浏览器显示空白；不阻塞本轮，`/openapi.json` 可用 |

## 已知问题

1. `scripts/index_papers.py` 没有读取 `settings.embedding_model`

   当前 `backend/src/config.py` 默认 `embedding_model = "data/models/bge-large-zh-v1.5"`，本地模型也已完整存在。但 `backend/scripts/index_papers.py` 直接 `BGEEmbedder()`，会走类默认值 `BAAI/bge-large-zh-v1.5`，导致重新建索引时尝试访问 Hugging Face 远端。

   本次为不改后端代码，使用临时命令显式传入本地模型路径完成索引。后续建议小修：indexer 使用 `BGEEmbedder(model_id=settings.embedding_model)`。

2. DeepSeek 上游偶发 `llm_unreachable`

   实测出现过 `Request timed out.` 与 `Connection error.`，同一后端随后也能成功返回 200。判断为后端到 DeepSeek 的网络/代理波动，不是前端实现问题。

   本轮前端已经把该错误码映射为用户可读错误条；后续可单独处理后端固定代理、`NO_PROXY` 与超时策略。

3. `/docs` 页面空白

   `/docs` 返回 200，但浏览器显示空白；`/openapi.json` 正常。推测是 Swagger UI 相关静态资源或浏览器/代理行为问题。本轮不依赖 `/docs`，不阻塞。

4. Chroma 当前只有 sample 数据

   当前 collection 内为 `sample.txt` 生成的 4 个 chunks，足够完成 M1.3.2 smoke。真实论文全集索引仍属于后续数据准备/评测工作。

## 完成判断

本轮成功完成：

- 前端从 health 探测页改为最小单轮 Chat UI
- `POST /api/chat` 成功路径可用
- citations 能从后端返回并由前端展示
- health 调试入口保留
- 网络/LLM 错误能以明确错误态暴露
- 不新增前端运行时依赖
- lint/build 通过

因此，M1.3.2 可以关闭。建议在进入 M1.4 前补一个小修：让 `scripts/index_papers.py` 读取 `settings.embedding_model`，避免后续重建索引再次误走远端下载。
