# Evidence Audit — M1.4-c

This file tracks why the frozen M1.4 questions fail after M1.4-b reranking.
Use it to decide whether a fix belongs in retrieval, context packing, or answer
extraction/prompting.

## Legend

| Label | Meaning |
|---|---|
| evidence recall miss within source | 期望 paper 召回了，但 evidence chunk 没召回 |
| reference-section false positive | 召回的 chunk 是 paper 的 References 段，不是正文 |
| mixed recall + reranker miss | 部分 evidence chunk 召回但被 reranker 压下，其余 evidence chunk 未召回 |
| reranker evidence miss | evidence chunk 在 embed top20 但未进 reranker top5 |
| chunk boundary / table preservation risk | evidence 被 chunk 切散（相邻段拆开、表格碎片化等） |
| packing miss | evidence 进了 top5 但被 `format_context` 字符预算截断（M1.4-c 目前无单题证据） |
| retrieval miss（旧） | 已废弃，按上述更细的分类标 |
| extraction miss（旧） | 已废弃，按上述更细的分类标 |
| latency risk | answer path is too slow for demo use |

v1.0 → v1.1 演化说明：原 `hypothesis: <label>` 约定（仅基于 M1.4-b 答案文本推测）
已被 `context_debug.py` dump + 一次性 full chunk lookup（2026-05-21）替换。第一张
表 Failure class 列现在均为基于完整 chunk 文本的确认结论。

## Current Context Pipeline

Current code path:

```text
ChatService.answer()
-> Retriever.retrieve(query, k)
-> prompt.build_messages(query, retrieved, max_context_chars)
-> prompt.format_context(retrieved, max_chars)
```

`format_context` currently keeps retrieved chunks in ranking order and stops when
the next block would exceed `max_context_chars`. It does not rebalance by source,
does not prioritize numeric/table evidence, and does not guarantee source
diversity for synthesis questions.

## Frozen Question Audit

数据来源：`backend/var/context_debug/20260521T181424-recall20-top5/`
（三层 dump JSON + `full_lookup.txt` 完整 chunk 文本与 token check 输出，均 gitignored）。

| QID | Expected source | dump 证据（M1.4-b + 2026-05-21 full chunk lookup） | Failure class | M1.4-c action |
|---|---|---|---|---|
| q02 | [43] Liang 2020 | top20 有 4 个 [43] chunks（ranks 3 / 7 / 18 / 20），全为 Intro / Discussion 段（87%/74% vs CK、36% vs farmer practice），**不含** drip+optN vs furrow+conv 的 41/60/68/68% 比较段。Final context 含错误数字（87%/74%），模型按 context 回答。 | evidence recall miss within source | 定位 [43] 中含 41/60/68% 对比的 chunk id（推测在 Results 段）；考虑 query expansion 触发 Results / Table 段召回；reference filter 在本题次要。 |
| q04 | [79] Huang 2024 | top20 的 3 个 [79] chunks（ranks 8 / 12 / 14）**全为 References 段**（079::0174 / 0166 / 0155）。真正 evidence 段 079::0004 / 0005 / 0083（6.2/3.1 kg N ha−1、33%、lateral seepage）已 ingest（[79] 共 175 chunks）但未召回。 | reference-section false positive | **顶优先级** — reference-section 过滤（ingest metadata flag 或 retriever 后处理）；复测后预期 [79] 正文 chunk 冒入 top20。失败再上 query expansion / multi-query。 |
| q05 | [26] Liang 2016 | top20 有 12 个 [26] chunks。026::0030（modules 列表）在 rank 14 ✓；026::0033（HYDRUS / DAISY 借鉴句）未召回；026::0031 / 0032 是过渡段。Sanity check 已确认 0033 在索引中。 | evidence recall partial miss within source; chunk adjacency split | 调查为何 0033 排在 top20 外（embedding 相似度 vs 0030 差距）；考虑 query expansion（"borrowed from" / "based on"）或相邻 chunk 合并。 |
| q06 | [79] Huang 2024 | 唯一 1 个 [79] chunk（079::0091，rank 12）含 lateral seepage 机制段，被 reranker 压出 top5；含 1.7/0.7 mg N/L 数字的 chunk（079::0086）未召回。 | mixed: reranker drop + evidence recall miss | mechanism：reranker 调参 / numeric-token boost；numbers：query 触发 "mg N L−1" 召回，或与 mechanism 段合并。 |
| q07 | synthesis（[41]/[43]/[60]/[63]） | top20 涵盖 5/6 期望 source 但只有 [60]（6 chunks）含 substantive evidence（green manure / milk vetch ✓）；[41] 2 chunks 缺 SNR / 5:3:1 / 231 / 155；[43] 7 chunks 缺 41% / drip（同 q02）；[63] 1 chunk 缺 180 / 200 / sandy / clay loam。 | synthesis evidence recall miss across [41]/[43]/[63] | 优先解 q02（同时改善 [43] 在 q07 的表现）；逐 source evidence 召回流程；packing 重排无法救——chunks 里没字。 |
| q08 | [26] Liang 2016 | 026::0172（rank 17）含完整答案：「determination coefficient... 0.84–0.99... RMSE 243–1097 kg ha−1... IA all over 0.70」，但未进 reranker top5。DBW / 3220 字样在 top20 [26] chunks 里未现。 | reranker evidence miss within source | **顶优先级** — reranker 调参或后处理（numeric-token boost / `evidence_tokens` 重排）。DBW / 3220 detail 可能在 [26] 别的 chunk 里，需 spot-check。 |

## Evidence-Level Next Checks

四级指标定义见 spec §4.5。L2 = expected evidence chunk in embed top20；
L3 = in reranked top5；L4 = in final context。

### Reference Filter Sanity Run（2026-05-22）

实现路径：retriever 后处理（不改 ingest / 不重建 Chroma），默认关闭；debug 脚本用
`--reference-filter` 显式启用。判定规则基于 bibliography-like 文本特征（DOI/URL、
作者列表、年份、journal/page-range 组合），并在 Chroma recall 后、reranker 前过滤。

q04 复测结论：

- `overfetch=2`（raw recall 40）能删掉 reference 假阳性，但过滤后只剩 4 个正文候选，
  仍未拉到 [79] core evidence。
- `overfetch=10`（raw recall 200）后，过滤后的 embedding top20 含
  `079::0004` rank 2、`079::0005` rank 15、`079::0087` rank 19。
- 同配置跑 `context_debug.py` 后，reranker top5 / final context 命中：
  `079::0005` rank 1、`079::0004` rank 2、`079::0067` rank 4。

判定：reference filter + deeper overfetch 可把 q04 从 L2/L3/L4=no 提升为
L2/L3/L4=yes；但 `overfetch=10` 会提高 embedding recall 取数规模，需在 full mini eval
里检查延迟与误杀风险。

| QID | Evidence chunk(s) | L2 | L3 | L4 | Notes |
|---|---|---|---|---|---|
| q02 | TBD（推测在 [43] Results 段；需 spot-check 找 chunk id） | no | no | no | 4 个召回的 [43] chunks 都是 Intro / Discussion；真正 evidence chunk id 待定 |
| q04 | 079::0004, 079::0005, 079::0083（正文）；079::0086（q06 的 numbers） | baseline no；ref-filter+overfetch10 yes（0004 rank 2、0005 rank 15） | baseline no；ref-filter+overfetch10 yes（0005 rank 1、0004 rank 2、0067 rank 4） | baseline no；ref-filter+overfetch10 yes | reference filter 需配 deeper overfetch；overfetch=2 只删 refs 但拉不到 core evidence |
| q05 | 026::0030（modules 列表）+ 026::0033（HYDRUS / DAISY 借鉴句） | partial（0030 ✓ rank 14；0033 ✗） | partial（0030 进 top5） | partial（仅 0030） | 0033 未召回是关键，需进一步实验或合并相邻段 |
| q06 | 079::0091（mechanism）+ 079::0086（1.7/0.7 numbers） | partial（0091 ✓ rank 12；0086 ✗） | no（0091 未进 top5） | no | mechanism 和 numbers 拆开看 |
| q07 | 每 source 单独：[41] SNR chunk 未召回；[43] drip chunk 未召回（= q02）；[60] green manure chunks ✓；[63] texture chunk 未召回 | only [60] | only [60] | only [60] | synthesis 只能基于 [60] 单源，必失败 |
| q08 | 026::0172（R² / RMSE / IA 答案）；DBW / 3220 chunk TBD | yes（rank 17） | no | no | 干净 reranker miss，第一可救；DBW / 3220 detail 需 spot-check |

## Pending evidence_tokens（按 spec §4.5）

每题 must-have term 列表 + 变体，作为 evidence chunk hit 的可操作判据。下沉到
`data/eval/mini_questions.yaml` 之前先在此维护。

| QID | must-have（变体） | K |
|---|---|---|
| q02 | `41%`/`41 %`；`60%`/`60 %`；`68%`/`68 %`；`DON`；`drip`/`滴灌` | 3 |
| q04 | `1.7`；`0.7`；`lateral`/`侧向`；`6.2`；`3.1`；`33%`/`33 %`；`17%`/`17 %` | 3 |
| q05 | `HYDRUS`；`DAISY`；`PS123`/`PS 123`；`CERES`；`WHCNS`；`framework`/`Framework` | 3 |
| q06 | `1.7`；`0.7`；`mg N/L`/`mg N L`/`mg N L−1`/`mg N L-1`；`lateral`/`侧向` | 2 |
| q07 | 每 source 维护一组：[41] `5:3:1`/`1:1:4`/`SNR`/`231`/`155`；[43] `41%`/`drip`/`DON`；[60] `green manur`/`milk vetch`/`vetch`/`Astragalus`/`紫云英`；[63] `180`/`200`/`sandy`/`clay loam` | per-source K=1 |
| q08 | `R²`/`R2`；`RMSE`；`IA`；`DBW`；`0.84`；`0.99`；`243`；`1097`；`3220` | 4 |
