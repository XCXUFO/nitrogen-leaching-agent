# 审查文档 — M1.5-a Demo Hardening

> 本轮完成 M1.5-a「demo 硬化」：A2 落生产默认、LLM 有界超时 + 重试 + 用户友好
> 降级（含前端错误态）、最小 smoke gate。三条 DoD 全部闭环，含一次 live smoke
> 实测 PASS。结论：通过，可进入 M1.5-b。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代代号 | m1-5-a-demo-hardening |
| 日期 | 2026-06-16 |
| 审查基线 | `847763e` 之后的 6 个 commit |
| 父里程碑 | M1.5（Demo Hardening） |
| 配套说明 | `spec.md` v1.0 |
| 配套报告 | `report.md` |
| Frozen set | q04（`data/eval/smoke_questions.yaml`，子集自 `mini_questions.yaml`） |
| 责任人 | XCXUFO |

## 2 变更范围清单

- [x] **config**：`config.py` ref-filter 默认对齐 A2（on / overfetch 10）+ 新增
  `deepseek_timeout_s` / `deepseek_max_retries`；`.env.example` 对齐 + demo profile 提示。
- [x] **llm**：`deepseek.py` 透传有界 timeout / max_retries 到 `AsyncOpenAI`，替代 SDK 600s 默认。
- [x] **api**：`chat.py` 统一 `_fail` 降级契约；超时单列 504 `llm_timeout`；兜底
  500 `internal_error`（固定文案、不泄露）；日志带 layer/code/elapsed_ms。
- [x] **web**：`error-messages.ts` 补 2 码；`chat-error.tsx` 加重试入口；`page.tsx` 复用 userQuery 重提。
- [x] **eval**：`smoke_questions.yaml`（q04 子集）+ `run_smoke_a.sh`（live gate + 端口预检）。
- [x] **test**：a2_defaults / client 透传 / 504 / 500-不泄露 共 4 个新测试。
- [x] 未触及：生产检索 / rerank / chunk / embedding / index / 题集 q01-q10 内容。

## 3 验证证据清单

| 项 | 证据 | 结果 | 通过 |
|---|---|---|---|
| A2 默认锁定 | `test_settings_a2_demo_defaults` | 20/5/true/10 | [x] |
| A2 默认 live | smoke A 启动日志 `top_k_recall=20 ... reference_filter=on overfetch=10` | 生效 | [x] |
| client 透传 | `test_client_forwards_timeout_and_max_retries`（42.0/5） | 落到 AsyncOpenAI | [x] |
| 超时契约 | `test_chat_504_on_llm_timeout` | 504 llm_timeout | [x] |
| 兜底不泄露 | `test_chat_500_on_unexpected_error_stays_controlled` | 500 + 固定文案 + 无 boom/路径 | [x] |
| 前端错误态 | `pnpm lint` + `tsc --noEmit` | 干净 / exit 0 | [x] |
| q04 非拒答 live | smoke A | PASS（48.2s，6.2/4%/33% grounded，5 引用） | [x] |
| 全量后端测试 | `uv run pytest -q` | 121 passed / 4 skipped | [x] |

## 4 DoD Review

| DoD | Threshold | Actual | Status |
|---|---|---|---|
| #1 生产默认 = A2 | 20/5/true/10 | config + .env.example + 启动日志 + 测试 + smoke 实证 | pass |
| #2 超时/重试/友好降级 | 显式 timeout + 有界 retry + 稳定契约 + 前端消费 | 60/2 透传、504/500 契约、前端 2 码 + 重试 | pass |
| #3 最小 smoke | q04 非拒答 + 一次上游失败可控 | smoke A PASS + 场景 B 2 测过 | pass |

结论：M1.5-a 三条 DoD 全部 pass。与 M1.4-c（质量 DoD incomplete）不同，本轮目标是
demo 路径稳定性，范围窄、可完整闭环，无 incomplete 项。

## 5 关键审查判断

1. **A2 落默认实现比预估更干净，零测试波及。**

   只翻 Settings 默认（生产经 main.py 走 Settings），Retriever ctor 默认保持
   False，直接构造 Retriever 的测试不受影响。spec §7 预估的默认翻转副作用未发生。

2. **有界超时是本轮最高价值改动。**

   SDK 默认 600s 是 M1.4-c A3 长挂根因。60s + 2 重试 + 前端重试，把 API 抖动从
   「裸错误 / 无限等待」降级为「可控 504 + 友好提示 + 一键重试」。

3. **兜底 500 固定文案 + 不泄露是必要收紧。**

   未知异常回显 `str(exc)` 有泄露内部路径 / 配置 / 三方细节风险；改固定文案、
   细节只进日志，既满足「前端始终拿得到 code」又不泄露。已分类错误沿用 str(exc)。

4. **降级不携带 citations 是正确取舍，不是缺陷。**

   route 层拿不到检索 citations，强行保留会推向 200 占位答案，与 spec §4.3 冲突
   （污染评测 / demo 看似正常但不可信）。

5. **smoke A 首跑失败是脚本超时太紧 × API 方差，非配置缺陷。**

   修 runner 300s + 端口预检后次跑 PASS。A2 配置本身在两跑的启动日志中均正确。

## 6 风险与回滚

- [x] **API 延迟方差未消除**：48s 量级单题仍是质量↔延迟硬权衡的一部分；本轮缓解
  到位（有界超时 + 重试 + 前端重试）但慢窗口本身属 demo 体感，非可消除项。
- [x] **smoke A 依赖外部资源**：真 API key + 索引 + reranker 模型 + 稳定 API 窗口；
  标为本地/手动 gate、不入 CI 是正确边界。场景 B（offline）可入 CI 兜底。
- [x] **demo profile 需操作者显式开 RAG_ENABLED + RERANKER_ENABLED**：这两个仍
  opt-in，`.env.example` 注释已指路；非默认翻转是有意决策（无索引时避免误导 503）。
- [x] **回滚**：6 个 commit 相互独立，可单独回退；A2 默认回退即改两个默认值，
  超时/重试回退即移除 settings 与构造参数，契约 / 前端 / smoke 均为独立增量。

## 7 审查结论

- [x] **通过：M1.5-a demo 硬化三条 DoD 闭环**
- [ ] **有条件通过**
- [ ] **驳回**

机审结论：M1.5-a 在窄范围内完整闭环了「让默认启动可稳定演示」目标。A2 修复进入
真实 demo 路径（live 实证 q04 翻盘）、LLM 抖动有有界超时 + 重试 + 友好降级兜底、
最小 smoke 双场景通过。可放行进入 M1.5-b（q08 numeric/evidence boost）。

> 边界提醒：M1.5-a 不声明 answer-level 质量 DoD 通过——`usable_for_demo` 与
> q01-q08 全题 L4 仍属 M1.5-c 人审。本轮只保证 demo 路径稳定，不保证 demo 内容完备。

---

**机审字段**：

```yaml
iteration: 2026-06-16-m1-5-a-demo-hardening
review_date: 2026-06-16
baseline_commit: 847763e
commits: 6
dod_1_a2_default: pass
dod_2_timeout_retry_fallback: pass
dod_3_smoke: pass
smoke_a_live: "PASS: q04 48.2s, 6.2/4%/33% grounded, 5 citations, non-refusal"
scenario_b_offline: "pass: 504 llm_timeout + 500 internal_error controlled/no-leak"
backend_tests: "121 passed / 4 skipped"
frontend_checks: "eslint clean + tsc --noEmit exit 0"
demo_path_stable: true
answer_quality_dod: "out of scope (M1.5-c human review)"
next_iteration: "M1.5-b reranker numeric/evidence boost for q08"
```
