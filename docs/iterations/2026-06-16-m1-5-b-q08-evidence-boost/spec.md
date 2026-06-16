# 说明文档 — M1.5-b q08 Evidence Boost

> reranker numeric/evidence boost：让 q08 缺的统计证据段 `026::0172`（含
> R²/RMSE/IA）穿过 reranker 进入最终上下文，使 q08 能 grounded 答出模型精度。
> 本轮**只修检索层排序**，不扩题、不动 M1.5-a 已稳的稳定性链路。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代 | M1.5-b（M1.5-Demo 第二刀：内容质量 / 单题证据召回） |
| 起始日期 | 2026-06-16 |
| 代码基线 | `b9103a3`（main，M1.5-a 收尾后） |
| 上游依据 | M1.4-c `report.md` §3.1-2 / `review.md`：q08 廉价路线（top_n 加深、ref-filter）已实测排除，确定走 reranker numeric/evidence boost |
| Frozen set | `data/eval/mini_questions.yaml` q01–q10（**in-sample，不可外推**） |
| 范围决策 | 已与用户拍板（见 §3），spec 落实 |

## 2 背景与事实锚点（来自 M1.4-c 定论，不重测）

q08 的失败链路已被 M1.4-c 8 组矩阵完整定位，**无需先做全题人审再定位**：

| 环节 | 事实 | 出处 |
|---|---|---|
| 目标证据段 | `026::0172`，含 R²/RMSE/IA（模型精度统计指标） | M1.4-c §2.1 备注 |
| embedding 层 | 能召回，rank ≈ 17 | M1.4-c §2.7 / §3.1-2 |
| recall 深度 | recall20 候选池容得下它；recall8/10 召不到 | M1.4-c C1/C2 |
| reranker 层 | 在候选池内，但被 reranker 打分**压在 top_n 之外** → 不进 final context | M1.4-c §2.1–2.4 |
| 廉价路线 | top_n 加深(top7) 无效；ref-filter 无效 | M1.4-c A3/A4 |

**因此本轮下刀点唯一**：在 reranker 打分之后、截 top_n 之前，对**含数值/统计/表格证据**的
候选做一次 query 条件化的加权重排，把 `026::0172` 这类被 cross-encoder 低估的「数据段」
提回 top_n。

**precondition（待本轮第一步复核，非已成立）**：boost 只能在 rerank 候选池内重排，前提是
`026::0172` 已在 A2 默认（recall20 + ref-filter on/overfetch10）的 q08 rerank 候选池内。
M1.4-c 历史结果显示**大概率满足**（recall20 召回、被 reranker 压出 top_n），但那是矩阵备注；
本轮**实现第一步先用 A2 默认 context_debug q08 复核坐实**，确认后再写 boost——若不成立立即停
本路线（见 §7 风险 C）。

## 3 范围（已拍板）

### 3.1 在做

1. **通用 numeric/evidence boost 机制**（独立纯函数，生产路径与 context_debug 共用）。
2. **接入两处 rerank 出口**：`Retriever.retrieve`（生产）与 `scripts/context_debug.py`（离线判据）。
3. **配置项 + A2 兼容默认**：新增 `rag_numeric_boost_*`，与现 A2 demo 默认叠加。
4. **三层 DoD 验证**：检索层主判据（context_debug 可测）+ 检索层回归（q01–q10 不被打坏）
   + answer 层 live 旁证（q08 smoke）。

### 3.2 不在做（明确挂账，避免 scope creep）

- **不扩题**：mini-eval 20–30 题扩评不并入本轮（防膨胀），留作 M1.5-c/-e 独立质量评测。
  → 故本轮所有结论**仍 in-sample，report/review 须带显式 caveat**。
- **不动 reranker 模型内部**：不微调、不换 `bge-reranker-v2-m3`；boost 是模型**外**的后处理。
- **不动 M1.5-a 稳定性链路**：超时/重试/错误契约/前端错误态不改。
- **不改 embedding / recall 深度 / ref-filter 逻辑**：A2 配置保持。

## 4 关键设计判断

### 4.1 boost 做成独立纯函数，而非塞进 Reranker 或 Retriever 内联

`context_debug.py` 是主判据的测量面，但它**不走 `Retriever`**——它直接
`reranker.rerank(query, hits)[:top_n]`（context_debug.py:329）。若把 boost 写进
`Retriever.retrieve` 内联，离线判据就测不到生产真实排序。

→ boost 落为 `backend/src/rag/numeric_boost.py` 的**纯函数**（输入 `query` + reranked
`list[RetrievalResult]`，输出重排后的新列表），生产路径和 context_debug **各自调用同一函数**。
这完全照搬 `reference_filter.filter_reference_chunks` 的既有模式（纯函数、regex 特征、
两处共用、可单测无需模型）。

### 4.2 信号只来自 query × chunk 通用特征（用户硬边界：防过拟合）

boost **不得**写死 `q08` / `026::0172` / expected answer 任何字面量。机制由两部分组成，
均为领域中性的通用特征：

- **chunk 侧 — 数值/统计/表格证据密度**（完全通用，任何数据段都高分）：
  - 数值 token 密度（数字、百分比、`±`、单位如 `kg/ha`/`mg/L` 的出现频次）；
  - 统计指标模式（`R²`/`R2`/`RMSE`/`IA`/`决定系数`/`均方根`/`一致性指数`/`p<`/`r=` 等
    通用统计学词，**非 q08 题面词**）；
  - 表格/对齐结构线索（`Table`/`表`/多列数字对齐、连续数字行）。
  - 归一化到约 `[0,1]`，记为 `density(chunk)`。
- **query 侧 — 定量意图门控**（领域中性，适用于任何「要数字」的问题）：
  - 通用定量词表：`精度`/`多少`/`范围`/`系数`/`误差`/`比例`/`贡献`/`量级`/`accuracy`/
    `error`/`how much` 等。门控 `gate(query) ∈ {0,1}`（或软 `[0,1]`）。
  - 词表在 spec / 代码注释中**逐词列明并论证其通用性**；不含 q08 专有名词
    （如 WHCNS、华北平原、四站点）。

**重排公式**（logit 尺度叠加，reranker logit ≈ `[-10,10]`，见 reranker.py 类注释）：

```
boosted_score(chunk) = rerank_logit(chunk) + weight · gate(query) · density(chunk)
```

按 `boosted_score` 重排，再截 top_n。`weight` 是唯一可调旋钮。

### 4.3 weight 按「实际 boost 排序的最小扰动」标定，**不是 raw logit gap**

`weight` 默认值**不拍脑袋**，也**不能只看 raw logit gap**：因为 boost 是对**所有**候选叠加
`weight·gate·density`，第 5 名及其上方的候选若同样有 numeric density，会被一起抬高——单看
「026::0172 与当前第 5 名的 logit 差」会低估所需 weight。

正确标定流程（实现期一次性做，写进 report）：
1. 对 A2 默认下 q08 的整个 rerank 候选池，算出每个 chunk 的 `density`；
2. 以 `weight` 为自变量、对**全候选**重算 `boosted_score` 并重排，**扫描 / 二分** `weight`；
3. 取「**让 `026::0172` 进入 top_n 的最小 `weight`** + 很小 margin」作为默认值。

取最小值的两个目的：(a) 对其它题排序的扰动最小（防过拟合的工程化）；(b)「为什么是这个值」
连同扫描曲线一起可写进 report，比单点 gap 更站得住。

### 4.4 boost 默认开，作为 M1.5-b 后的新 demo 默认；但保留开关用于 A/B 与回归

参照 M1.5-a 落 A2/ref-filter 的方式：新增 `rag_numeric_boost_enabled`（默认 `True`），
但保留开关，使 DoD 的「on vs off」回归对照可跑、单测可固定。config.py 默认与
`.env.example` 同步改（沿用 M1.5-a §4.2 教训，不只改一处）。

### 4.5 重排可审计：新对象 + metadata 留痕，生产 prompt 零影响

`RetrievalResult` 是 `frozen=True, slots=True` 的 dataclass，不能原地改 `score`。
`apply_numeric_boost` 用 `dataclasses.replace` 生成新对象，并在 `metadata` 写入三个排查字段：
`numeric_boost_raw_score`（reranker 原始 logit）、`numeric_boost_density`、
`numeric_boost_delta`（`weight·gate·density`）；`score` 设为 boost 后分用于重排。

生产 prompt **不受影响**：`format_context`（prompt.py）只取 `result.document` 与
`metadata["source"]`，不读这些字段；citations 也只回传既有结构。但 context_debug 输出**同时
打印 raw 分与 boost 后分**（及上述 metadata），on/off 两份产物对账时一眼看清谁被抬了多少。

## 5 实现要点（落点清单，便于按模块拆 commit）

1. **`backend/src/rag/numeric_boost.py`（新）**：
   - `numeric_evidence_density(text) -> float`（chunk 侧特征，纯 regex/计数，`[0,1]`）。
   - `is_quantitative_query(query) -> bool`（query 侧门控，通用词表）。
   - `apply_numeric_boost(query, reranked, *, weight) -> list[RetrievalResult]`
     （对全候选叠加 boost、按 boost 后分重排，返回**新**列表——用 `dataclasses.replace`
     生成新对象、metadata 留 raw/density/delta 痕，见 §4.5；`weight<=0` 或 `gate=0` 时
     **原样返回**，零行为变化）。
2. **`backend/src/rag/retriever.py`**：`reranker.rerank(...)` 之后、`[:k]` 之前调用
   `apply_numeric_boost`（受 `numeric_boost_enabled` + `weight` 控制；新增构造参数，
   默认关以不改既有调用方行为，由 main.py 注入开）。
3. **`backend/scripts/context_debug.py`**：rerank 行（:329）之后、截 top_n 之前调用同一函数；
   flag 设计为 `--numeric-boost / --no-numeric-boost`（**显式双向开关**，默认跟
   `settings.rag_numeric_boost_enabled`，on/off 对账**不靠环境变量绕**）+ `--numeric-boost-weight`；
   把 boost 状态写进输出 JSON 的 `settings` 块，且 `reranked_top_n` 每段**同时输出 raw 分与
   boost 后分**（及 §4.5 的 metadata）。
4. **`backend/src/config.py` + `backend/.env.example`**：`rag_numeric_boost_enabled: bool = True`、
   `rag_numeric_boost_weight: float = <标定值>`。
5. **`backend/src/main.py`**：把两个 setting 注入 `Retriever` 构造。
6. **`data/eval/smoke_questions.yaml`**：加入 q08（与 mini set 逐字一致），供 smoke B 用。
7. **`backend/scripts/run_smoke_b.sh`（新，仿 run_smoke_a.sh）**：A2+boost 默认下问 q08，断言
   答案含 grounded 的 R²/RMSE/IA 关键值且非拒答。
8. **测试**：`backend/tests/test_numeric_boost.py`（纯函数单测，无模型）；
   `backend/tests/test_retriever.py` 补 boost 接线用例。

## 6 DoD（M1.5-b 通过判据）

| # | 层 | 判据 | 测量方式 |
|---|---|---|---|
| 1（主） | 检索层 | A2 默认 + boost on 下，`026::0172` 进入 q08 `reranked_top_n`（争取进 `final_context`） | context_debug q08，读 JSON，**离线确定性、无 LLM** |
| 2（回归） | 检索层 | boost on vs off 跑 q01–q10：无任何题丢失原有关键证据段；具体 **q04 仍保留 079::0004 & 079::0005 于 top_n**；q09/q10 不因 boost 被塞入诱发脑补的伪数值段 | context_debug 两份产物对账 |
| 3（旁证） | answer 层 | q08 live（A2+boost 默认路径）答出 grounded R²/RMSE/IA 关键值且非拒答 | smoke B，仿 smoke A |
| 4（防过拟合） | 代码 | 代码/配置无 `q08`/`026::0172`/expected 数值字面量；词表通用；§DoD-2 证明非单题局部最优 | 人审 + grep |

> DoD-1 是 gate（必过）；DoD-2 是「不退步」约束（必过）；DoD-3 是体感旁证（live，受 API
> 抖动影响，沿用 smoke A 的「本地手动 gate、不入 CI」定位）。

## 7 风险与回滚

- **风险 A：boost 救了 q08 却打坏别题**（过拟合反面）。→ DoD-2 强制 on/off 全题对账；
  weight 取最小可用值（§4.3）；任一题退步则调小 weight 或收紧 query 门控，不放宽边界。
- **风险 B：reranker logit 尺度漂移**导致固定 weight 失准。→ weight 由标定得来并记录在
  report；reranker 模型不变期内稳定；换模型需重标定（写进风险登记）。
- **风险 C：026::0172 根本不在候选池**（若 ref-filter 误杀或 recall 不够）。→ 实现第一步先用
  context_debug 确认它在 q08 的 `embedding_recall` / rerank 候选内；若不在，本方案前提不成立，
  需回到 recall/ref-filter 层（升级为 Step 3，另议）。
- **回滚**：`rag_numeric_boost_enabled=false` 即回到 M1.5-a 的 A2 默认，零代码回滚。

## 8 交付物

- 代码：`backend/src/rag/numeric_boost.py` + retriever/context_debug/config/main/smoke 接线 + 测试
  （路径见 §5）。
- 文档：本 `spec.md`、`report.md`（实验日志 + on/off 对账表 + weight 标定记录）、
  `review.md`（机审 + 人审，**显式 in-sample caveat**）。
- 提交：按模块拆 Conventional Commits（spec → boost 模块 → 接线 → smoke → report+review），
  push 前两份文档齐（沿用既定工作法）。
