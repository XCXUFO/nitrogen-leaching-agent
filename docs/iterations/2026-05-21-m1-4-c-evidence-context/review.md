# 审查文档 — M1.4-c Evidence Context

> 本轮完成 M1.4-c 评测矩阵 8/8 组，对 reference-section filter、
> recall 深度、top_n 深度和延迟做了 in-sample 对照。结论是：实验闭环通过，
> 但质量 DoD 未闭环；不得把本结果表述为 demo-ready。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代代号 | m1-4-c-evidence-context |
| 日期 | 2026-06-16 |
| 审查基线 | `b537587` 之后的未提交变更 |
| 父里程碑 | M1.4（评测与质量改进） |
| 配套说明 | `spec.md` v1.1 |
| 配套审计 | `evidence_audit.md` |
| 配套报告 | `report.md` |
| Frozen set | `data/eval/mini_questions.yaml` q01-q10 |
| 责任人 | XCXUFO |

## 2 变更范围清单

- [x] **eval script**：新增 `backend/scripts/run_eval_group.sh`，把服务启动、健康检查、
  mini eval 和服务清理绑定到同一生命周期。
- [x] **eval script**：新增 `backend/scripts/run_eval_matrix.sh`，按完成 jsonl 行数做
  checkpoint，支持 flaky 会话下重复执行和跳过完整组。
- [x] **iteration report**：新增 `report.md`，回填 A1-A4 / B1-B2 / C1-C2 共 8 组结果。
- [x] **iteration review**：新增本审查文档，明确 DoD、风险和 M1.5 进入条件。
- [x] 未触及：生产 retriever 逻辑、prompt、frontend、题集、Chroma index、LLM 配置。

## 3 验证证据清单

| 项 | 证据 | 结果 | 通过 |
|---|---|---|---|
| A1 recall20/top5/filter off | `20260603-155831` | 10 ok / 0 err | [x] |
| A2 recall20/top5/filter on | `20260603-162321` | 10 ok / 0 err | [x] |
| A3 recall20/top7/filter off | `20260603-170936` | 9 ok / 1 err | [x] |
| A4 recall20/top7/filter on | `20260615-192727` | 9 ok / 1 err | [x] |
| B1 recall10/top5/filter off | `20260615-193827` | 10 ok / 0 err | [x] |
| B2 recall10/top5/filter on | `20260615-191229` | 9 ok / 1 err | [x] |
| C1 recall8/top5/filter off | `20260615-191741` | 10 ok / 0 err | [x] |
| C2 recall8/top5/filter on | `20260615-192009` | 10 ok / 0 err | [x] |
| Matrix report | `report.md` §2 / §3 | 8/8 组已回填 | [x] |
| Refuse 题不幻觉 | q09 / q10 | 全 8 组均 2 / 2 | [x] |
| q04 evidence flip | A2 / A4 | 079::0004 + 079::0005 进 final context 并答出 | [x] |
| q08 cheap fixes | A3 / A4 / B/C | top_n / ref-filter 均无效 | [x] |

## 4 DoD Review

| DoD | Threshold | Actual | Status |
|---|---:|---:|---|
| HTTP errors | <= 1 / 10 | 全 8 组均 <= 1 / 10 | pass |
| refuse `not_hallucinated` | 2 / 2 | 全 8 组均 2 / 2 | pass |
| `usable_for_demo` | >= 5 / 10 | 未完成全题人审 | incomplete |
| q01-q08 L4 | >= 5 / 8 | 仅 q04 / q08 完整闭环；其余待逐题核 | incomplete |
| recall 20 / 10 / 8 latency record | 有记录 | 三档均有记录；定量加速比受 API 时段污染 | pass with caveat |
| in-sample caveat | 必须声明 | `report.md` §3.1 / §5 已声明 | pass |

结论：M1.4-c 的实验 DoD 通过，质量 DoD 未通过也未失败；状态应标为
`incomplete`。原因不是数据缺失，而是 `usable_for_demo` 与 q01-q08 完整 L4 需要
逐题人审，当前只对 q04 / q08 做了完整闭环。

## 5 关键审查判断

1. q04 的修复成立，但条件严格。

   q04 答出当且仅当 `recall20 && ref-filter on`，只出现在 A2 / A4。ref-filter
   删除 References 假阳性是必要条件，但不是充分条件；recall10 / recall8 的召回池
   无法同时装下 079::0004 和 079::0005，模型仍拒答。

2. q08 不应继续在 top_n / ref-filter 上消耗。

   026::0172 在 embedding rank 约 17，top_n=7 仍进不了 reranker 输出；ref-filter
   与本题无关。下一步应做 reranker numeric / evidence boost，或把 evidence token
   作为后处理重排信号。

3. A2 是当前唯一合理的质量优先 demo 默认候选。

   A4 没有带来 q08 收益，且 top7 增加上下文和延迟风险；B/C 档较快，但会放弃 q04
   翻盘。因此若必须演示，应默认 A2：recall20、top_n=5、ref-filter on、overfetch=10。

4. 不建议把 M1.4-c 直接标为 demo-ready。

   当前还缺完整 `usable_for_demo` 人审、q01-q08 L4 人审、q08 numeric evidence 修复和
   API 抖动降级。把 A2 作为内部 demo candidate 可以接受；对外或 HR demo 质量结论必须
   等 M1.5 再定。

## 6 是否进入 M1.5-Demo

审查判定：**有条件进入 M1.5-Demo 准备，不通过 demo-ready gate**。

进入条件与边界：

- M1.5 可以以 A2 作为默认质量配置继续做 demo hardening。
- M1.5 不应声明 M1.4-c 已达 `usable_for_demo >= 5/10`，除非补完人审并达标。
- M1.5 的首要 backlog 应包含 q08 numeric/evidence boost、全题 L4/usable 人审、
  DeepSeek API 重试与超时友好降级。
- 若演示目标强依赖低延迟，则必须接受 q04 退化，或先做 reranker / LLM 延迟优化。

## 7 风险与回滚

- [x] **in-sample 风险**：所有结论仅基于 q01-q10 frozen set；不可外推到泛化质量。
- [x] **人工评分缺口**：`usable_for_demo` 与完整 L4 未闭环；报告保留待人审状态是正确的。
- [x] **延迟归因风险**：B/C 档跑在 API 顺畅时段，不能与 A 档直接相减得出加速比。
- [x] **API 稳定性风险**：A4 / B1 / B2 首轮出现 502 / ReadTimeout；当前 demo 路径缺少重试和降级。
- [x] **脚本边界**：新增 matrix 脚本只服务离线评测，不改变生产路径；如需回滚，可独立移除两个脚本和本轮报告。

## 8 审查结论

- [ ] **通过：demo-ready**
- [x] **有条件通过：实验闭环，进入 M1.5-Demo 准备**
- [ ] **驳回**

机审结论：M1.4-c 成功定位 q04 / q08 的关键差异，并给出 A2 质量优先候选配置。
但它没有闭合 answer-level 质量 DoD，不应作为正式 demo 质量通过声明。建议放行进入
M1.5 的前提是：M1.5 以 hardening 和剩余质量缺口为目标，而不是把 M1.4-c 当作已达标。

---

**机审字段**：

```yaml
iteration: 2026-05-21-m1-4-c-evidence-context
review_date: 2026-06-16
baseline_commit: b537587
matrix_runs: 8
http_error_threshold_met: true
refuse_not_hallucinated: "2/2 across all 8 runs"
recommended_candidate: "A2 recall20 top_n5 reference_filter_on overfetch10"
dod_quality_met: false
dod_quality_status: "incomplete: usable_for_demo and full q01-q08 L4 require human review"
demo_ready: false
m1_5_entry: "conditional: demo hardening only"
primary_next_steps:
  - "reranker numeric/evidence boost for q08"
  - "human review usable_for_demo and q01-q08 L4"
  - "API retry and timeout degradation"
```
