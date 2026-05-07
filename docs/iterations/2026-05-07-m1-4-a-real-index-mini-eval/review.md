# 审查文档 — M1.4-a 真实索引 + Mini Eval

> 本轮把 sample.txt 演示索引切换到 8 篇真实 PDF，落 HTTP runner、10 题人工
> 评分表与首轮 mini eval。**DoD 未达 7/10 demo 阈值（usable_for_demo
> 2/10）**，但建立了可复现的真实语料基线，并清晰定位瓶颈在 retrieval
> 命中率而非 LLM 胡编。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代代号 | m1-4-a-real-index-mini-eval |
| 日期 | 2026-05-07 |
| 起止 commit | `4c951e6` (排除) → `fa22461`（审查基线） |
| 包含 commit 数 | 4（feat rag / chore config / feat eval / docs iteration） |
| 目标里程碑 | M1.4（评测） |
| 责任 LLM | Claude Opus 4.7 |
| 责任人 | XCXUFO |

## 2 变更范围清单

- [x] **rag**：`backend/src/config.py` `embedding_model` 默认改本地路径 `data/models/bge-large-zh-v1.5`，避免 HF 直连不稳。
- [x] **rag**：`scripts/download_models.sh` 新增；通过 hf-mirror.com + 7890 代理拉 BGE-large-zh-v1.5 到 `backend/data/models/`。
- [x] **rag**：`backend/scripts/index_papers.py` 显式传 `settings.embedding_model`，索引 / 查询同源。
- [x] **config**：`backend/src/config.py` `deepseek_model` 默认 `deepseek-chat` → `deepseek-v4-flash`，跟进 DeepSeek 2026-07-24 弃用时间表。
- [x] **eval**：`backend/scripts/run_mini_eval.py` 新增 — 串行 / 不重试 / 不并发的 HTTP runner；`--k` 走 `ChatRequest.k` 走 per-request override。
- [x] **eval**：`data/eval/{README,mini_questions}.yaml` 新增 — 10 题题集（5 类别配额 4/2/1/1/2），id 稳定。
- [x] **eval**：`data/eval/mini_eval_20260507-164315_judged.yaml` 新增 — 4 维二值人工初评。
- [x] **iteration**：`docs/iterations/2026-05-07-m1-4-a-real-index-mini-eval/{spec,candidate_pool,report}.md` 新增。
- [x] **iteration**：`data/papers/sources.md` 新增 — 8 篇 PDF DOI / 作者年来源清单。
- [x] **tests**：`conftest.py` 加 `RUN_LIVE_RAG_CHAT` 哨兵；`test_chat_live` / `test_embedder_live` / `test_rag_live` 改用 `settings.embedding_model`；`test_chroma_store` 翻新 add 重复 id 行为测试（新版 chromadb 静默忽略而非 raise）。
- [x] **deps**：`backend/pyproject.toml` 加 `pyyaml>=6.0`（dev only）。
- [x] **docs**：`backend/README.md` RAG Chat 节重写 4 步流程；`data/papers/README.md` 加"放真实 PDF 并索引"节。
- [x] 未触及：前端、`src/agent/`、`src/api/`、`src/rag/` 业务实现、Chroma schema。

## 3 验证证据清单

| 项 | 命令 | 期望 | 实际 | 通过 |
|---|---|---|---|---|
| backend 全套默认测试 | `cd backend && uv run pytest -q` | 全绿，live 默认跳过 | `101 passed, 3 skipped` | [x] |
| chromadb add 重复 id 行为 pin | `pytest tests/test_chroma_store.py -q` | 重复 add 不替换、不 raise | 命中 | [x] |
| 索引 / 查询同源 | `index_papers.py` 与 lifespan 都读 `settings.embedding_model` | 同一份模型 | 代码审 + grep | [x] |
| 真实 PDF 入库 | `index_papers.py --paths ../data/papers/*.pdf` | chunks > 1000 | `1348 chunks` | [x] |
| HTTP runner | `run_mini_eval.py --questions ../data/eval/mini_questions.yaml` | 10 题落 JSONL | `9 ok / 1 timeout` | [x] |
| `--k` per-request override | `run_mini_eval.py --k 10` | runner 透传 `{"query": ..., "k": 10}` | runid `20260507-191435` 验证 | [x] |
| `usable_for_demo` 初评 | 人工 4 维二值表 | 给出 yes/no + notes | `2/10`，详 `judged.yaml` | [x] |
| `refuse` 题 `not_hallucinated` | 人工核对 q09 / q10 | 不胡编获奖者 / 不强拼数值 | 2/2 | [x] |
| HTTP error 阈值 | runner summary | ≤ 1/10 | 1/10（q01 ReadTimeout） | [x] |

## 4 关键审查点

- [x] 评测过程**未调参**：`top_k` / `chunk` / `embedding` / `LLM` / `query rewrite` 全部按默认跑，2/10 是未调参基线。
- [x] **题面冻结**：mini_questions.yaml `version=1`，10 个 id（q01–q10）稳定，M1.4-b 题集是 superset 不重排 id。
- [x] **§9.5 出题人偏差缓解**：题面来自 `candidate_pool.md`（8 篇 PDF × 5 候选 + 24 主题 gap），不是开发者凭印象出题。
- [x] **citation_check 维度**：q08 由人工核对 `[N]` 标记是否落在 citations 数组合法范围；本轮表现"命中论文但未命中关键 chunk"，记录为 retrieval 问题而非引用一致性问题。
- [x] **拒答底线**：q09（完全脱离知识库）+ q10（Tier B：领域近邻但场景未覆盖）均未编造数值或获奖者；refuse 拒答行为可信。
- [x] **结果归因清晰**：调参附录三个 ablation runid（k=5 复刻 / k=10 / k=10+8000ctx）说明单纯提高 `top_k` 或 `context_chars` 不是主解，瓶颈在召回，不是 LLM。

## 5 偏离与取舍

- [x] **DoD `usable_for_demo` 未达 7/10**：实际 2/10。决策：不在本轮强调到 7/10，转向 M1.4-b 做 reranker。理由是硬调容易 overfit 这 10 题；瓶颈定位（retrieval 命中率）优于打表面分。
- [x] **q01 在正式 runid 触发 60s ReadTimeout**：`HTTP error ≤ 1/10` 的 DoD 通过，但需要 spec 明确"评测时不重试"的策略——本轮按既定行为落盘，不补跑。
- [x] **初评非专家复评**：`judged.yaml` 是开发者自评，下一轮答辩材料前应由领域同学复评 4 维二值，再更新 summary。
- [x] **题集只 10 题**：spec §9.4 已识别 in-sample 风险；M1.4-b 用同一题集做对照实验，泛化验证留 M1.4-c 扩到 20–50 题。
- [x] **embedding_model / deepseek_model 默认值变更影响所有 pull 后的开发者**：BGE 路径不存在时启动会崩；备选回退路径写入 `.env.example` 与 `backend/README.md`。

## 6 风险与回滚

- [x] **风险**：本地 BGE 路径默认在新机器上不存在；mitigation：`backend/README.md` §2 写明 `bash scripts/download_models.sh` 流程，并标注代理 7890；不愿走本地的可在 `.env` 用 `EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5` 走 HF cache。
- [x] **风险**：DeepSeek 默认升 v4-flash 对 v4 系列定价 / 速率限制变化敏感；mitigation：commit body 已注明 2026-07-24 弃用时间表，可 `.env` 覆盖回退到 `deepseek-chat`（兼容期内对应 v4-flash 非思考模式）。
- [x] **风险**：mini eval runner 默认 60s 超时在网络抖动 / 提示词更长时易触发；本轮 q01 即受影响。mitigation：`--timeout` 可调，但要重跑会破坏 baseline 不变性，下一轮再评估。
- [x] **风险**：chromadb add 行为变更（从 raise → 静默忽略）影响重复索引语义；mitigation：`test_chroma_store.py` 中 pin 此行为；indexer 走 `upsert` 路径不受影响。
- [x] **风险**：`judged.yaml` 是初评，专业复评未完成；mitigation：报告与本审查均明确标注"初评，待领域复评"。
- [x] **回滚**：可逐 commit revert：
  - 回退 BGE 默认 → revert `3568989`
  - 回退 deepseek 默认 → revert `d906529`
  - 拆掉 runner / 题集 → revert `8b45f0d`
  - 拆掉迭代文档 → revert `fa22461`
  各 commit 互不依赖，可独立回滚。

## 7 审查结论

- [x] **通过**（机审：Claude Opus 4.7 / 2026-05-07）
- [ ] **驳回**，原因：__________
- [x] **有条件通过**，需在 push 后补做：领域同学复评 `judged.yaml` 4 维二值，并把 summary 更新写入 thesis 材料。

机审结论：所有列入 §3 的命令都通过；DoD 中 `usable_for_demo ≥ 7/10` 未达，但 spec §3.10 已声明本迭代不调参，且 §10 把"瓶颈定位"列为可接受的失败模式。结论"未达阈值但基线有效"与本迭代设计意图一致，建议放行进入 M1.4-b。

---

**机审字段**：

```yaml
iteration: 2026-05-07-m1-4-a-real-index-mini-eval
commits_from: 4c951e6
commits_to: fa22461
commit_count: 4
files_changed: 22
lines_added: 1704
lines_removed: 35
tests_passed: 101
tests_failed: 0
tests_skipped: 3
breaking: false
new_runtime_deps_python: 0
new_runtime_deps_node: 0
secrets_in_repo: false
parent_iteration: 2026-05-05-m1-3-1-chat-rag-route
dod_met: false
dod_failure_reason: "usable_for_demo 2/10 < 7/10; bottleneck identified as retrieval recall, not LLM hallucination; deferred to M1.4-b"
ablation_runids:
  - "20260507-191243"   # k=5 replay
  - "20260507-191435"   # k=10
  - "20260507-191926"   # k=10 + max_context=8000
official_baseline_runid: "20260507-164315"
indexed_corpus:
  papers: 8
  chunks: 1348
```
