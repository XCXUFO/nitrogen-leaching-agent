# M1.4-a Mini Eval Report

## 1. 元信息

| 字段 | 值 |
|---|---|
| 迭代 | M1.4-a real index + mini eval |
| 日期 | 2026-05-07 |
| 正式 runid | `20260507-164315` |
| 题集 | `data/eval/mini_questions.yaml` |
| 原始输出 | `backend/var/eval/mini_eval_20260507-164315.jsonl` |
| 人工评分 | `data/eval/mini_eval_20260507-164315_judged.yaml` |
| 评分状态 | 初评，待专业复评 |

> 注意：`20260507-161215` 是索引尚未完整写入时跑出的调试结果，不能作为正式评测依据。

## 2. 索引基线

本轮从 `sample.txt` 演示索引切换到 8 篇真实 PDF。PDF 不入库，来源记录见
`data/papers/sources.md`。

| 指标 | 结果 |
|---|---:|
| PDF 数 | 8 |
| Chroma collection | `papers` |
| 持久化目录 | `backend/var/chroma` |
| 总 chunks | 1348 |
| HTTP runner 题数 | 10 |

入库论文覆盖三类主题：氮淋失机制 / 管理措施 / WHCNS 模型应用。子主题包括稻田氮损失、灌溉水分管理、绿肥替代、土壤质地差异、温室番茄水氮优化与 WHCNS 模型验证。

## 3. 题集说明

题集共 10 题，配额与 spec §3.2 一致：

| category | 数量 | 目的 |
|---|---:|---|
| `factual` | 4 | 验证核心事实问答和具体数值召回 |
| `concept` | 2 | 验证概念解释和机制归纳 |
| `synthesis` | 1 | 验证跨论文综合 |
| `citation_check` | 1 | 人工检查答案 `[N]` 与 citations 对应 |
| `refuse` | 2 | 验证超出知识库时是否拒答、不胡编 |

题面基于 `candidate_pool.md` 从真实论文反推。题面本身不包含本地文献编号，避免把 `[26]` / `[79]` 这类来源编号暴露给模型；编号保留在 `expected_points` 和 `notes`，用于人工判分和答辩追溯。

## 4. Runner 结果

Runner 串行调用 `POST /api/chat`，不重试、不并发，失败原样落盘。

| 指标 | 结果 |
|---|---:|
| OK | 9 |
| HTTP / timeout error | 1 |
| 总题数 | 10 |
| DoD: HTTP error ≤ 1/10 | 通过 |

失败题：

| 题号 | 错误 | 说明 |
|---|---|---|
| q01 | `ReadTimeout('timed out')` | 60s 超时，无可判答案 |

## 5. 初评汇总

初评采用 4 个二值维度：`relevant`、`cited`、`not_hallucinated`、`usable_for_demo`。

| 指标 | 结果 |
|---|---:|
| `relevant` | 4 / 10 |
| `cited` | 3 / 10 |
| `not_hallucinated` | 7 / 10 |
| `usable_for_demo` | 2 / 10 |
| `refuse` 题 `not_hallucinated` | 2 / 2 |

DoD：

| 条件 | 阈值 | 结果 | 是否通过 |
|---|---:|---:|---|
| `usable_for_demo` | ≥ 7 / 10 | 2 / 10 | 否 |
| `refuse` 题 `not_hallucinated` | 2 / 2 | 2 / 2 | 是 |
| HTTP error | ≤ 1 / 10 | 1 / 10 | 是 |

结论：M1.4-a 未达到 HR demo 可用阈值。主要问题不是大面积胡编，而是检索没有命中 expected chunks，导致模型保守回答“资料未涉及”或只答到局部。

## 6. 典型案例

### 6.1 拒答表现可接受

q09 问 2025 年诺贝尔化学奖，模型回答“资料中未涉及”，没有编造获奖者或研究内容。

q10 问“华北平原冬小麦在 AWD 交替干湿灌溉下的氮淋失量”，模型明确表示资料未覆盖该具体场景，没有把稻田 AWD、阿拉善玉米或华北小麦材料硬拼成数值。

这两题说明当前系统在“没有证据时拒答”上有一定底线。

### 6.2 检索漏召回

q03 的正确答案来自 [63] Meng 2022，涉及吉林梨树春玉米田沙壤土 / 黏壤土年均氮淋失与推荐施氮量。但正式 run 的 citations 没有召回 [63]，模型回答“未找到该特定区域和土壤类型的数值信息”。

q04 的正确答案来自 [79] Huang 2024，涉及湖北荆州稻田地下径流 N 损失、地表径流对比与侧向渗漏贡献。但正式 run 没有召回 [79]，模型回答资料未涉及。

q06 同样应命中 [79]，但检索结果不含 [79]，导致机制题失败。

### 6.3 命中论文但未命中关键 chunk

q05 和 q08 都召回了 [26] Liang 2016，但没有命中足够具体的模型框架 / 精度指标段落。模型因此只能给出“WHCNS 是集成土壤-作物系统模型”“IA > 0.70”这类泛化回答，未答到 `expected_points` 中的模块组成、R²、RMSE 和 DBW 异常点。

### 6.4 相近数值混淆

q02 期望的是天津武清温室番茄中“沟灌 + 常规施氮”与“滴灌 + 优化施氮”的直接对比：灌溉水量、水分淋失、硝态氮和 DON 淋失分别减少 41%、60%、68%、68%。

模型回答了同篇论文中另一个情景优化结果：硝态氮淋失减少 87%、DON 淋失减少 74%。这些数值有 citation 支撑，但比较对象错误，不能算可用答案。

### 6.5 综合题覆盖不足

q07 要求回答“减施化学氮肥同时维持或提高产量”的多种管理措施，预期至少整合 [41]、[43]、[60]、[63] 中的两篇以上。模型只回答了紫云英 / 绿肥替代这一条，来自 [60]，没有形成 synthesis。

## 7. HR Demo 建议

当前不建议把 factual / concept 题直接用于 HR demo。可安全展示的只有拒答类能力：

| 推荐题 | 理由 |
|---|---|
| q09 | 完全脱离知识库，模型能拒答且不胡编 |
| q10 | 表面相关但实际未覆盖，模型能避免硬拼数值 |

如果必须演示事实问答，应先进入 M1.4-b 做检索质量改进，再重新跑 mini eval。否则 demo 容易暴露“知识库里有答案但系统找不到”的问题。

## 8. 风险记录

1. **出题人偏差**
   - 本轮题目来自候选池，已尽量从 PDF 内容反推，但仍是开发者自建题集。
   - 后续 M1.4-b 应引入外部人员或独立 LLM 生成部分题目，降低自我验证偏差。

2. **推荐题挑好样本**
   - q09/q10 表现好，但它们只证明拒答底线，不代表系统已能回答专业事实题。
   - HR demo 材料必须同时说明本轮 `usable_for_demo` 只有 2/10。

3. **初评非最终专家判分**
   - 当前 judged.yaml 是初评，用于工程判断。
   - 专业复评后应更新 summary，再写入最终答辩材料。

4. **评测时不调参**
   - 本轮没有在评测过程中修改 `top_k`、chunk 参数或 reranker。
   - 失败结果应作为基线，调优放到后续迭代。

## 9. Backlog for M1.4-b

优先级从高到低：

1. **诊断检索召回**
   - 对 q03/q04/q06/q05/q08 做 query-level retrieval debug。
   - 输出 top-k chunk 的 `source`、`chunk_id`、`score`、`snippet`，确认关键 chunk 为什么没进入 top 5。

2. **提高召回容量**
   - 评估 `chat_top_k` 从 5 提高到 8 或 10 的影响。
   - 重点观察 q07 synthesis 是否能召回多篇 source。

3. **改进 chunk 策略**
   - 当前部分 PDF chunk 平均长度偏长，可能导致关键短句被稀释。
   - 评估按 section / paragraph 切分，或降低 `target_size` / `max_size`。

4. **Metadata-aware retrieval**
   - 保留论文标题、年份、主题、section 等 metadata。
   - 对题面中的地点 / 作物 / 模型名做 metadata 辅助过滤或 rerank。

5. **Query rewrite**
   - 将中文 query 改写为中英混合检索 query，尤其对 WHCNS、DON、lateral seepage、sandy loam 等英文论文术语。

6. **Reranker**
   - 引入轻量 reranker，对 top 20 embedding hits 重排。
   - 优先解决“召回同篇但没命中关键段”的问题。

7. **引用一致性程序化校验**
   - 解析答案中的 `[N]`，检查是否落在 citations 数组范围内。
   - 检查引用句是否有对应 snippet 支撑。

8. **完整评测扩展**
   - 将 10 题扩展到 20–50 题。
   - 保留 M1.4-a 题集作为超集前 10 题，不重排 id。

## 10. 调参诊断附录

本节是 M1.4-b 的诊断实验，不改变 M1.4-a 官方 DoD。官方基线仍以
`20260507-164315` 为准。

| runid | k | max_context_chars | temperature | OK / error | 初步结论 |
|---|---:|---:|---:|---:|---|
| `20260507-191243` | 5 | 4000 | 0.3 | 10 / 0 | 复刻默认 top-k；无超时，但答案质量与官方基线基本一致 |
| `20260507-191435` | 10 | 4000 | 0.3 | 10 / 0 | 更多目标论文进入 citations，但 q03/q04/q05/q06 仍未答出 |
| `20260507-191926` | 10 | 8000 | 0.3 | 7 / 3 | context 加大后 q05/q06/q07 超时，质量没有明显改善 |

观察：

1. `k=10` 能改善召回覆盖面。例如 q04 / q06 的 [79]、q07 的多篇 source、q08 的 [26] 更容易出现在 citations 中。
2. 覆盖面改善没有稳定转化为答案改善。q03/q04/q05/q06 仍倾向回答“资料未涉及”，q07 仍只回答绿肥，q08 仍未给出 R² 0.84–0.99 和 RMSE 243–1097 kg/ha。
3. `CHAT_MAX_CONTEXT_CHARS=8000` 不建议作为当前默认值。它带来更高延迟和 3/10 timeout，但没有解决核心 factual / concept 失败。
4. 单纯提高 `top_k` 或 context 不是主解。下一步应优先做 query-level retrieval debug、query rewrite、metadata-aware retrieval 和 reranker，而不是继续把更多 chunk 直接塞给 LLM。

当前推荐参数策略：

| 场景 | 建议 |
|---|---|
| M1.4-a 官方报告 | 保持 `k=5` / `max_context_chars=4000`，作为未调参基线 |
| M1.4-b 诊断 | 可继续用 `k=10` 暴露更多召回候选，但不作为 demo 默认 |
| HR demo | 不建议仅靠提高 `k` 上线 factual / concept 题 |

## 11. 结论

M1.4-a 完成了真实 PDF 入库、HTTP runner、人工评分表和首轮 mini eval。系统已经从 sample 演示版推进到真实论文索引版，但当前质量不足以进入 HR demo。

本轮最重要的发现是：模型总体更倾向于保守拒答，而不是强行胡编；但 retrieval 对关键事实段的命中率不足，导致专业问答不可用。后续应把工作重点放在检索诊断、chunk 策略、top-k / reranker 和 query rewrite 上，而不是继续包装 demo。
