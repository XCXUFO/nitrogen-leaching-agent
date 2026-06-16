# Report — M1.5-b q08 Evidence Boost

> 实验日志 + DoD 实证。reranker numeric/evidence boost 让 q08 缺的统计证据段
> `026::0172`（R²/RMSE/IA）穿过 reranker 进入 final context，q08 由「无数值」
> 翻为「答出模型精度」。**全部结论 in-sample（q01–q10 frozen set），不可外推**。

## 0 元信息

| 字段 | 值 |
|---|---|
| 报告版本 | v1.0（检索层闭环 + 1 题 live 旁证） |
| 起始 / 完成 | 2026-06-16 / 2026-06-16 |
| 代码基线 | `ef5c9a1^`（main，M1.5-a 收尾 `b9103a3` 之后） |
| HEAD | `0eee7b3` |
| 配套 spec | `spec.md`（含 5 处用户审订 + band 为实现期新增旋钮） |
| Frozen set | `data/eval/mini_questions.yaml` q01–q10 |
| 默认参数 | `numeric_boost_enabled=True, weight=0.445, band=0.30` |

## 1 提交序列（按模块拆）

| commit | 内容 | 阶段 |
|---|---|---|
| `ef5c9a1` | spec（含 §4.5 审计、§4.3 标定方法） | — |
| `bdb709a` | `numeric_boost.py` 模块 + 单测 | B-1 |
| `f81cf56` | context_debug 接入 boost（offline A/B） | B-1 |
| `6939373` | **relevance band**（q01 回归修复） | B-2 |
| `739c11e` | context_debug band flag + eligible 审计 | B-2 |
| `e6a92cc` | Retriever 接线（reranker 后处理） | step 3 |
| `82cf70e` | config 默认开 + main 注入 + .env.example | step 3 |
| `0eee7b3` | smoke B（q08 live gate） | step 3 |

## 2 前提复核（动代码前先验，spec §2 / §7-C）

A2 默认（recall20 + ref-filter on / overfetch10）下 q08 rerank 候选池含 `026::0172`：
**成立** —— 它在 embedding_recall rank 17、rerank rank 13（logit +0.6979），在池内但被
reranker 压在 top5 之外。precondition 坐实后才动 boost；若不在池内本路线即停（未触发）。

## 3 weight / band 标定（spec §4.3，按实际 boost 排序而非 raw gap）

### 3.1 weight 扫描（q08 单题，A2 默认全候选）

对 q08 的 20 个候选算 density，以 weight 为自变量对**全候选**重算 `logit + w·density`
并重排，扫描让 `026::0172` 进 top5 的最小 weight：

| weight | 026::0172 boost 后名次 |
|---|---|
| 0（off） | r13 |
| 0.30 | r8 |
| **0.395（最小可用）** | **r5（刚进 top5）** |
| 0.40–0.70 | 稳定 r5（平台） |
| 0.80+ | r3 |

取 **weight = 0.445**（最小 0.395 + 0.05 margin），落平台中段，对 logit 抖动有容差。
理由不是「raw gap 0.217」：boost 对全候选叠加，密度更高的 043::0074（dens 0.864）会一起
上浮，单看 gap 会低估所需 weight，故按实际重排标定。

### 3.2 band 的由来（DoD-2 暴露 → 第二个旋钮）

仅有 weight 时 DoD-2 发现 q01 回归：weight 0.445 把 reranker 判为尾部不相关的高密度段
（`067::0087` logit 0.038 / `026::0138` logit 0.009，dens 均 0.825）纯凭 density 抬进 top5，
挤掉 q01 预期源段 `029::0026`。代数上**无解**：

```
保住 q01 右段：0.161 + w·0.307 > 0.038 + w·0.825  ⟹  w < 0.237
解 q08：                                              w ≥ 0.395   → 空集
```

且 q01 是定量题、gate 必开，调 gate 也无效。故加 **relevance band**：只对 `raw_logit ≥
池最高分 − band` 的候选施加 boost，其余保持原分（delta=0）。**band = 0.30** 含 q08 目标
（gap 0.253）、排除 q01 污染段（gap ≈ 0.85）。语义：boost 只重排「够相关的竞争者」,不召回
无关尾部。

## 4 DoD 实证

### 4.1 DoD-1（检索层主判据，离线确定性）— ✅

A2 默认 + boost(0.445/0.30) 下 q08：`026::0172` 进 `reranked_top_n` **rank5**（boosted
0.985，raw 0.698 + delta 0.287）**且进 `final_context`**。审计：它越过零密度的 `026::0167`
（0.951，无 boost）。预期源 [26] Liang 2016 命中。

### 4.2 DoD-2（检索层回归，on/off 全题对账）— ✅

`--top-n 5` 生产口径，boost-off vs boost-on(banded) 逐题 top5：

| qid | gate | vs off | 说明 |
|---|---|---|---|
| q01 | on | **same** | band 把 067::0087/026::0138 判 ineligible（delta=0），029::0026 保留 |
| q02 | on | same | 未扰动 |
| q03 | on | same | 弱尾部不上浮 |
| q04 | on | same | 079::0005/0004 仍 rank1/2（M1.5-a 翻盘证据完整保留） |
| q05 | off | same | gate 关，no-op |
| q06 | off | same | gate 关（机理题，未含定量词） |
| q07 | off | same | gate 关 |
| **q08** | on | **CHANGED** | 026::0172 进 top5（目标） |
| q09 | off | same | gate 关，拒答题无变化 |
| q10 | on | same | gate 开但未塞伪数值段，拒答安全 |

**净效果：全 10 题里唯一 top5 变化的是 q08，其余九题与 boost-off 基线逐字一致。**

### 4.3 DoD-3（answer 层 live 旁证，smoke B）— ✅

生产默认路径（startup 日志确认 `numeric_boost=on(w=0.445,b=0.3)`）问 q08：

- 答：「决定系数 R² 0.84–0.99，RMSE 243–1097 kg ha⁻¹，IA 均大于 0.70」——全部 grounded
- 引用 5 条，**`026::0172` 作为 [5] 被引**，答案正从它取数；非拒答
- latency 29.8s，HTTP 200
- 断言：非拒答 ✓ / metric tokens 全中 ✓ / 026::0172 traced ✓ → PASS

**首跑 504 `llm_timeout`（212s，DeepSeek 端瞬时尖峰，非接线/检索问题）**：startup 日志已证
boost 接线生效、retrieval 阶段已过（超时在 LLM 生成），按 spec/用户裁定记为 live 依赖失败，
**不回退默认**；重试一次即 30s 干净 PASS，印证瞬时抖动。

### 4.4 DoD-4（防过拟合）— ✅

boost 机制可执行逻辑（`numeric_boost.py` / `retriever.py` / `config.py` / `main.py`）
**无 q08 / 026::0172 / 期望数值字面量**——逻辑仅用通用统计词表 + 数值密度 + weight/band
旋钮；`q08`/`026::0172` 仅出现在解释性注释里（动机示例，非分支条件）。query gate 词表
排除 q08 专有词（WHCNS / 华北平原 / 产量），逐题验证只对定量题开。

## 5 机制性副作用（用户要求明记）

boost 不是「只塞 026::0172」，而是按通用 density 整体重排。q08 top5 在 026::0172 之外还
新进 `043::0074`（另一篇 WHCNS 论文的 R²/RMSE 段，dens 0.864）与 `041::0051`，挤掉三个
叙述段（0167/0076/0002）。**这是「通用 boost」的预期副作用，不是违规**：043::0074 本身是
合法统计段。DoD-2 已证它只影响 q08、不污染其它题。smoke B 实测 q08 答案干净源自 026::0172
（[5]），**未混用 043 的数值**，故无需收紧 prompt/引用侧。

## 6 验证汇总

| 项 | 结果 |
|---|---|
| 单测 `test_numeric_boost.py` | 11 passed |
| 全量 `pytest -k "not live"` | 134 passed / 4 deselected（live） |
| context_debug off/on（top5，q01–q10） | 唯 q08 变 |
| context_debug banded（top20，审计） | 026::0172 → top5 + final_context |
| smoke B（live, q08） | PASS（30s；首跑 504 抖动重试通过） |
| DoD-4 grep（机制文件） | clean（仅注释提及 q08） |

## 7 Decision Log

| 时点 | 触发 | 观察 | 下一步 |
|---|---|---|---|
| 前提复核 | A2 context_debug q08 | 026::0172 在 rerank 池 rank13、被压出 top5 | 标定 weight |
| weight 标定 | 全候选扫描 | 最小 0.395 进 top5，平台 0.40–0.70 | 定 0.445 + margin |
| DoD-2 第一轮 | weight-only on/off | **q01 回归**：尾部高密度段挤掉 029::0026；代数无解 | 加 relevance band |
| DoD-2 第二轮 | banded(0.445/0.30) | 唯 q08 变，q01/q03 回到 off | 接生产 + smoke B |
| smoke B | live q08 ×2 | 首 504 抖动 / 重试 30s PASS，引 026::0172 | DoD 全过，写文档 |

## 8 Notes

- **in-sample 声明**：全部基于 q01–q10 frozen set。density 词表/权重、weight、band 均在该
  集上观察标定；泛化判断与 caveat 见 `review.md`。20–30 题扩评（外样本验证）按拍板**不并入
  本轮**，留作独立质量评测（M1.5-c/-e）。
- latency 仅 smoke B 单点（29.8s）+ 一次 504 抖动；非延迟基准。
- 产物：context_debug 输出在 `backend/var/context_debug/`（gitignored，会话级 checkpoint）。
