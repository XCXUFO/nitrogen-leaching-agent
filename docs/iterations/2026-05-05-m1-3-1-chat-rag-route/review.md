# 审查文档 — M1.3.1 后端 RAG Chat API

> 本轮把 M1.1 的 `LLMClient` 与 M1.2 的 `Retriever` 接成单轮
> `POST /api/chat`。默认 `RAG_ENABLED=false` 时服务可启动，chat 返回 503。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代代号 | m1-3-1-chat-rag-route |
| 日期 | 2026-05-05 |
| 起止 commit | 待回填 |
| 包含 commit 数 | 预计 3（docs + backend feat + tests/docs follow-up） |
| 目标里程碑 | M1.3（后端 RAG Chat API） |
| 责任 LLM | GPT-5 |
| 责任人 | XCXUFO |

## 2 变更范围清单

- [x] **api**：`backend/src/api/chat.py` 新增 — `POST /api/chat`，翻译未配置 RAG、检索失败、LLM 上游错误。
- [x] **api**：`backend/src/api/chat_schema.py` 新增 — `ChatRequest` / `ChatResponse`，`query` strip 后判空。
- [x] **agent**：`backend/src/agent/chat_service.py` 新增 — `ChatService` 编排 retrieve → prompt → LLM，sync retriever 走 `asyncio.to_thread(...)`。
- [x] **agent**：`backend/src/agent/prompt.py` 新增 — 带引用编号的 system/user prompt builder。
- [x] **backend**：`backend/src/main.py` lifespan 扩展 — 构造 `DeepSeekClient`，按 `RAG_ENABLED` 可选构造真实 RAG 链路，失败软降级为 503。
- [x] **config**：`backend/src/config.py` 新增 RAG/chat 配置字段与相对路径规整。
- [x] **docs**：`.env.example` / `backend/README.md` / `backend/src/api/README.md` 更新启用步骤。
- [x] **tests**：新增 schema / prompt / service / route / live smoke 测试；扩展 config 回归。
- [x] 未触及：前端、持久化 schema、M1.2 RAG 核心实现。

## 3 验证证据清单

| 项 | 命令 | 期望 | 实际 | 通过 |
|---|---|---|---|---|
| M1.3.1 单元测试 | `cd backend && uv run pytest tests/test_chat_schema.py tests/test_chat_prompt.py tests/test_chat_service.py tests/test_chat_route.py -q` | 全绿 | `32 passed in 1.13s` | [x] |
| 后端全套默认测试 | `cd backend && uv run pytest -q` | 全绿，live 默认跳过 | `84 passed, 20 skipped in 1.75s` | [x] |
| 默认 RAG 禁用路径 | route test 注入 `chat_service=None` | 503 + `rag_not_configured` | 命中 | [x] |
| 查询失败路径 | Fake service 抛 `RAGQueryError` | 503 + `rag_query_failed` | 命中 | [x] |
| LLM 连接失败路径 | Fake service 抛 `APIConnectionError` | 502 + `llm_unreachable` | 命中 | [x] |
| sync retriever 隔离 | service test 记录 thread id | retrieve 不在事件循环主线程 | 命中 | [x] |
| live RAG chat | `RUN_LIVE_RAG_CHAT=1 uv run pytest tests/test_chat_live.py -q` | 手动守门 | 默认跳过，未实测 | [-] |

## 4 关键审查点

- [x] 默认 `RAG_ENABLED=false`，未装 `rag` extra 或无本地 Chroma 索引时应用仍可启动。
- [x] `/api/health` 不依赖 RAG 初始化；`/api/chat` 在未配置时返回稳定 503。
- [x] route 层不直接拼 prompt 或访问 Chroma；业务编排在 `agent.ChatService`。
- [x] `agent` 不依赖 `api`；`Citation` 定义在 `agent.chat_service`，由 `api.chat_schema` 复用。
- [x] 默认测试不触 DeepSeek、不下载 BGE、不要求 chromadb 已安装。
- [x] `query` 空白字符串被拒绝；`k` 限制在 1 到 20。

## 5 偏离与取舍

- [x] **新增 `RAGQueryError`**：spec 初稿只写 route 翻译 chromadb 异常；实现中由 service 包装 retriever 异常，route 只认业务错误类型，测试更稳定。
- [x] **代码行数超计划**：非测试后端代码约 317 行，超过 spec 的 250 行软目标；主要来自清晰拆分 route/schema/service/prompt/lifespan/config。暂不压缩，避免把职责揉回 route。
- [x] **默认启动时间未单独计时**：全套测试能证明默认路径不加载 RAG，但未跑 uvicorn 计时。
- [x] **live smoke 未执行**：需要真实 DeepSeek key、rag extra 与 BGE 权重下载，默认跳过。

## 6 风险与回滚

- [x] **风险**：RAG 初始化失败被软降级，配置错误可能只在日志里可见。缓解：503 detail 指向 `RAG_ENABLED` / `RAG_CHROMA_DIR` / 离线索引。
- [x] **风险**：首次真实 chat 可能触发 BGE 冷加载。缓解：M1.3.2 前端只展示 loading；M2 再评估 lifespan 预加载。
- [x] **风险**：LLM 是否严格使用 `[N]` 引用未校验。缓解：M1.4 评测处理。
- [x] **回滚**：可 revert 本迭代后端 feat commit；M1.2 RAG 原语不受影响。

## 7 审查结论

- [x] **通过**（机审：GPT-5 / 2026-05-05）
- [ ] **驳回**，原因：__________
- [ ] **有条件通过**，需在 push 后补做：__________

---

**机审字段**：

```yaml
iteration: 2026-05-05-m1-3-1-chat-rag-route
commits_from: 6904bc9
commits_to: TBD
commit_count: TBD
files_changed: TBD
lines_added: TBD
lines_removed: TBD
tests_passed: 84
tests_failed: 0
tests_skipped: 20
breaking: false
new_runtime_deps_python: 0
new_runtime_deps_node: 0
secrets_in_repo: false
parent_iteration: 2026-05-05-m1-2-3-ingest-index-retriever
```
