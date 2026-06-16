# Report — M1.5-a Demo Hardening

> 实现日志 + DoD 实证。M1.5-a 取 M1.4-c review backlog 的「demo 硬化」一刀，
> 压到最窄：让默认启动可稳定演示。三条 DoD 全部闭环，含一次 live smoke 实测。

## 0 元信息

| 字段 | 值 |
|---|---|
| 报告版本 | v1.0（实现闭环） |
| 起始日期 | 2026-06-16 |
| 完成日期 | 2026-06-16 |
| 代码基线 | `847763e`（M1.4-c 闭环）→ 本轮 6 commit |
| 配套 spec | `spec.md` v1.0 |
| 配套 review | `review.md` |
| Smoke 产物 | `data/eval/smoke_questions.yaml` + `backend/scripts/run_smoke_a.sh` |

## 1 提交序列（按模块拆，先稳定再消费）

| # | commit | 步 | DoD |
|---|---|---|---|
| 1 | `1ce6466` docs(iteration): add m1.5-a demo hardening spec | — | — |
| 2 | `4a24ce7` feat(config): default retrieval to A2 demo profile | 1 | #1 |
| 3 | `6fd61da` feat(llm): add bounded timeout and retries to DeepSeek client | 2 | #2 client |
| 4 | `646c87d` feat(api): unify chat error contract with timeout and fallback handling | 3 | #2 后端 + 场景 B |
| 5 | `f000947` feat(web): consume chat error contract with retry | 4 | #2 前端 |
| 6 | `844868e` test(eval): add q04 live smoke gate (smoke A) | 5 | #3 |

## 2 DoD 实证

### 2.1 DoD #1 — 生产默认与 A2 对齐

改动：`config.py` 把 `rag_reference_filter_enabled` 默认 `False→True`、
`rag_reference_filter_overfetch` 默认 `2→10`（recall20 / top_n5 此前已对齐）；
`.env.example` 对齐 + demo profile 提示；`main.py` 启动日志补 `overfetch`；
`test_config.py` 新增 `test_settings_a2_demo_defaults` 锁住四元组。

实现判断（比 spec §4.2 预估更干净）：**只翻 Settings 默认，未动 Retriever ctor
默认**（`retriever.py:55` 仍 `False`）。生产经 `main.py` 走 Settings → A2；直接
`Retriever(embedder, store)` 的测试吃 ctor 默认 → 仍 OFF。核实无任何测试断言
Settings 的 ref-filter 默认，`test_reference_filter.py` 是显式传参 → **测试零波及**。
spec §7 预估的「默认翻转会改单测行为」实际未发生。

未碰 `RAG_ENABLED` / `RAG_RERANKER_ENABLED` 默认（部署开关、opt-in、不在 DoD #1
四参数内；`.env.example` 默认 true 反会在无索引时误导 503）。

**Live 实证**（smoke A 启动日志）：

```
RAG enabled | ... | reranker=data/models/bge-reranker-v2-m3 |
top_k_recall=20 | top_k=5 | reference_filter=on | overfetch=10
```

### 2.2 DoD #2 — LLM 超时 / 重试 / 友好降级（含前端错误态）

**client 层**（`deepseek.py` / `config.py` / `main.py`）：新增
`deepseek_timeout_s=60.0` / `deepseek_max_retries=2`，透传到
`AsyncOpenAI(timeout=, max_retries=)`，**替代 SDK 默认 timeout=600s**——这正是
M1.4-c A3 那次请求拖到 135s 才报错的根因。透传测试用非默认值 42.0/5 断「值确实
落到 AsyncOpenAI」，**不硬编 60/2 策略值**（spec §4.4）。

**后端契约层**（`api/chat.py`）：统一 `_fail` 降级契约，日志带
`layer/code/elapsed_ms`，一眼可辨上游 / 检索 / 内部失败。两处新增：

- 超时单列 `APITimeoutError → 504 llm_timeout`（排在 `APIConnectionError` 前，
  前者是后者子类），对应本轮的有界超时，不再误报 `llm_unreachable`。
- 兜底 `except Exception → 500 internal_error`，走稳定契约、不裸崩；**回固定通用
  文案「服务内部异常，请稍后重试」，`str(exc)` 只进日志**（防泄露内部路径 / 配置 /
  三方细节）。已分类的 LLM/RAG 错误沿用 `str(exc)` 不变。

场景 B（offline pytest）：`test_chat_504_on_llm_timeout`、
`test_chat_500_on_unexpected_error_stays_controlled`（含断言 message 不含
`boom` / `/secret/path`，锁非泄露）。

**前端层**（`error-messages.ts` / `chat-error.tsx` / `page.tsx`）：补
`llm_timeout` / `internal_error` 两个新码文案；ChatError 加可选 `onRetry` +
「重试」按钮；error 时复用保留的 `userQuery` 重新提交。**「保留问题与页面状态」原
架构已满足**（`userQuery` 在 error 时不清空、仍以 user message 显示），本轮没破坏它。
严格守边界：只做错误态消费，不改状态模型、不动视觉、不碰演示脚本 / 免责声明。

### 2.3 DoD #3 — 最小 smoke（q04 默认不拒答 + 一次上游失败可控）

- **场景 A（live）**：见 §3，PASS。
- **场景 B（offline）**：见 §2.2，2 个 pytest 通过。

## 3 Smoke A live 实测

| 项 | 值 |
|---|---|
| 配置 | A2（recall20 / top_n5 / ref-filter on / overfetch10 / reranker on） |
| 题 | q04（湖北荆州稻田地下径流氮损失 vs 地表径流 + 侧渗贡献） |
| 结果 | **PASS** |
| 延迟 | 48.2 s（单题；含 embed + recall20 + CPU rerank + DeepSeek） |
| 引用 | 5 条 |
| 答案 | 「地下径流氮损失约 **6.2 kg N ha⁻¹**，占施氮 **4%**，为地表径流 **2 倍** [1][2]；侧向渗漏贡献 **33%** [1]」 |
| 断言 | grounded 数字 6.2 / 33 / 4% 全在，无拒答标记 |

**两次跑的观察（API 延迟方差）**：首跑在 runner 180s 超时（ReadTimeout），后端
日志显示 chroma 查询已触发、请求仍在途；次跑 48.2s 即返回。诊断为**双因叠加**：
(1) 我 smoke 脚本 runner 超时设太紧（180s）会与后端最坏耗时（60s × (1+2 重试) =
180s LLM + CPU rerank）赛跑 → 已修为 300s；(2) DeepSeek API 延迟方差（M1.4-c
反复记录过的 API 窗口波动）。300s 给足余量后骑过慢窗口。

> 这次实测同时实证了 DoD #1（A2 默认在真 `/api/chat` 路径产出 q04 翻盘）与 DoD #3。

## 4 关键取舍

### 4.1 降级不携带 citations（spec §4.3 落地说明）

spec 场景 B 提到「citations 若已取到则保留」——当前架构 **N/A**：LLM 在
`chat_service.answer` 内、检索之后调用，异常会越过已取到的 citations 抛到 route
层，route 拿不到。要保留 citations 就得返回 200 + 占位答案，正是 §4.3 明确否决的
模式（会污染评测、让 demo「看似正常但不可信」）。故降级一律走错误契约、不携带
citations。

### 4.2 API 延迟方差是真实 demo 风险，本轮缓解到位但未消除

有界超时（60s）+ 有界重试（2）+ 前端重试入口三者叠加，把 M1.4-c 暴露的 API 抖动
从「前端吃裸错误 / 无限等待」降级为「可控 504 + 友好提示 + 一键重试」。但慢窗口本身
（48s 量级单题）仍是质量↔延迟硬权衡的一部分，属 demo 体感而非可消除项。

## 5 验证汇总

| 项 | 证据 | 结果 |
|---|---|---|
| 后端测试 | `uv run pytest -q` | 121 passed / 4 skipped |
| 新增后端测试 | a2_defaults / client 透传 / 504 / 500-不泄露 | 4 个，全过 |
| 前端 | `pnpm lint` + `tsc --noEmit` | 干净 / exit 0 |
| A2 默认 live | smoke A 启动日志 | 四元组生效 |
| q04 非拒答 live | smoke A | PASS（48.2s，6.2/4%/33% grounded） |

## 6 Decision Log

| 日期 | 触发 | 观察 | 下一步 |
|---|---|---|---|
| 2026-06-16 | 步 1 A2 落默认 | 只翻 Settings 默认即满足生产=A2；测试零波及，比 spec 预估干净 | 进步 2 client 透传 |
| 2026-06-16 | 步 2 client 透传 | SDK 默认 600s 是 A3 长挂根因；透传测试断行为不断策略值 | 进步 3 后端契约 |
| 2026-06-16 | 步 3 后端契约 | 超时单列 504、兜底 500 不泄露；场景 B 2 测过 | 进步 4 前端 |
| 2026-06-16 | 步 4 前端 | 状态保留原架构已满足；只加 2 码 + 重试按钮 | 进步 5 smoke A |
| 2026-06-16 | 步 5 smoke A 首跑 | runner 180s ReadTimeout：超时太紧 × API 方差 | 修 runner 300s + 端口预检，重跑 |
| 2026-06-16 | 步 5 smoke A 次跑 | **PASS**：q04 48.2s 答出 6.2/4%/33% grounded，无拒答 | 交棒 review.md 收口 |

## 7 Notes

- smoke A 是本地/手动 gate，不入 CI（依赖真 DEEPSEEK_API_KEY + chroma 索引 +
  reranker 模型）；场景 B 是 offline pytest，可入 CI。
- 延迟 48.2s 来自单次 live，含 API 窗口波动，不作定量基线；与 M1.4-c A2 的 ~28s
  同量级偏慢，归因 API 时段。
- 本报告只承载 M1.5-a 范围；q08 boost（M1.5-b）、全题人审（M1.5-c）、外链演示
  （M1.5-d）不在内。
