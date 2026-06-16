# Report — M1.4-c Evidence Context

> 实验日志 + 结果表。8 组矩阵已跑完并回填；answer-level 人审项保留待核，
> 不在本报告内伪造 `usable_for_demo` 或完整 L4 判定。

## 0 元信息

| 字段 | 值 |
|---|---|
| 报告版本 | v1.0（矩阵闭环） |
| 起始日期 | 2026-06-03 |
| 完成日期 | 2026-06-15 |
| 代码基线 | `b537587`（main，未 push） |
| 配套 spec | `spec.md` v1.1 |
| 配套审计 | `evidence_audit.md` |
| 配套 review | `review.md` |
| Frozen set | `data/eval/mini_questions.yaml` q01–q10 |

## 1 实验矩阵

8 组对照。reranker 模型固定为 `BAAI/bge-reranker-v2-m3`，embedding 固定为
BGE。`overfetch` 仅在 ref-filter 启用时生效。

| Run | recall | top_n | ref-filter | overfetch | 目的 |
|---|---:|---:|---|---:|---|
| A1 | 20 | 5 | off | — | M1.4-b 基线复跑（确认无回归） |
| A2 | 20 | 5 | on | 10 | 验证 ref-filter 是否解 q04 而不伤其他题 |
| A3 | 20 | 7 | off | — | q08 廉价试探：top_n 是否能替代 numeric boost |
| A4 | 20 | 7 | on | 10 | 组合上限：ref-filter + 更深 top_n |
| B1 | 10 | 5 | off | — | 延迟 DoD：recall 10 基线 |
| B2 | 10 | 5 | on | 10 | 延迟 + ref-filter 交叉点 |
| C1 | 8 | 5 | off | — | 延迟 DoD：recall 8 基线（补齐 spec §6.3 三档之三） |
| C2 | 8 | 5 | on | 10 | 最快档下 ref-filter 收益是否仍稳（q04 是否仍翻盘） |

> 默认 `chat_max_context_chars` 保持 `settings` 当前值，不在本轮调整
> （packing 改动按 spec §4.2 暂缓）。

## 2 单组结果

每组一张小表。`q04 L2/L3/L4` 与 `q08 L3/L4` 是显式追踪列，独立于
overall score；`备注` 用于记录 citation 肉眼检查、单题失败原因、延迟
异常等不便量化的观察。

### 2.1 Run A1 — recall20 / top_n=5 / ref-filter off

| 项 | 值 |
|---|---|
| run_id | `20260603-155831`（jsonl `mini_eval_20260603-155831.jsonl`） |
| 配置 | recall=20, top_n=5, ref-filter=off |
| 跑完日期 | 2026-06-03 |
| HTTP errors | 0 / 10 |
| median latency | 27.0 s |
| p95 latency | 53.9 s（max 57.8 s，min 19.9 s） |
| q04 L2 / L3 / L4 | no(直接) / no / no（top5 全为 [41]，final context 零 [79]） |
| q08 L3 / L4 | no / no（top5 全为 [26] 但缺 026::0172） |
| usable_for_demo | 需人审（provisional 见备注） |
| not_hallucinated（refuse 题） | 2 / 2（q09 干净拒答；q10 解释式拒答） |
| 备注 | **q04**：rerank 后 top5 = `041::0070/0146/0162/0161/0108`，无 079；模型正确拒答「资料中未涉及」。注意分层：`/api/chat` 只暴露 rerank top5 + final context，**不 dump embed top20**，所以 A1 只能直接证明「reranked top5 / final context 零 [79]」，**不能**单独证明 embed top20 没有 [79]。5 月 audit 的「079 References 假阳性 @ embed top20」与本轮「final context 零 [79]」处于**不同层、各自成立、不矛盾**：embed top20 里 079 出现的是 References 段（假阳性），而 baseline 下 reranker 没把它们送进最终上下文，正文段（079::0004/0005/0083）则压根没进候选——两者叠加导致 [79] 在最终上下文完全缺席。**q08**：top5 = `026::0167/0141/0076/0002/0164`，缺含 R²/RMSE/IA 的 `026::0172`；模型「未提供具体 RMSE 数值」，确认干净 reranker miss。**provisional usable**（待人审）：q09/q10 拒答正确；q04 正确拒答但漏了本应能答的 [79] 证据（召回未命中）；q01/q02/q03/q05/q06/q07 答案含引用但 evidence 命中需逐题判。citations 字段结构正常（dict: chunk_id/source/score/snippet）。 |

### 2.2 Run A2 — recall20 / top_n=5 / ref-filter on / overfetch=10

| 项 | 值 |
|---|---|
| run_id | `20260603-162321`（jsonl `mini_eval_20260603-162321.jsonl`） |
| 配置 | recall=20, top_n=5, ref-filter=on, overfetch=10 |
| 跑完日期 | 2026-06-03 |
| HTTP errors | 0 / 10 |
| median latency | 28.8 s |
| p95 latency | 32.7 s（max 33.3 s，min 20.9 s） |
| q04 L2 / L3 / L4 | yes(反推) / yes / yes（top5 = 079::0005(r1)/0004(r2)/041::0070/079::0067/041::0130） |
| q08 L3 / L4 | no / no（top5 与 A1 逐字相同，仍缺 026::0172） |
| usable_for_demo | 需人审（q04 由拒答翻为带数字正答，provisional 较 A1 +1） |
| not_hallucinated（refuse 题） | 2 / 2（q09 干净拒答；q10 解释式拒答，无脑补数值） |
| 备注 | **q04（headline）**：ref-filter 在 top20 删掉 079 References 段后，overfetch=10 把正文证据段 079::0004/0005 拉进 rerank top1/top2 → final context → 答案给出「地下径流氮损失 6.2 kg N ha⁻¹、占施氮 4%、为地表径流 2 倍、侧向渗漏贡献 33%」[1][2]。逐字核对 079::0004/0005 原文：四个数字（6.2 kg N ha⁻¹、4%、2-fold、33%）全部 grounded，非脑补。对比 A1 q04 top5 零 079、模型拒答——生产 `/api/chat` 路径复现了 5 月 context_debug 结论。**L2 标注**：`/api/chat` 不 dump embed top20，L2 由「正文段已穿过 ref-filter+overfetch 进入送 reranker 的候选池」反推，非直接观测（同 A1 分层口径）。**误杀核查**：逐题比对 A1↔A2 top5，未见 ref-filter 删掉任一题先前可用的正文证据段——q02 丢 079::0005 但 top5 转向其 expected source [43]（改善）；q05/q06/q07 仅次序微调，关键段保留（q06 机理段 079::0091 仍 rank1）；q09/q10 拒答仍干净。**q03**：should_refuse=False 但仍拒答，A1 同样未答出（沙壤/黏壤淋失范围）；ref-filter 把候选换成 063::0138/0123/029 段模型仍抽不出 → q03 自身 evidence-recall miss，非 A2 回归，单独跟踪。**延迟**：overfetch=10 无可测延迟成本（median 28.8s vs A1 27.0s，噪声内；p95 32.7s 比 A1 54s 紧，归因 LLM 端波动而非 ref-filter）。 |

### 2.3 Run A3 — recall20 / top_n=7 / ref-filter off

| 项 | 值 |
|---|---|
| run_id | `20260603-170936`（jsonl `mini_eval_20260603-170936.jsonl`） |
| 配置 | recall=20, top_n=7, ref-filter=off |
| 跑完日期 | 2026-06-03 |
| HTTP errors | 1 / 10（q05 = 502 `llm_unreachable`） |
| median latency | 27.5 s（剔除 >70s API 抖动后 24.9 s） |
| p95 latency | 83.1 s（剔除抖动后 32.9 s；抖动尖峰 q07 80s / q10 85s） |
| q04 L2 / L3 / L4 | no(反推) / no / no（top7 仍零 079 正文段，模型仍拒答） |
| q08 L3 / L4 | no / no（top7 = A1 五段 + 041::0051 / 043::0074，**026::0172 仍未进**） |
| usable_for_demo | 需人审（q04 仍漏 [79]、q08 仍漏 026::0172；另 q05 因 API 502 无答案） |
| not_hallucinated（refuse 题） | 2 / 2（q09 干净拒答；q10 解释式拒答，无脑补 AWD 数值） |
| 备注 | **A3 目的 = 「top_n 加深能否替代 reranker numeric boost 解 q08」→ 否**。q08 top7 在 A1 五段之后补的是 041::0051 / 043::0074（他源），含 R²/RMSE 的 026::0172 仍被 reranker 压在 top7 之外 → 单纯加深 top_n 无效，q08 需走 Step 2（numeric / evidence boost）。**q04**：top7/off 仍零 079 正文段、仍拒答（与 A1 同）→ 印证解 q04 的是 ref-filter（见 A2），不是 top_n 深度；off 配置下 079::0004/0005 压根没进 reranker 候选池。**HTTP err 1/10**：q05 = 502 `llm_unreachable`（135s 超时后报错，DeepSeek API 端连接故障，非检索/配置问题），仍在 DoD ≤1/10 内。**延迟受 API 抖动污染**：含全部 ok 时 median 27.5s / p95 83.1s 被 q07 80s、q10 85s 两个抖动尖峰拉高；剔除 >70s 尖峰后 median 24.9s / p95 32.9s 才是配置本身特征，与 A1（27.0/53.9）、A2（28.8/32.7）可比。 |

### 2.4 Run A4 — recall20 / top_n=7 / ref-filter on / overfetch=10

| 项 | 值 |
|---|---|
| run_id | `20260615-192727`（jsonl `mini_eval_20260615-192727.jsonl`；首轮 q09/q10 撞 API 故障已重跑，废数据存 `.apifail`） |
| 配置 | recall=20, top_n=7, ref-filter=on, overfetch=10 |
| 跑完日期 | 2026-06-15 |
| HTTP errors | 1 / 10（q07 ReadTimeout，API 抖动；达标 ≤1/10） |
| median latency | 32.8 s（API 抖动时段；p95/max 见下，非配置稳态） |
| p95 latency | 138.4 s（max 165.8 s，min 23.6 s；**尖峰系 API 抖动**，非 top7 开销） |
| q04 L2 / L3 / L4 | yes(反推) / yes / yes（top7 = 079::0005(r1)/0004(r2)/...，答出 6.2/4%/2×/33%） |
| q08 L3 / L4 | no / no（top7 = 026 五段 + 041::0051/043::0074，026::0172 仍未进，与 A3 一致） |
| usable_for_demo | 需人审（q04 翻盘正答；q07 因 API 缺数据） |
| not_hallucinated（refuse 题） | 2 / 2（q09 干净拒答；q10 解释式拒答） |
| 备注 | **q04 翻盘在 top7 仍稳**：0004/0005 仍占 top1/top2，与 A2(top5) 同结论 → top_n 5→7 不改变 q04（关键段本就在前两位），**recall20 才是 q04 翻盘的决定变量**（对照 B2/C2 recall10/8 失败）。**q08**：top7+ref-filter 仍 miss 026::0172，与 A3(top7/off) 完全一致 → q08 与 top_n 深度无关，确定留给 Step 2（reranker numeric/evidence boost）。**延迟**：本组重跑撞上 API 不稳时段，p95 138s / q07 timeout 均系 DeepSeek 端，非 recall20/top7 的真实开销；med 32.8s 与 A2 的 28.8s 同量级，符合 recall20 档预期。 |

### 2.5 Run B1 — recall10 / top_n=5 / ref-filter off

| 项 | 值 |
|---|---|
| run_id | `20260615-193827`（jsonl `mini_eval_20260615-193827.jsonl`；首轮 8/10 撞 API 故障已重跑，废数据存 `.apifail`） |
| 配置 | recall=10, top_n=5, ref-filter=off |
| 跑完日期 | 2026-06-15 |
| HTTP errors | 0 / 10（CLEAN；重跑落在 API 稳定时段） |
| median latency | 16.4 s（API 顺时段，见 §3 延迟 caveat） |
| p95 latency | 42.8 s（max 46.9 s，min 13.9 s；n=10） |
| q04 L2 / L3 / L4 | no / no / no（recall10/off，top5 全 041 + 060::0107，拒答） |
| q08 L3 / L4 | no / no（026 四段 + 041::0051，026::0172 未进） |
| usable_for_demo | 需人审（recall10 baseline；q04 拒答） |
| not_hallucinated（refuse 题） | 2 / 2（q09 干净拒答；q10 解释式拒答） |
| 备注 | recall10/off baseline。q04 off 必拒答（同 A1/C1，079 正文段进不了候选）。**与 B2(recall10+rf) 构成 recall10 档的 ref-filter 开关对照**：两者 q04 都拒答——off（B1）进不了 079，on（B2）虽删了 References 但 recall10 太浅、捞不全 0004/0005——**recall10 档 ref-filter 不产生 q04 收益**，与 recall20 档（A1 off 拒答 → A2 on 翻盘）形成鲜明对比。延迟 caveat 同 §3。 |

### 2.6 Run B2 — recall10 / top_n=5 / ref-filter on / overfetch=10

| 项 | 值 |
|---|---|
| run_id | `20260615-191229`（jsonl `mini_eval_20260615-191229.jsonl`） |
| 配置 | recall=10, top_n=5, ref-filter=on, overfetch=10 |
| 跑完日期 | 2026-06-15 |
| HTTP errors | 1 / 10（q03 ReadTimeout，DeepSeek API 抖动；达标 ≤1/10） |
| median latency | 12.1 s（API 顺时段，见下方 caveat） |
| p95 latency | 27.0 s（max 32.2 s，min 8.7 s；n=9，不含 err 题 q03） |
| q04 L2 / L3 / L4 | no / no / no（top5 仅 079::0119 进，**非证据段**；0004/0005 未召回，模型拒答） |
| q08 L3 / L4 | no / no（top5 = 026 四段 + 041::0051，026::0172 未进） |
| usable_for_demo | 需人审（q04 仍拒答；与 A2 同配置仅 recall 不同却失去翻盘） |
| not_hallucinated（refuse 题） | 2 / 2（q09 干净拒答；q10 解释式拒答） |
| 备注 | **关键对照**：与 A2 唯一差别是 recall 20→10，q04 即从「翻盘正答」掉回拒答。recall10 召回池里 079 核心证据段 0004/0005 双双未进，ref-filter 只能把非证据段 079::0119（图7 scenario 讨论）排进 top5 → 模型无数字可用、拒答。**这证明 ref-filter 解 q04 依赖 recall 深度**，不是 ref-filter 单独起效。q03 ReadTimeout 系 API 抖动（与配置无关）。**延迟 caveat**：本组在 DeepSeek API 恢复后的顺畅时段跑，单题 LLM 远快于 A1/A2 时段（q04 仅约 10s），故 12.1s 不能与 A2 的 28.8s 直接相减归因于 recall 深度——延迟差里混入了 API 时段差异，严格对照需同时段复跑。 |

### 2.7 Run C1 — recall8 / top_n=5 / ref-filter off

| 项 | 值 |
|---|---|
| run_id | `20260615-191741`（jsonl `mini_eval_20260615-191741.jsonl`） |
| 配置 | recall=8, top_n=5, ref-filter=off |
| 跑完日期 | 2026-06-15 |
| HTTP errors | 0 / 10（CLEAN） |
| median latency | 12.0 s（API 顺时段，见 caveat） |
| p95 latency | 21.9 s（max 22.8 s，min 9.3 s；n=10） |
| q04 L2 / L3 / L4 | no / no / no（recall8/off，top5 全 041 + 067，仍拒答） |
| q08 L3 / L4 | no / no（top5 含相邻段 026::0173，但**非** 026::0172） |
| usable_for_demo | 需人审（recall8 baseline；q04 仍拒答） |
| not_hallucinated（refuse 题） | 2 / 2 |
| 备注 | recall8 最浅档基线。q04 在 off 配置下必拒答（079 正文段进不了候选，与 A1/A3 同理）。q08 召回了与证据段相邻的 026::0173，但目标 026::0172（含 R²/RMSE）仍未进——印证 026::0172 在 embedding 层 rank 较深（约 17），recall8 直接召不到。**延迟 caveat 同 B2**：API 顺畅时段，不能与 recall20 各组直接比延迟。 |

### 2.8 Run C2 — recall8 / top_n=5 / ref-filter on / overfetch=10

| 项 | 值 |
|---|---|
| run_id | `20260615-192009`（jsonl `mini_eval_20260615-192009.jsonl`） |
| 配置 | recall=8, top_n=5, ref-filter=on, overfetch=10 |
| 跑完日期 | 2026-06-15 |
| HTTP errors | 0 / 10（CLEAN） |
| median latency | 13.4 s（最快档；API 顺时段，见 caveat） |
| p95 latency | 18.6 s（max 18.9 s，min 9.8 s；n=10） |
| q04 L2 / L3 / L4 | 部分 / no / no（top5 仅 079::0004(r1) 进，**0005 未进**，单段证据不足，模型仍拒答） |
| q08 L3 / L4 | no / no（026::0172 未进） |
| usable_for_demo | 需人审（q04 仍拒答） |
| not_hallucinated（refuse 题） | 2 / 2 |
| 备注 | **预写假设被证实**（即本节 skeleton 阶段预写的待验证假设）：recall8 下 overfetch=10 不够深，ref-filter 只把 079::0004 单段拉进 top5、漏掉 0005，**单段证据不足以支撑作答 → q04 掉回拒答**。结合 B2（recall10 同样失败）与 A2（recall20 成功），三档构成清晰梯度：**079::0004+0005 这对证据段只有 recall20 能同时召回并通过 rerank，ref-filter 的 q04 收益强依赖 recall 深度**。延迟为全矩阵最低（med 13.4 / p95 18.6s），但 caveat 同上：API 顺畅时段，延迟优势不能纯归因于 recall8。 |

## 3 总览（go/no-go）

跑完所有 8 组后填。用于：
1. 决定是否把 ref-filter / overfetch / top_n / recall 的某个组合定为 demo 默认。
2. 决定是否需要进入 reranker numeric boost（Step 2）或 evidence recall 改造（Step 3）。
3. 判断 M1.4-c DoD §6.2 / §6.3 是否达成。

| Run | HTTP err | median lat | p95 lat | q04 L4 | q08 L3 | usable | not_hallu | 推荐 |
|---|---:|---:|---:|---|---|---:|---:|---|
| A1 | 0 | 27.0s | 53.9s | no | no | 需人审 | 2/2 | baseline；q04 漏 [79]、q08 漏 026::0172 |
| A2 | 0 | 28.8s | 32.7s | yes | no | 需人审 | 2/2 | q04 翻盘（079::0004/0005 进 top1/2，数字 grounded）；q08 不变；无误杀 |
| A3 | 1 | 27.5s(去抖24.9) | 83.1s(去抖32.9) | no | no | 需人审 | 2/2 | top_n7 不解 q08（026::0172 仍未进）、不解 q04；q05 撞 API 502 |
| A4 | 1 | 32.8s† | 138s† | yes | no | 需人审 | 2/2 | q04 翻盘在 top7 仍稳；top7 不解 q08；†延迟撞 API 抖动 |
| B1 | 0 | 16.4s* | 42.8s* | no | no | 需人审 | 2/2 | recall10/off baseline；q04 拒答；与 B2 对照证明 recall10 档 ref-filter 无 q04 收益 |
| B2 | 1 | 12.1s* | 27.0s* | no | no | 需人审 | 2/2 | recall10 下 ref-filter 失效：q04 掉回拒答（0004/0005 未召回） |
| C1 | 0 | 12.0s* | 21.9s* | no | no | 需人审 | 2/2 | recall8 baseline；q04 拒答；q08 召回相邻 0173 非 0172 |
| C2 | 0 | 13.4s* | 18.6s* | no | no | 需人审 | 2/2 | recall8+rf：仅捞到 079::0004 单段，q04 仍拒答；延迟最低 |

> `*` B2/C1/C2 的延迟在 DeepSeek API **恢复后的顺畅时段**测得（单题 LLM 远快于
> A1–A4 时段，q04 低至 ~10s），**不能**与 recall20 各组（A1/A2 测于较慢时段）直接相减
> 把差异归因于 recall 深度。recall 深度对延迟的净效应需同时段复跑才能确认。本轮延迟仅
> 支持「recall 越浅候选越少、reranker 越快」的定性方向，不支持定量加速比。

DoD 对照（来自 spec §6.2 / §6.3）：

评估锚定**推荐配置 A2（recall20 + ref-filter on）**——它是全矩阵唯一让 q04
evidence-level 翻盘的配置（A4 同质但 top7、延迟更高）。

| 指标 | 目标 | 最终结果（A2 为准） | 通过 |
|---|---|---|---|
| HTTP errors | ≤ 1 / 10 | 0 / 10（A2；全矩阵重跑后各组均 ≤ 1/10） | ✅ |
| not_hallucinated | 2 / 2 | 2 / 2（q09 干净拒答、q10 解释式拒答；**全 8 组一致**） | ✅ |
| usable_for_demo | ≥ 5 / 10 | **待人审**（report 全程标「需人审」，不自动判定） | ⏳ 待人审 |
| q01–q08 L4 命中 | ≥ 5 / 8 | **仅完整追踪 q04(L4=yes)/q08(L4=no)**；余 6 题需按 `evidence_audit.md` evidence chunk 逐题核 | ⏳ 待核 |
| recall 10 vs 20 延迟 | 有对照记录 | ✅ 有 recall 20/10/8 三档记录（**定性**：越浅越快；定量加速比因 API 时段差异不成立，见上 caveat） | ✅（定性） |

### 3.1 本轮判断（go/no-go 数据输入，不预写泛化结论）

1. **q04 evidence-level 翻盘已实现，但前提严格**：q04 答出 ⟺ `recall20 ∧ ref-filter on`
   （仅 A2 / A4）。ref-filter 是**必要不充分**——它删掉 References 段腾出位置，但只有
   recall20 的召回池能同时容纳 079::0004（6.2 / 4%）+ 0005（2× / 33%）两段核心证据；
   recall10 / 8 即便开 ref-filter 也捞不全 → 拒答（B2 / C2 实证）。
2. **q08 未解，廉价路线已排除**：top_n 加深（A3 / A4 top7）对 026::0172 无效，recall8 / 10
   更召不到（embed rank ≈ 17）。下一刀确定走 Step 2（reranker numeric/evidence boost 或更深
   recall），不再在 top_n / ref-filter 上找。
3. **质量 ↔ 延迟硬权衡**：唯一质量配置（A2 / A4 = recall20）median ~28–33s；低延迟档
   （recall8 / 10）~12–16s 但废掉 q04。延迟数字含 API 时段差异，仅支持定性方向。→ demo 默认
   倾向 **A2（质量优先）**，recall10 仅作「可接受丢 q04 的快速备选」；终判见 `review.md`。
4. **DoD 未闭环**：`usable_for_demo` 与 q01–q08 L4 完整版需人审 + `evidence_audit.md` 逐题核；
   本报告仅完整闭环 q04 / q08 两题。**不得据此宣称「质量 DoD 通过」**。
5. **稳定性风险（本轮新观察）**：A4 / B1 / B2 首轮均撞 DeepSeek API 502 / ReadTimeout，重跑才
   达标。当前 demo 路径对 LLM 端抖动**无重试 / 超时降级**，是真实 demo 风险，建议进 backlog
   （API 重试 + 超时友好降级）。
6. **in-sample 声明**：以上全部基于 q01–q10 frozen set，**不可外推**；泛化判断留 `review.md`。

## 4 Decision Log

每跑完一组立刻记一行：「这个结果意味着下一步怎么走」。不预写。

| 日期 | 触发 | 观察 | 下一步 |
|---|---|---|---|
| 2026-06-03 | A1 baseline 跑完 | 10 ok/0 err；median 27s / p95 54s。q04 rerank 后 top5 零 [79]（连 References 段都没召回），模型正确拒答；q08 top5 缺 026::0172。refuse 2/2 正确。baseline 锚点成立。 | 跑 A2（ref-filter+overfetch10），重点看 q04：ref-filter 在 top20 删掉 079 References 后，更深 overfetch 能否把 079 正文段（0004/0005/0083）拉进 top5。若 A2 q04 仍零 079，说明 overfetch=10 在生产路径召回不到正文段，需回到 context_debug 复核 raw recall 深度。 |
| 2026-06-03 | A2（ref-filter on/overfetch10）跑完 | 10 ok/0 err；median 28.8s（vs A1 27.0s，持平）。**q04 翻盘**：079::0004/0005 进 rerank top1/top2，模型给出 6.2 kg N ha⁻¹ / 2× / 33% 且逐字 grounded（L2 反推 / L3 / L4 = yes）。q08 top5 与 A1 逐字相同、仍缺 026::0172（ref-filter 不触及 reranker miss，符合假设）。误杀核查：未见 ref-filter 删任一题先前可用的正文段；q09/q10 拒答仍干净。q03 仍未答出（A1 亦然），属其自身 recall miss。 | A2 已证明「ref-filter 关键不是单纯删 References，而是 overfetch 后正文证据能进候选并通过 rerank」。下一步：(1) 跑 A3/A4 看 top_n=7 是否顺带救 q08（reranker miss）或徒增延迟；(2) 跑 B1/B2 看 recall10 下 ref-filter 收益是否仍稳；(3) **DoD 缺口**：spec §6.3 要求 recall 20/10/8 三档，当前矩阵只有 20/10——已决定补 recall8（C1/C2），见矩阵 §1 与 §2.7/§2.8。 |
| 2026-06-03 | A3（top_n7/off）跑完 | q08 廉价试探**失败**：top_n 加深到 7 仍未把 026::0172 拉进候选（补的是他源 041::0051/043::0074），证明 top_n 替代不了 reranker numeric boost。q04 top7/off 仍零 079、仍拒答 → 解 q04 靠 ref-filter 而非 top_n 深度。q05 撞 DeepSeek 502（API 端，1/10 仍达标）；q07/q10 两个 80s+ 抖动尖峰污染 p95，去抖后 24.9/32.9s。 | q08 正式从「top_n 加深」路线排除，留给 Step 2（reranker numeric/evidence boost）。A4（top7+ref-filter）只需确认 ref-filter 收益在 top7 仍在、不被更深 top_n 稀释即可，不指望它救 q08。继续 B/C 档看延迟与 recall 深度对 ref-filter 收益的影响。 |
| 2026-06-15 | B2/C1/C2（recall10/8 档）跑完 | **本轮最重要结论 — ref-filter 解 q04 的收益强依赖 recall 深度**。同为 ref-filter on + overfetch10，q04 随 recall 退化：A2(recall20) 0004+0005 双段进、答出完整数字 ✅ → B2(recall10) 仅非证据段 079::0119 进、拒答 ❌ → C2(recall8) 仅 0004 单段进、拒答 ❌。根因：079 的两段核心证据（0004 含 6.2/4%、0005 含 2×/33%）需同时在召回池才够模型作答，而浅召回（10/8）容不下。q08 全档仍 miss 026::0172（recall8 更没机会，它在 embed rank≈17）。B/C 档 refuse 2/2 干净。延迟 12–13s 但混入 API 顺畅时段，不作定量加速结论。 | demo 配置选型出现**质量↔延迟硬权衡**：唯一让 q04 翻盘的是 recall20+ref-filter（A2，~28s），而低延迟档（recall8/10，~12s）会废掉 q04 修复。建议把 **A2 定为质量优先 demo 默认**，recall10/8 仅作「可接受丢 q04 的快速档」备选，最终判断留 review.md。下一步：等 A4/B1 重跑（首轮撞 API 故障）补全矩阵，再结 DoD 与 go/no-go。 |
| 2026-06-15 | A4/B1 重跑达标，矩阵 8/8 闭环 | A4 重跑 9ok/1err(q07 API)：q04 翻盘在 top7 仍稳、q08 仍 miss 026::0172。B1 重跑 10ok/0err：recall10/off 下 q04 拒答，与 B2 对照证实 **recall10 档 ref-filter 无 q04 收益**。全矩阵定论：**q04 答出 ⟺ recall20 ∧ ref-filter on**（仅 A2/A4）。首轮 A4/B1/B2 撞 API 502/ReadTimeout，废数据存 `.apifail`。 | 矩阵闭环，report §2/§3 填毕。交棒 `review.md`：(1) 据 §3.1 判 demo 是否进 M1.5（A2 质量优先 vs 低延迟丢 q04）；(2) `usable` 与 q01–q08 L4 完整版需人审 + `evidence_audit.md` 逐题核，本报告未闭环；(3) API 抖动重试/降级进 backlog。提交按模块拆：report 回填 + `run_eval_matrix.sh`。 |

## 5 Notes

- run_id 命名沿用 `context_debug.py`：`{YYYYMMDDTHHMMSS}-recall{N}-top{n}`；
  当 ref-filter 启用时，在备注里手工标注 `+reffilter-of{N}`。
- 所有 latency 数据来自 mini eval runner，不来自 `context_debug.py`
  （后者不调 LLM）。
- q04 / q08 的 L 层判定以 evidence_audit.md 表二为准，evidence chunk id
  即时核对、不靠记忆。
- 本报告只承载 in-sample 数据；任何"该方案可泛化"的判断必须留到 review.md
  写明 caveat。
