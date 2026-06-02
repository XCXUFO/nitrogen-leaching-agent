# 说明文档 — M1.4-c 证据抽取 + Context Packing

> 上承 M1.4-b（reranker 已接入，检索层 q01-q08 expected-source top5 命中
> `7/8`，但 `usable_for_demo` 仍为 `2/10`），下接 M1.5-Demo 或 M2 Agent
> 能力建设。
>
> 本迭代的核心判断：当前瓶颈不再是“系统有没有 RAG 闭环”，也不只是
> “目标论文能不能召回”，而是**关键证据是否进入最终 prompt、是否被模型稳定抽取、
> 是否能在可接受延迟内回答**。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代名 | m1-4-c-evidence-context |
| 日期 | 2026-05-21 |
| 文档版本 | v1.1（pivot 后；详见 §1.1） |
| 父里程碑 | M1.4（评测与质量改进） |
| 当前 release | `v0.1.0-m1.4b` |
| 责任人 | XCXUFO |

## 1.1 v1.0 → v1.1 pivot

v1.0 把主线设为“context packing 改进”。2026-05-21 完成 q02 / q04 / q05 / q06 /
q07 / q08 的 final-context dump（`backend/scripts/context_debug.py`）+ 一次性 full
chunk lookup 后，诊断翻转：6 题里 5 题是 **evidence 召回层** 问题，只有 q08 是
reranker 层；packing 层目前无证据是瓶颈。

具体翻转点：

- q04 [79]：embedding top20 里 [79] 的 3 个 chunk 全是 References 列表
  （079::0174 / 0166 / 0155）。正文核心证据 chunk（079::0004 / 0005 / 0083）虽在
  索引里却没被召回。根因是 reference 段在 embedding 上对该 query 压过正文段。
- q02 [43] / q05 [26]：相关 source 召回了大量 chunk，但都是 Intro / Discussion，
  关键 evidence 段（41/60/68% 对比、HYDRUS / DAISY source-mapping）没在 top20。
- q06：mechanism 段（079::0091）被 reranker 压下 top5；numbers 段（079::0086）
  未召回。
- q07：top20 看似 source 多样，但 [41] / [43] / [63] 的 evidence chunk 均未召回，
  synthesis 只能基于 [60] 单源构造。
- q08：唯一 evidence 段（026::0172）在 embedding top20 rank 17，但 reranker 未提
  进 top5——这是干净的 reranker miss，可救。

v1.1 因此把主线从 “evidence + packing” 调整为 “evidence-level recall diagnostics
+ recall fixes”。Packing 改动降级到 backlog；指标体系也从 paper-level 升级到
evidence-level（详见 §4.5 / §6.2）。

## 2 当前状态

项目已经具备端到端 RAG 原型：

```text
paper corpus -> ingest -> chunk -> embed -> Chroma -> retrieve -> rerank
-> prompt context -> DeepSeek -> /api/chat -> frontend UI -> citations
```

已完成能力：

- FastAPI `POST /api/chat`
- Next.js 单轮 chat UI
- BGE embedding + Chroma persistent index
- `BAAI/bge-reranker-v2-m3` 二阶段 rerank
- citations 返回与前端展示
- retrieval debug 脚本
- mini eval runner + judged YAML 流程

M1.4-b 关键结果：

| 指标 | 结果 | 判断 |
|---|---:|---|
| HTTP errors | 0 / 10 | pass |
| q01-q08 expected source in reranked top5（paper-level；v1.1 已降级，见 §4.5） | 7 / 8 | pass，但 q04 是 false positive |
| refuse `not_hallucinated` | 2 / 2 | pass |
| `usable_for_demo` | 2 / 10 | fail |
| 单题延迟 | 25-51 s | demo 风险 |

结论：reranker 值得保留，但不能单独解决答案质量。下一步必须面向 evidence
recall、reference-section 过滤、numeric/table fact 召回与延迟策略。

## 3 范围

### 3.1 在做

1. **失败样例证据审计**（v1.1 已完成主体；持续维护）
   - 逐题审计 q02、q04、q05、q06、q07、q08。
   - 标注 expected evidence chunk 是否存在于 embed top20 / rerank top5 /
     final context（即 §4.5 的 L2 / L3 / L4 指标）。
   - 失败类型细分见 §6.1。

2. **Evidence-level recall diagnostics & fixes**（v1.1 主线，原 packing 计划下沉，
   理由见 §1.1）
   - 优先候选 1：**reference-section 过滤**（针对 q04 等场景；区分正文 /
     参考文献；可走 ingest metadata flag 或 retriever 后处理）。
   - 优先候选 2：**query expansion / multi-query recall**（针对 q02 / q05 / q06
     的 evidence chunk 召回偏到 background / discussion 段的问题）。
   - 优先候选 3：**reranker 后处理**（针对 q08；可考虑 numeric-token boost 或按
     `evidence_tokens` 命中重排）。
   - 候选 4：chunk adjacency / boundary 复检（针对 q05 / q06 相邻段被切散；
     仅在前 3 项不足时启动，因为 re-chunk 影响全库）。
   - 候选 5（backlog）：source-aware packing / 同 source 多 chunk 去重；目前无
     单题证据指向 packing 层瓶颈，留到 evidence recall 改善后复评。

3. **Evidence-focused retrieval debug**
   - 已有 `backend/scripts/context_debug.py` 覆盖三层 dump（`embedding_recall`
     / `reranked_top_n` / `final_context`）。
   - 一次性 full chunk lookup（不入库脚本，仅 inline 命令）已经验证：snippet
     检查会产生假阴性，必须按 `chunk_id` 从 Chroma 拉完整 document 才能下结论。
   - 后续如需常态化“full chunk + `evidence_tokens`”检查，再产品化成脚本。

4. **Reranker 延迟优化实验**
   - 评估 `RAG_RERANKER_TOP_K_RECALL=20 / 10 / 8` 的速度与命中差异。
   - 保留 `RAG_RERANKER_TOP_N=5` 作为第一轮对照。
   - 记录每题 latency、evidence-level L2 / L3 命中、answer-level judged 变化。
   - 评估是否需要条件 rerank：embedding 结果足够确定时跳过 reranker。

5. **Mini eval 扩展准备**
   - 不改 q01-q10 的 id、题面和 expected points。
   - 追加题集前先完成上面的问题定位，避免扩题后仍看不清失败原因。
   - 本迭代后半段再扩到 20-30 题；50 题放到质量稳定后。

6. **报告与 review**
   - 输出 `report.md`：证据审计表、recall 改动、延迟对照、answer-level 结果。
   - 输出 `review.md`：DoD 复盘、剩余风险、是否进入 M1.5-Demo 的判断。

### 3.2 不在做

- 不做 WHCNS 真实仿真接入；仍属 M3。
- 不做多轮对话、streaming、工具调用；仍属 M2。
- 不做前端大改；除非需要展示 debug 信息，否则 UI 保持稳定。
- 不把 M1.4-c 结果包装成生产质量结论。
- 不为了通过 10 题手工改题或硬编码 query。
- 不盲目更换 embedding / chunking / LLM；每次只动一个主要变量。
- **不做 source-aware / evidence-aware packing 算法**（v1.0 原主线，v1.1 降级；
  理由见 §1.1）。`format_context` 字符预算逻辑保持现状。

## 4 关键设计判断

### 4.1 先修证据链，再扩题

M1.4-b 已经证明：相关 source 经常能进入 reranked top5，但答案仍错过关键数字、
比较对象或多源结论。若现在直接扩到 50 题，只会得到更多失败记录，却未必知道失败
发生在哪一层。

因此本迭代先建立 evidence audit，再扩题。

### 4.2 Context packing 升级思路（v1.1 暂缓）

> **v1.1 更新**：full chunk lookup 数据（详见 `evidence_audit.md`）显示，6 题里
> 没有一题能确定为 packing miss——主要瓶颈在 evidence 召回层。本节判断保留作为
> 长期方向，但 M1.4-c 不实现 packing 改动。当前迭代主线见 §4.5。

当前 `Retriever` 返回排序后的 top-k，`ChatService` 再按字符预算拼上下文。这个策略
简单，但对以下问题不友好：

- 同一篇论文多个相邻 chunk 重复占用上下文。
- 关键数字在 rank 5，前面 broad context 已经用完预算。
- synthesis 题需要多 source，但 top5 可能被单 source 垄断。
- citation_check 题需要 table metric，普通 snippet 不一定保住表格附近内容。

这些场景在 evidence recall 改善后可能仍然存在，届时再启动 packing 工作。

### 4.3 Reranker 延迟先用配置实验降风险

当前 `RAG_RERANKER_TOP_K_RECALL=20`，CPU 下单题 25-51 秒。第一轮优化不应直接重写
模型推理路径，而是先比较：

| 配置 | 预期 |
|---|---|
| recall 20 / top5 | 质量基线，慢 |
| recall 10 / top5 | 可能显著变快，质量需验证 |
| recall 8 / top5 | 更快，但 q01/q03/q04 风险更高 |

如果 recall 10 质量可接受，则可作为 demo 默认配置；recall 20 保留给离线评测。

### 4.4 条件 rerank 是后续工程优化点

条件 rerank 规则候选：

- embedding top5 source 分布合理且 top1/top2 分差明显时跳过 rerank。
- refuse 题或低相似度题优先走拒答，不强行 rerank。
- synthesis 题、numeric/table 题强制 rerank。

本迭代可以设计并小范围实现，但必须先有 latency 与质量对照基线。

### 4.5 评测指标从 paper-level 升级到 evidence-level

M1.4-b 的 “q01-q08 expected source in reranked top5 = 7/8” 具有误导性：q04 的
[79] 命中是 References 段而非 evidence 段；q07 的多 source 命中里也只有 [60] 含
substantive evidence。本迭代起，主指标采用四级 evidence-level：

| 级别 | 含义 | 备注 |
|---|---|---|
| L1: expected paper in embed top20 | 旧 paper-level 指标 | 仅作背景，不再单独作为通过条件 |
| L2: expected evidence chunk in embed top20 | evidence 是否被召回 | 第一道关 |
| L3: expected evidence chunk in reranked top5 | reranker 是否选对 | 第二道关 |
| L4: expected evidence chunk in final context | 是否真的进 prompt | 决定模型能不能用 |

“Evidence chunk hit” 的可操作定义：

- 每题维护一个 `evidence_tokens` 字段：must-have term 列表 + 变体
  （如 `["R²", "R2"]`、`["lateral", "侧向"]`）。
- 某 chunk hit evidence ⇔ chunk 完整文本里命中题目所要求阈值 `K` 个 must-have
  term（`K` 由题定，简单题 `K=1`，多信息点 `K=2` 或更多）。
- 该指标承认局部假阴性（unicode、改写），不作为唯一判据，需要保留人审 dump。

本迭代不强求把 `evidence_tokens` 立即写入 `data/eval/mini_questions.yaml`；先在
`evidence_audit.md` 第二张表里逐题维护，验证后再下沉到 yaml schema。

## 5 计划变更清单

| 项 | 文件 | 内容要点 |
|---|---|---|
| 迭代 spec | `docs/iterations/2026-05-21-m1-4-c-evidence-context/spec.md` | 本文件（v1.1） |
| 证据审计文档 | 同目录 `evidence_audit.md` | q02/q04/q05/q06/q07/q08 evidence-level 数据 |
| 一次性诊断脚本 | `backend/scripts/context_debug.py` | 三层 dump（`embedding_recall` / `reranked_top_n` / `final_context`） |
| Inline full chunk lookup | 不入库；输出落 `backend/var/context_debug/<runid>/full_lookup.txt` | 一次性诊断，验证 snippet 假阴性 |
| Recall 改动（reference filter 等） | `backend/src/rag/retriever.py` 或 ingest pipeline | 按 §3.1 候选 1-3 实施 |
| Context packing | （本迭代不动） | 降级到 backlog，理由见 §1.1 / §4.2 |
| Retrieval debug | `backend/scripts/retrieval_debug.py` | source 分布、numeric/unit 标记，已能跑通 |
| 配置实验 | `.env` / report 记录 | recall 20/10/8 对照，不一定改默认值 |
| 测试 | `backend/tests/` | recall 改动相关单测；packing 单测推迟 |
| 报告 | 同目录 `report.md` | 实验结果与结论 |
| Review | 同目录 `review.md` | 是否进入 demo 的判断 |

## 6 DoD

### 6.1 诊断 DoD

- q02 / q04 / q05 / q06 / q07 / q08 均有 evidence audit 记录，且含 evidence
  chunk id（不只是 paper id）。
- 每题归类到下列细分（可多选）：
  - evidence recall miss within source
  - reference-section false positive
  - mixed recall + reranker miss
  - reranker evidence miss
  - chunk boundary / table preservation risk
  - packing miss（仅在前几类排除后保留）
- 能说明 evidence chunk 在 embed top20 / rerank top5 / final context 各层是否出现。

### 6.2 质量 DoD

在 q01-q10 frozen set 上：

| 指标 | 阈值 |
|---|---:|
| HTTP errors | <= 1 / 10 |
| refuse `not_hallucinated` | 2 / 2 |
| `usable_for_demo` | >= 5 / 10 |
| q01-q08 evidence chunk in final context（L4） | >= 5 / 8 |
| q01-q08 evidence chunk in embed top20（L2） | 记录用，不设硬阈值 |

说明：M1.4-b 的 answer-level 目标 `>= 7/10` 没达成。本迭代先把目标设为
`>= 5/10`，证明证据链改动有效；若达到 `>= 7/10`，可直接评估 M1.5-Demo。

注：L4 指标替代了 M1.4-b 的 paper-level “expected source in final context”。原
指标 7/8 在 q04 上是 false positive（命中的是 References 段），不再单独作为通过
条件。

### 6.3 延迟 DoD

至少完成 recall 20 / 10 / 8 的对照记录：

- 每题 latency
- 平均 latency
- p95 latency
- expected-source top5 命中
- answer-level 人工评分

若 recall 10 在质量上不明显退化，则推荐作为 demo 配置候选。

### 6.4 文档 DoD

- `report.md` 写清楚每个实验变量。
- `review.md` 明确是否进入 M1.5-Demo。
- 不把 in-sample 10 题结果表述成泛化结论。

## 7 今日操作顺序

【已完成 2026-05-21】

1. 建立本 spec（v1.0）。
2. 读取 `ChatService` 当前上下文拼接逻辑。
3. 产出 `evidence_audit.md` 初版，未验证项标 `hypothesis:`。
4. 实现一次性 final-context dump（`backend/scripts/context_debug.py`），覆盖：
   - `embedding_recall`（top-k-recall 可配）
   - `reranked_top_n`（top-n 可配）
   - `format_context` 实际落到 prompt 的 chunk_id / 顺序 / 截断
   - `source_reference_hints` 在以上每一层是否出现
5. 跑 q02 / q04 / q05 / q06 / q07 / q08 dump。
6. 一次性 inline full chunk lookup（不入库），按 `chunk_id` 从 Chroma 拉完整
   document + token check（含 unicode 变体）；输出落到
   `backend/var/context_debug/<runid>/full_lookup.txt`。
7. Sanity check：确认 [79] 共 175 chunks 已 ingest；q04 真正 evidence 段
   （079::0004 / 0005 / 0083 / 0086）在索引里但未召回；q05 模块列表
   （026::0030）和 source-mapping（026::0033）相邻但只前者召回。
8. 改本 spec → v1.1，主线从 packing 调整为 evidence recall。

【待办，按依赖顺序】

9. 填 `evidence_audit.md` 两张表至 evidence-level 数据。
10. 已选定第一刀：候选 1（reference filter）。
11. 已实现 retriever 后处理版 reference filter + 单测；q04 复跑显示
    `overfetch=10` 时 L2 / L3 / L4 可恢复，详见 `evidence_audit.md`。
12. 若本地服务与模型可用，跑一次 mini eval。
13. 产出 `report.md` 与 `review.md`。

## 8 风险

- 只优化 q01-q10 会过拟合；报告必须声明 in-sample。
- Packing 规则过复杂会变成隐性 prompt engineering，难解释。
- 降低 reranker recall 可能让 q01/q03/q04 的目标来源掉出候选。
- 如果本地缺模型或 API key，今天只能完成代码与非 live 测试，live eval 顺延。
- Reference-section 过滤可能把“作者讨论已有文献”误判为 reference；规则上线前要在
  q04 上验证不杀正文段，并保留一小批判定样本备查。
- `evidence_tokens` 检查存在 unicode / 改写假阴性，不替代人审 dump；定阈值 `K`
  时要按题保守。
