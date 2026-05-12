# 说明文档 — M1.4-b 检索改进 + Reranker

> 上承 M1.4-a（基线 `usable_for_demo=2/10`，瓶颈定位在 retrieval 命中率
> 而非 LLM 胡编），下接 M1.4-c 完整评测和 M1.5-Demo HR 链接。
>
> 本迭代不是"完整评测扩容"。目标是**只针对 retrieval 召回质量做工程改进**，
> 用同一套 10 题与同一份索引做对照实验，让 `usable_for_demo` 从 2/10
> 推到 ≥7/10。如果 reranker 单独够用，query rewrite 可以不做。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代名 | m1-4-b-retrieval-rerank |
| 日期 | 2026-05-08 |
| 涉及 commit | `6fc2a40` retrieval debug；`213fff9` reranker integration；`1add700` retrieval debug memory fix；report/review 见本迭代 docs commit |
| 文档版本 | v1.0（设计） |
| 父里程碑 | M1.4（评测） — a / b 两步走的第二步 |
| 设计 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |
| 上一轮 | `2026-05-07-m1-4-a-real-index-mini-eval` |
| 上一轮 baseline runid | `20260507-164315`（k=5，未调参） |

## 2 范围

### 2.1 在做

1. **Query-level retrieval debug 工具**
   - 给定 query → 打印 top-N（默认 N=20）`source` / `chunk_id` / `score` / `snippet[0:120]`
   - 离线脚本（`backend/scripts/retrieval_debug.py` 或 inline 进现有脚本）
   - 输出落盘到 `backend/var/retrieval/<runid>/<question_id>.json` 便于 diff
   - 用途：M1.4-a 时只能从答案猜哪一步坏；本迭代改完 reranker 后必须能对 q01–q08 复现"目标 chunk 进 top5 / 没进"的事实
2. **Reranker 集成**
   - 模型固定 `BAAI/bge-reranker-v2-m3`（多语言，2.3 GB；语料是中英混合所以选 v2-m3 而非 reranker-large）
   - 接入方式：`Retriever` 内增加 rerank 阶段。`top_k_recall` 走原 embedding（默认 20），rerank 后取 `top_n` 给 LLM（默认 5）。
   - 走本地路径默认值（仿照 M1.4-a 的 BGE 处理）：`reranker_model: str = "data/models/bge-reranker-v2-m3"`，`scripts/download_models.sh` 多拉一份
   - 配置项加：`rag_reranker_enabled: bool = True`、`rag_reranker_top_k_recall: int = 20`、`rag_reranker_top_n: int = 5`、`rag_reranker_model: str`
3. **重跑同套 10 题对照**
   - 复用 `data/eval/mini_questions.yaml`（题面冻结）
   - 跑两个 runid：
     - **A**: reranker 关（`RAG_RERANKER_ENABLED=false`）— 应当复刻 M1.4-a baseline
     - **B**: reranker 开 — 主对照
   - 落 JSONL + 走 retrieval_debug 出 q01–q08 的 reranked top5 实际命中
   - 人工 4 维二值评分（沿用 M1.4-a `judged.yaml` schema）
4. **报告 + review**
   - `docs/iterations/2026-05-08-m1-4-b-retrieval-rerank/report.md`：A vs B 对照、retrieval-level 命中率、answer-level 4 维二值变化、case study
   - 同目录 `review.md`：机审 + 人审；明确 7/10 是 in-sample，泛化留 M1.4-c

### 2.2 不在做（明确边界）

- ❌ **不动 10 题题面**：`mini_questions.yaml` `version=1` 冻结；任何题面变更触发"调题人偏差"问题
- ❌ **不动 chunk 策略**：不重建索引、不改 `target_size` / `max_size` / `overlap`；重建索引混进 reranker 实验里没法归因
- ❌ **不动 embedding model**：保持 `BAAI/bge-large-zh-v1.5`（本地路径）
- ❌ **不动 LLM**：保持 `deepseek-v4-flash` + 默认 prompt + temperature 0.3
- ❌ **不做 query rewrite**：除非 reranker 单独不到 7/10，再单独起 M1.4-c 做；现在做会一次动两个变量，归因失败
- ❌ **不扩题集**：保留 10 题；20–50 题扩展留 M1.4-c
- ❌ **不做 LLM-as-judge** / **不做 `[N]` 程序化校验** / **不做 token 预算精确化** → 全部 M1.4-c
- ❌ **不动前端**、**不动部署**

### 2.3 计划变更清单

| 项 | 文件 | 内容要点 |
|---|---|---|
| Reranker 实现 | `backend/src/rag/reranker.py` 新增 | 包装 `BAAI/bge-reranker-v2-m3`；`Reranker.rerank(query, candidates) -> List[(score, chunk)]` |
| Retriever 集成 | `backend/src/rag/retriever.py` 修改 | rerank 阶段；`enabled=False` 时纯 embedding 路径不变（保证 A 对照可复刻） |
| 配置 | `backend/src/config.py` 修改 | `rag_reranker_enabled` / `_top_k_recall` / `_top_n` / `_model` 四个新字段 |
| 配套 | `backend/src/main.py` lifespan | reranker 实例化（`enabled` 时才加载，避免 RAG 关时白下 2.3 GB） |
| 模型下载 | `scripts/download_models.sh` 修改 | 增加 `bge-reranker-v2-m3` 拉取（条件下载，避免对 BGE-only 用户也强加 2.3 GB） |
| 调试脚本 | `backend/scripts/retrieval_debug.py` 新增 | 给定 query → 打 top-N（embedding-only / reranked 双视图） |
| `.env.example` | 修改 | 加四个 reranker 字段示例值 |
| `backend/README.md` | 修改 | RAG Chat 节加"启用 Reranker" 子节 |
| 测试 | `backend/tests/test_reranker.py` 新增 | 不依赖真实模型（mock score function）；`@pytest.mark.live` 才走真模型 |
| 测试 | `backend/tests/test_retriever.py` 修改 | 增加 reranker 关 / 开两条路径回归 |
| 报告 | `docs/iterations/2026-05-08-m1-4-b-retrieval-rerank/report.md` 新增 | A vs B + retrieval-level 命中表 + case study |
| 审查 | `docs/iterations/2026-05-08-m1-4-b-retrieval-rerank/review.md` 新增 | 机审 + 人审 |
| 评分 | `data/eval/mini_eval_<B-runid>_judged.yaml` 新增 | 沿用 M1.4-a schema，4 维二值 |

## 3 关键判断

### 3.1 为什么是 reranker 不是 query rewrite

M1.4-a 调参附录显示 `k=10` 让目标论文进入 citations 候选概率明显上升（q04 / q06 / q07 / q08），但答案质量没有同步改善——LLM 看到 10 段内容里只有 1–2 段是关键证据，剩下都是噪声，prompt 被稀释。Reranker 是把"召回更多 + 重排取关键"做成两步，比单纯把 `top_k` 拉到 20 干净。

Query rewrite（如中文 query 拼英文术语）也能改善召回，但有两个风险：
1. 手工 per-question 补关键词 → 测试集泄漏（看了 expected_points 才补 "R²" / "lateral seepage"）
2. 自动 LLM-rewrite → 多一个组件、多一个 prompt、多一个失败模式

reranker 是 drop-in、归因清楚，应优先尝试。

### 3.2 为什么固定 `bge-reranker-v2-m3` 而非 `bge-reranker-large`

| 候选 | 中文 | 跨语言 | 大小 | 选择 |
|---|---|---|---|---|
| `bge-reranker-large` | 强 | 弱 | 1.1 GB | 否 |
| `bge-reranker-v2-m3` | 良 | 强 | 2.3 GB | 是 |

8 篇论文里题面是中文，但具体数值 / 术语在 Methods/Results 段是英文（"R²"、"sandy loam"、"lateral seepage"、"WHCNS modules"）。跨语言 rerank 命中率比单语种更重要，所以选 v2-m3。`large` 留作回退方案——如果 v2-m3 跑不动或精度不达，单独起子任务换。

### 3.3 为什么 recall=20 / top_n=5

- recall=20：M1.4-a 调参附录的 top-20 诊断显示 q03 / q04 / q06 的目标论文均在 rank 8–18 之间，20 是把这些题"理论可救"的最小阈值。
- top_n=5：和 M1.4-a 默认 `chat_top_k=5` 对齐，控制 LLM 上下文不变形（`max_context_chars=4000` 不动），让效果归因到 reranker 排序质量而不是上下文长度变化。

## 4 DoD

### 4.1 Answer-level（硬阈值）

| 条件 | 阈值 | M1.4-a baseline |
|---|---|---|
| `usable_for_demo` | ≥ 7 / 10 | 2 / 10 |
| `refuse` 题 `not_hallucinated` | 2 / 2 | 2 / 2 |
| HTTP error | ≤ 1 / 10 | 1 / 10 |

### 4.2 Retrieval-level（硬阈值）

| 条件 | 阈值 | 说明 |
|---|---|---|
| q01–q08 中目标论文进 reranked top5 的题数 | ≥ 6 / 8 | "目标论文"指 `mini_questions.yaml` notes 字段里 `[N]` 标注的预期来源；至少有 1 个该论文的 chunk 出现在 reranked top5 即算命中 |

`refuse` 题（q09 / q10）不参与本指标——它们的目标是"不命中"。

### 4.3 Synthesis diagnostic（软指标，不硬卡）

| 条件 | 阈值 | 说明 |
|---|---|---|
| q07 reranked top8 中不同 source 数 | ≥ 2 | synthesis 题质量信号；不达不阻断本迭代，记录到 backlog 引导 M1.4-c |

q07 是 synthesis 题，预期跨 ≥2 篇文献。把它写成硬 DoD 风险高（最小闭环过重）；写成 diagnostic 只在 report.md 里给数值。

### 4.4 in-sample 风险声明（必填到 report.md §x）

> M1.4-b 的 7/10 是 in-sample 数据：题集与 baseline 共用 10 题，reranker
> 参数（recall / top_n）有可能"恰好对这 10 题好"。真正的泛化验证留 M1.4-c
> 用 20–50 题扩展集做。

不写这段就放进答辩材料 → 答辩时被问到"为什么不是过拟合"答不上来。

## 5 实现顺序

1. **第一步：retrieval debug 脚本**
   - 不依赖 reranker；先打 embedding-only 的 top-20。
   - 跑一遍 q01–q08，落盘 → 与未来 reranked top-20 做 diff
   - 这一步独立可测；落 commit `feat(rag): add retrieval debug script`
2. **第二步：Reranker 实现**
   - `Reranker` 类 + `Retriever` 集成 + 配置 + lifespan
   - mock 测试先过；live 测试 gated（同 BGE 风格，`RUN_LIVE_RERANK=1`）
   - 落 commit `feat(rag): integrate bge reranker v2 m3`
3. **第三步：A 对照**
   - 启 backend `RAG_RERANKER_ENABLED=false` → 跑 mini eval → 应复刻 baseline 数据（usable_for_demo ≈ 2/10）
   - 不复刻 → 实现路径有副作用，回查
4. **第四步：B 主实验**
   - 启 backend `RAG_RERANKER_ENABLED=true` → 跑 mini eval → 走 retrieval_debug 出每题 reranked top5
5. **第五步：人工评分**
   - 沿用 M1.4-a `judged.yaml` schema，4 维二值；只评 B 的 JSONL
6. **第六步：写报告 + review**
   - `report.md`：A vs B 表格、retrieval-level 命中表、answer-level 4 维变化、典型 case
   - `review.md`：机审 + 人审；标注 in-sample
   - 落 commit 拆分：`docs(iteration): ...spec` → `feat(rag): debug script` → `feat(rag): reranker` → `docs(iteration): report` → `docs(iteration): review`

## 6 风险与预检

### 6.1 模型下载（最大变量）

- `bge-reranker-v2-m3` 约 2.3 GB；首次下载走 hf-mirror.com + Clash 7890 代理
- 预检：动手前先在新机器上跑 `bash scripts/download_models.sh`，确认 `backend/data/models/bge-reranker-v2-m3/` 完整再开始 reranker 编码
- 风险：网络抖动半下崩了会留一坨 partial 文件，要写脚本支持续传 / 重试（curl `--retry` 已有）

### 6.2 实现错误污染 A 对照

- 风险：refactor `Retriever` 时引入 bug，让 `RAG_RERANKER_ENABLED=false` 路径也变了
- 预检：A 对照用 `pytest`（`test_retriever.py` 加 enabled=false 路径测试）+ 重跑 baseline 必须复刻 `usable_for_demo=2/10`，不复刻就停下来回查

### 6.3 推理时间膨胀

- reranker 是额外一次 forward pass；2.3 GB 模型 CPU 跑可能让单题响应从 3–5 s 变 10+ s
- 预检：不阻断；加监控 `latency_ms`，report.md 列出 baseline vs B 延迟分布
- 如果延迟太离谱（>30 s/题），考虑 pin GPU 或换 reranker-large 子任务（不在本迭代范围）

### 6.4 in-sample overfit

- 风险：reranker 参数（recall=20 / top_n=5）在这 10 题上调过，真换题集会塌
- 预检：本轮**不调参**——recall / top_n 用上面 §3.3 论证的默认值跑；调参留 M1.4-c
- 报告里必须按 §4.4 写 in-sample 声明

### 6.5 评分人是开发者本人

- 沿用 M1.4-a 风险——`judged.yaml` 是开发者初评，可能潜意识偏好 B
- 缓解：评分时**不看是哪个 runid**（人为控制），后置揭晓
- 答辩材料前补领域同学复评（同 M1.4-a 处理）

## 7 评测产物

- `backend/var/eval/mini_eval_<A-runid>.jsonl`（reranker off，对照基线）
- `backend/var/eval/mini_eval_<B-runid>.jsonl`（reranker on，主实验）
- `data/eval/mini_eval_<B-runid>_judged.yaml`（B 的人工 4 维二值评分）
- `backend/var/retrieval/<B-runid>/q01.json` … `q08.json`（每题 reranked top5/top20 快照）
- 报告：`docs/iterations/2026-05-08-m1-4-b-retrieval-rerank/report.md`

baseline JSONL 不重跑——直接引用 `mini_eval_20260507-164315.jsonl`。如果实现路径触及到 lifespan 或 chat_service 的"打开/关闭"开关之外的代码，A 对照仍要跑一遍证明无副作用。

## 8 后续 backlog（本轮不做）

- M1.4-c 题集扩展到 20–50 题（保留 q01–q10 作 superset 前 10 题，id 不重排）
- M1.4-c LLM-as-judge 自动评分
- M1.4-c `[N]` 引用合法性程序化校验
- M1.4-c query rewrite（仅在 reranker 单独不达 7/10 才动手）
- M1.4-c chunk 策略调整（仅在前面都不够时动手；动 chunk = 重建索引 = 新基线）
- M1.5-Demo cloudflared 临时外链（等 M1.4-b 通过再上）
