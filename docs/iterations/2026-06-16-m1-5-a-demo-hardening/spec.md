# 说明文档 — M1.5-a Demo Hardening

> 标题：**M1.5-a Demo Hardening — production A2 defaults + LLM retry/fallback + smoke gate**
>
> 上承 M1.4-c（评测矩阵 8/8 闭环，`review.md` 判定「有条件进入 M1.5-Demo 准备，
> 不通过 demo-ready gate」，唯一让 q04 evidence-level 翻盘的配置是 A2）。
> 下接 M1.5-b（q08 numeric/evidence boost）、M1.5-c（q01–q08 全题 L4 / usable 人审）、
> M1.5-d（cloudflared/frp 外链 + 演示脚本）。
>
> 本迭代的核心判断：**先让「默认启动后可演示、不容易当场翻车」成立**，再谈
> demo 内容够不够好。当前更基础的问题不是「答案质量」，而是「demo 路径本身是否稳定」：
> ① A2 修复没进生产默认路径（ref-filter 默认关、overfetch=2），直接起服务演示 q04 会拒答；
> ② LLM 上游失败（502 / ReadTimeout）会直接暴露给前端、且无有界超时。质量人审做得再好，
> 也降不低这两个现场翻车概率。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代名 | m1-5-a-demo-hardening |
| 日期 | 2026-06-16 |
| 文档版本 | v1.0 |
| 父里程碑 | M1.5（Demo Hardening / 演示准备） |
| 当前 release | `v0.1.0-m1.4b` |
| 审查基线 | `847763e`（main，M1.4-c 已闭环） |
| 责任人 | XCXUFO |

## 2 背景与现状核实

M1.4-c `review.md` §6 把 M1.5 首要 backlog 定为三类：demo 硬化、q08 numeric/evidence
boost、全题人审 + API 重试降级。本迭代（M1.5-a）**只取「demo 硬化」这一刀**，且压到最窄：
让默认启动可稳定演示。其余挂账 M1.5-b/c/d。

代码核实（基线 `847763e`）：

| 项 | A2 推荐 | 当前生产默认 | 文件 | 结论 |
|---|---|---|---|---|
| `top_k_recall` | 20 | 20 | `config.py:42` / `.env.example:36` | ✅ 已对齐 |
| `top_n` | 5 | 5 | `config.py:43` / `.env.example:37` | ✅ 已对齐 |
| `reference_filter_enabled` | **on** | **`False`** | `config.py:46` / `.env.example:43` | ❌ 默认关，q04 会拒答 |
| `reference_filter_overfetch` | **10** | **`2`** | `config.py:48` / `.env.example:45` | ❌ 不足以拉回 079::0004/0005 |
| LLM 有界超时 | 需要 | **无**（吃 SDK 默认） | `llm/deepseek.py:8` | ❌ A3 q05 拖到 135s 才报错 |
| LLM 重试/退避 | 需要（显式可控） | 仅 SDK 隐式默认 | `llm/deepseek.py` | ❌ 不可控、不可见 |
| 上游失败响应 | 用户友好可控 | 已分类抛 502/429/500 | `api/chat.py:36-59` | ⚠️ 分类已有，但前端吃裸错误 |
| 上游 vs 检索失败区分 | 需要 | 已区分（`RAGQueryError` 独立） | `api/chat.py:30` / `chat_service.py:60` | ✅ 已具备，保留 |

> 关键既有资产：上游失败 vs 检索失败的区分**已经做对了**（`RAGQueryError` 与
> `llm_*` 分开 catch、分开记日志）。本迭代不重建这套分类，只在它之上补「有界超时 +
> 显式重试 + 可控降级契约」。

## 3 范围

### 3.1 在做（M1.5-a 三条主线，对应三条 DoD）

1. **A2 落成生产默认**
   - `config.py`：`rag_reference_filter_enabled` 默认 `True`、`rag_reference_filter_overfetch`
     默认 `10`；`top_k_recall=20` / `top_n=5` / `min_keep=1` 维持。
   - `.env.example`：把 demo profile 注释 + 值对齐 A2，并显式标注「这是 M1.4-c 验证过的
     demo 质量默认，改动会影响 q04」。`RAG_REFERENCE_FILTER_ENABLED=true`、
     `RAG_REFERENCE_FILTER_OVERFETCH=10`。
   - 启动日志已打 `reference_filter on/off`（`main.py:77`）；补打 `overfetch` 值，让默认配置在日志里可核。

2. **LLM 调用：有界超时 + 显式重试 + 用户友好降级（含前端错误态消费）**
   - **有界超时**：新增 `deepseek_timeout_s`，传入 `AsyncOpenAI(timeout=...)`，杜绝 A3 那种
     135s 长挂。**必须存在显式 timeout**；默认值先定 60s，可被 `.env` 覆盖。
   - **显式重试**：新增 `deepseek_max_retries`，传入 `AsyncOpenAI(max_retries=...)`，把 SDK
     隐式重试变成可配置、可见、**有界**（仅对可重试错误：连接/超时/429/5xx 生效）。默认值先定 2，
     可被 `.env` 覆盖。
   - **后端用户友好降级**：保持 `api/chat.py` 现有错误分类与 HTTP 语义（不把上游失败伪装成 200），
     确保返回**稳定、文档化的错误契约** `{code, message}`，并补齐 code/耗时字段，使日志一眼可辨
     「LLM 上游故障」与「检索/后端逻辑故障」（现状已部分具备）。
   - **前端错误态契约消费（纳入本轮，边界写死）**：
     - 识别 `llm_unreachable` / `llm_upstream_error` / `llm_rate_limited` / `llm_auth_failed`
       / 通用 error；
     - 显示稳定中文友好提示（非裸 stack / 非空白等待 / 非控制台异常）；
     - 提供一次「重试」入口；
     - 保留用户当前问题与页面状态；
     - **不做**视觉大改、不做演示脚本、不做免责声明/说明文案扩展（这些是 M1.5-d）。

3. **最小 smoke / eval gate**（两条场景，不做全题人审）
   - **场景 A — q04 默认路径不再拒答**（live，需真索引 + LLM）：复用 `run_mini_eval.py`
     跑 q04 单题子集，断言 answer 非拒答（含 6.2 / 4% / 33% 之一或显式非「资料中未涉及」）。
     作为本地/手动 gate，不入 CI（依赖外部 LLM 与本地 chroma）。
   - **场景 B — 一次上游失败可控降级**（offline，pytest）：注入一个会抛
     `APIConnectionError` / 超时的 mock LLM，断言 `/api/chat` 返回既定降级契约
     （稳定 code + 非 5xx-unhandled、不崩、检索 citations 若已取到则保留），且日志标记为上游失败。
     纯单测、确定、可入 CI。

### 3.2 不在做（明确挂账，避免 scope creep）

- ❌ q08 numeric/evidence boost → **M1.5-b**（reranker 后处理，独立子迭代）。
- ❌ q01–q08 全题 L4 / `usable_for_demo` 人审 → **M1.5-c**（或与 b 并行）。
- ❌ cloudflared/frp 外链、演示脚本、安全声明打磨 → **M1.5-d**（本地路径稳定后才上）。
- ❌ 前端 UI polish、首页/说明/免责声明扩写、演示顺序与话术、加载态/骨架屏 → **M1.5-d**。
  本轮前端**只**做错误态契约消费（见 §3.1.2），不滑成演示 UI 打磨。
- ❌ 复杂熔断 / 限流 / 队列 / circuit breaker：M1.5-a 只要「有界超时 + 少量重试 + 可控降级」，不做生产级弹性。
- ❌ 多轮、streaming、工具调用 → M2。WHCNS → M3。
- ❌ 不改检索/rerank/chunk/embedding/index/题集；本轮**不动 A2 之外的任何检索变量**。
- ❌ 不把 M1.4-c 结果包装成 demo-ready 或质量 DoD 已过。

## 4 关键设计判断

### 4.1 为什么 A2 落默认排第一

最低风险、最高收益的一刀。M1.4-c 已证明 q04 翻盘 ⟺ `recall20 ∧ ref-filter on`，而生产
默认现在 ref-filter 关、overfetch=2 —— 等于把已验证有效的修复挡在真实 demo 之外。若不先修，
后面做外链/脚本都是在包装一个 q04 会拒答的不稳定版本。

> **定位声明**：A2 是当前 **demo default**，不是「已验证的最终最优检索策略」。M1.4-c 只在
> q01–q10 frozen set 上对照出它是唯一让 q04 翻盘的配置，q08 仍未解。M1.5-b 做 q08
> numeric/evidence boost 后，reranker / numeric evidence 信号可能要再调，那时允许覆盖
> 本轮的默认值——M1.5-a 只负责「让默认可演示」，不锁死检索策略，二者不冲突。

### 4.2 同时对齐 config.py 默认与 .env.example，而非只改一处

运行时配置实际来自 `.env`（gitignored），`config.py` 默认在 env 缺省时兜底，`.env.example`
是新部署的模板。要让「默认启动即可演示」稳健成立，三者需一致：

- `config.py` 默认对齐 A2 → 即便某次 `.env` 漏配 ref-filter，行为仍是验证过的配置而非 q04-breaking 配置。
- `.env.example` demo profile 对齐 A2 并加注释 → 新部署 copy 即得正确默认。

> 风险：把 `rag_reference_filter_enabled` 默认翻成 `True` 会改变所有未显式配置者（含部分单测）
> 的检索行为。本轮须连带核对/修正受影响的既有测试（见 §6 验证 与 §7 风险）。

### 4.3 降级用「稳定错误契约 + 前端友好渲染」，不用「200 伪成功」

两条路线：(a) 保持 HTTP 错误语义、返回稳定 `{code, message}`，前端按 code 映射友好文案；
(b) 上游失败时返回 200 + 占位答案。选 **(a)**：后端不能把「模型没答」伪装成成功，否则 demo 里
会出现「看起来答了、其实是降级占位」的更糟体验，也污染后续 eval 的 ok/err 统计。前端只需
最小改动——把已有错误码（`llm_unreachable` / `llm_upstream_error` / `llm_rate_limited` /
`llm_auth_failed` / `rag_query_failed`）映射成中文友好提示并允许「重试」。

### 4.4 超时与重试的取值是「demo 体感」而非「SLA」

默认 `timeout=60s` / `max_retries=2` 是为 demo 现场体感选的（A 档单题 median ~28s，60s 给
一次 LLM 端抖动留余量；2 次重试覆盖偶发连接抖动而不至于把单题拖到分钟级）。取值放进 settings、
可被 `.env` 覆盖，不在代码里写死。本轮不追求定量 SLA。

**测试只断行为、不断策略值**：smoke/单测断言「显式 timeout 已生效 / 可重试错误会触发有界重试 /
最终失败走可控降级契约」，**不**把 `60` / `2` 这类策略值硬编进测试断言。这样后续 A 档延迟变化、
要调超时或重试次数时，改默认值不会牵动一堆测试。

## 5 实现要点（落点清单，便于按模块拆 commit）

| 模块 | 文件 | 改动 |
|---|---|---|
| config | `backend/src/config.py` | ref-filter 默认对齐 A2；新增 `deepseek_timeout_s` / `deepseek_max_retries` |
| env 模板 | `.env.example` | demo profile 对齐 A2 + 新增 timeout/retries + 注释说明 |
| LLM client | `backend/src/llm/deepseek.py` | `AsyncOpenAI(timeout=, max_retries=)`；构造签名透传 |
| 装配 | `backend/src/main.py` | 传 timeout/max_retries；启动日志补 overfetch/timeout/retries |
| API 降级 | `backend/src/api/chat.py` | 核验错误契约稳定（`{code,message}`），补耗时/标记字段（分类逻辑保留） |
| 前端 | `frontend/`（最小） | 错误码 → 中文友好文案映射 + 重试入口 |
| smoke A | `backend/scripts/`（复用 `run_mini_eval.py`）+ q04 子集 yaml | live gate：q04 非拒答 |
| smoke B | `backend/tests/`（新增 pytest） | offline gate：mock LLM 抛错 → 可控降级契约 |

**实现 / 提交顺序**（先稳定再消费，按模块拆 commit，不攒大 commit）：

1. **A2 默认**：`config.py` + `.env.example` 对齐 + 启动日志补 overfetch。
2. **LLM client timeout/retry**：`deepseek.py` 透传 `timeout` / `max_retries` + `main.py` 装配 + settings。
3. **后端错误契约 + 测试**：`api/chat.py` 稳定 `{code,message}` + 补字段；新增场景 B offline pytest。
4. **前端错误态消费**：错误码 → 中文提示 + 重试 + 保留状态（边界见 §3.1.2）。
5. **smoke A（live）**：q04 子集 yaml + 跑通记录。
6. **文档**：`report.md` 回填 + `review.md` 复盘。

## 6 DoD（M1.5-a 通过判据）

| # | DoD | 判据 | 验证方式 |
|---|---|---|---|
| 1 | 生产默认配置与 A2 对齐 | `top_k_recall=20`、`top_n=5`、`reference_filter_enabled=true`、`reference_filter_overfetch=10` 在 `config.py` 默认与 `.env.example` 均成立；启动日志可核 | 读默认 + 启动日志 + smoke A |
| 2 | LLM 调用具备超时/重试/友好降级（含前端错误态） | 后端：`AsyncOpenAI` 带**显式 timeout** 与**有界 max_retries**（默认 60/2、可 `.env` 覆盖），上游异常返回稳定 `{code,message}` 而非裸错误/无限等待，日志可辨上游 vs 检索失败。前端：识别错误码 → 中文友好提示 + 一次重试 + 保留问题与页面状态。测试断行为（超时生效/会重试/失败可控），不断策略值 | smoke B + 前端手测 + 读日志 |
| 3 | 最小 smoke/eval 跑通 | 场景 A：q04 默认路径不拒答；场景 B：一次上游失败返回可控降级且不崩 | 跑 smoke A（live）+ pytest smoke B（offline） |

附带不回归项（非新增 DoD，但须保持）：

- refuse 题 q09/q10 仍干净拒答（A2 默认下不退化）。
- `pytest` 全绿（含因 ref-filter 默认翻转而需修正的既有用例）。
- 上游 vs 检索失败的日志区分不被本轮改动破坏。

## 7 风险与回滚

- **默认翻转影响既有测试**：`reference_filter_enabled` 默认 `True` 会改变未显式配置用例的
  检索行为。缓解：本轮逐一核对受影响测试，必要时在测试里显式置参而非依赖默认。
- **超时取值偏紧误伤慢但正常的请求**：60s 在 A 档 median ~28s 下有余量，但 API 抖动时段
  仍可能触发降级。缓解：取值可被 `.env` 覆盖；report 记录一次抖动时段的实际表现。
- **重试放大上游压力 / 延迟**：`max_retries=2` 对 429/5xx 退避重试可能把单题拉长。缓解：
  仅对可重试错误生效，且总时长受 `timeout` 上界约束。
- **前端降级是最小改动、非完整 UX**：本轮只做错误码→文案映射 + 重试，不做加载态/骨架屏等，
  那些放 M1.5-d 演示打磨。
- **回滚**：三条主线相互独立，可单独回退——A2 默认回退即改两个默认值；超时/重试回退即移除
  两个 settings 与构造参数；smoke 为新增文件，可独立删除。均不触碰检索/rerank 生产算法。

## 8 交付物

- `backend/src/config.py` / `.env.example`：A2 默认 + timeout/retries。
- `backend/src/llm/deepseek.py` / `main.py`：有界超时 + 显式重试 + 日志补字段。
- `backend/src/api/chat.py`（+ 前端最小映射）：稳定降级契约。
- `backend/tests/`：场景 B offline smoke；q04 子集 yaml + 跑通记录：场景 A live smoke。
- `report.md`：A2 默认核验、smoke A/B 结果、一次上游失败实测、延迟体感记录。
- `review.md`：DoD 复盘、剩余风险、是否放行 M1.5-b/c/d。
