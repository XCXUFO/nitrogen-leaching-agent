# 审查文档 — M1.2.1 Embedder 抽象 + ChromaStore 薄封装

> Reviewer 请逐项勾选。本轮是 M1.2 子序列的第 1 个 sub-iteration，
> 引入 RAG 与向量存储的两个抽象点，是 M1.2.2~M1.2.3 的依赖前置。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代代号 | m1-2-1-embedder-chromastore |
| 日期 | 2026-05-05 |
| 起止 commit | (m1-1-llm-client docs 之后) → 待回填 (审查基线) |
| 包含 commit 数 | 预计 4（feat rag + feat storage + test infra + docs）|
| 目标里程碑 | M1.2（RAG 索引，骨架阶段） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 变更范围清单

- [ ] **rag**：`backend/src/rag/base.py` 新增 — `Embedder` ABC（`dim` 契约要求无需触发 model load 即可返回）
- [ ] **rag**：`backend/src/rag/bge.py` 新增 — `BGEEmbedder` 实现（lazy-load）
- [ ] **rag**：`backend/src/rag/__init__.py` 公开导出
- [ ] **storage**：`backend/src/storage/chroma_store.py` 新增 — `ChromaStore` 薄封装（PersistentClient + 4 方法 + 1 属性）
- [ ] **storage**：`backend/src/storage/__init__.py` 公开导出
- [ ] **tests**：`backend/tests/test_embedder.py` 新增 — 契约测（ABC + lazy-load + dim + Fake 实现）
- [ ] **tests**：`backend/tests/test_embedder_live.py` 新增 — `RUN_LIVE_EMBED=1` 守门的实调 smoke
- [ ] **tests**：`backend/tests/test_chroma_store.py` 新增 — 端到端 add/query/count（tmp_path）
- [x] **deps**：`backend/pyproject.toml` + `backend/uv.lock` — 新增 `rag` extra，按需安装 `sentence-transformers>=3.0,<4.0` + `chromadb>=0.5,<0.6`
- [ ] **docs(iteration)**：本目录 `spec.md` + `review.md`
- [ ] 未触及：前端、`agent/` / `simulator/` / `api/` / `llm/` / `utils/`

## 3 commit 规范清单

预期 commit（待回填实际 SHA）：

- [ ] `feat(rag): add Embedder ABC with lazy-loaded BGEEmbedder`
- [ ] `feat(storage): add ChromaStore thin wrapper over PersistentClient`
- [ ] `test(rag,storage): add embedder and chroma_store contract tests`
- [ ] `docs(iteration): add 2026-05-05 m1-2-1 embedder/chromastore spec and review`

- [ ] 全部符合 `<type>(<scope>): <subject>`
- [ ] 单 commit 单意图：rag 与 storage 分离，避免一个 commit 跨两个模块
- [ ] 测试与依赖随 feat 同 commit（依赖独立装不上、测试无法独立跑）

## 4 验证证据清单

| 项 | 命令 | 期望 | 实际 | 通过 |
|---|---|---|---|---|
| 依赖安装 | `cd backend && env UV_CACHE_DIR=/tmp/uv-cache uv sync` | 退出码 0；默认路径不安装 `rag` extra | `Resolved 126 packages`; `Checked 35 packages` | [x] |
| 后端单测 | `cd backend && uv run pytest` | 全套 < 5s（不下载真实模型）| `18 passed, 6 skipped in 1.66s` | [x] |
| Embedder lazy-load | `python -c "from src.rag import BGEEmbedder; print('lazy ok' if BGEEmbedder()._model is None else 'EAGER LOAD BUG')"` | 输出 `lazy ok` | `lazy ok` | [x] |
| ABC 强制 | `Embedder()` / `ChromaStore()` 实例化（缺参） | `TypeError` | `Embedder TypeError, ChromaStore TypeError` | [x] |
| ChromaStore 端到端 smoke | spec §5 步骤 5 的 tempfile 脚本 | 输出 `count: 1` | 默认未装 `rag` extra；由 `tests/test_chroma_store.py` skip 守门 | [-] |
| 实调 BGE（守门）| `cd backend && RUN_LIVE_EMBED=1 uv run pytest tests/test_embedder_live.py` | 1 passed；输出维度 1024 的向量 | 默认跳过 | [-] |

## 5 依赖变更清单

### Python（默认 0 个直接依赖新增；`rag` extra 新增 2 个可选依赖）

- [x] `sentence-transformers>=3.0,<4.0`（`rag` extra）
- [x] `chromadb>=0.5,<0.6`（`rag` extra）
- [ ] 间接：torch / numpy / onnxruntime / tokenizers 等（仅 `uv sync --extra rag` 时安装，未在默认路径回填完整清单）
- [ ] 锁文件 `backend/uv.lock` 已更新
- [x] 体积影响：默认安装路径无新增大包；`uv sync --extra rag` 仍可能膨胀 ~1.5 GB（torch CPU 版主要贡献）— 已在 spec §8 记录

### Node

- [ ] 无变更

## 6 兼容性 / 破坏性变更

- [ ] 无公开 API 改动（不动 `/api/*`）
- [ ] 无数据库 schema 改动（SQLite 不动）
- [ ] **新增 chroma 持久化目录**：首次运行后 `backend/data/chroma/` 出现 sqlite 文件；已在 `.gitignore`（继承 walking-skeleton 的 data/ 排除规则，需 push 前确认）
- [x] **运行行为变化**：构造 `BGEEmbedder` 不触发模型加载；首次调 `embed_*` 才加载（~5s 冷启动延迟）

## 7 安全清单

- [x] 无新增外发请求；`BGEEmbedder` 只在 `RUN_LIVE_EMBED=1` 时主动下载
- [x] chromadb / sentence-transformers 来自官方 PyPI 发布
- [ ] `git log -p | grep -iE "sk-[a-zA-Z0-9]{20,}"` 应无命中
- [ ] CORS 配置未变

## 8 文档清单

- [ ] 本审查文档与说明文档（`spec.md`）在同目录下
- [ ] `spec.md` 已沉淀关键设计判断（分层 / lazy-load / ABC / 拆 documents/query / store 不持有 embedder / 持久化模式 / dim 属性）
- [ ] M0 遗留无相关项

## 9 风险与回滚

- [ ] **风险**：chromadb 主版本升级 breaking — 锁定 `>=0.5,<0.6`
- [ ] **风险**：sentence-transformers 与 torch 体量大；CI 装包慢
- [ ] **风险**：HuggingFace 下载需要梯子（`test_embedder_live.py` 才触发）
- [ ] **风险**：PersistentClient 进程独占（M1.3 多 worker 时再处理）
- [ ] **风险**：lazy-load 隐藏首次延迟（M1.3 集成时 lifespan 兜底）
- [ ] **风险**：M1.3 若直接在 async 路由里调用 sync Retriever，会阻塞 event loop；需经 `asyncio.to_thread(...)`
- [ ] **回滚**：4 个 commit 互相独立，可单独 revert；deps commit revert 后需手动 `uv sync` 清理 .venv

## 10 待办（不阻塞合并）

- [ ] M1.2.2 之前确认 `.gitignore` 已排除 `backend/data/chroma/` 与 HuggingFace cache（`~/.cache/huggingface/`）
- [ ] M1.2.3 引入 `tests/test_rag_live.py`，补父 milestone 级集成 live 路径（embedder + retriever 一起验证）
- [ ] M1.3 之前评估是否在 lifespan 期主动 `_ensure_loaded()` 以避免在线 chat 首次延迟

## 11 审查结论

- [ ] **通过**（reviewer 签名 + 日期：__________ / __________）
- [ ] **驳回**，原因：__________
- [ ] **有条件通过**，需在 push 后补做：__________

---

**机审字段**（push 前回填）：

```yaml
iteration: 2026-05-05-m1-2-1-embedder-chromastore
commits_from: TBD
commits_to: TBD
commit_count: 4
files_changed: TBD
lines_added: TBD
lines_removed: TBD
tests_passed: 18
tests_failed: 0
breaking: false
new_runtime_deps_python: 0
new_runtime_deps_node: 0
new_dev_deps_python: 0
secrets_in_repo: false
parent_iteration: 2026-05-04-m1-1-llm-client
```
