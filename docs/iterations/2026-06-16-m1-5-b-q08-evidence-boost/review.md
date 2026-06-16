# 审查文档 — M1.5-b q08 Evidence Boost

> 机审（代码正确性 / 边界 / 回归）+ 人审（设计判断 / 泛化 caveat / 残留风险）。
> 结论：**通过，可 push**。范围严格限定在 reranker 后处理，未触检索主链路与 M1.5-a
> 稳定性链路。**所有量化结论 in-sample，不外推。**

## 1 元信息

| 字段 | 值 |
|---|---|
| 审查对象 | `ef5c9a1^..0eee7b3`（8 commit） |
| 配套 | `spec.md` / `report.md` |
| 审查日期 | 2026-06-16 |
| 范围红线 | 只动 reranker 后处理；不改 embedding/recall/ref-filter；不改 RAG/reranker opt-in 语义；不改 M1.5-a 稳定性链路 |

## 2 变更范围清单

| 文件 | 变更 | 影响面 |
|---|---|---|
| `src/rag/numeric_boost.py`（新） | gate + density + banded boost（纯函数） | 无副作用，可单测 |
| `src/rag/retriever.py` | reranker 分支内调 boost；新增 3 个 ctor 参数（默认关） | 仅 reranker 路径；既有调用方零变化 |
| `src/config.py` | 新增 3 个 setting（默认开 0.445/0.30） | 仅 RAG+reranker 启用后生效 |
| `src/main.py` | 注入 setting + startup 日志加 numeric_boost | 仅日志 + 注入 |
| `scripts/context_debug.py` | `--numeric-boost/--no-...` + band flag + 审计字段 | 离线工具，不入生产 |
| `.env.example` | 文档化新 block | 文档 |
| `data/eval/smoke_b_questions.yaml`（新）/ `scripts/run_smoke_b.sh`（新） | q08 live gate | 本地手动 gate，非 CI |
| `tests/test_numeric_boost.py`（新）/ `tests/test_retriever.py` | 单测 + 接线测试 | 测试 |

## 3 验证证据清单

| 证据 | 出处 | 结果 |
|---|---|---|
| 单测 | `pytest test_numeric_boost.py` | 11 passed |
| 回归 | `pytest -k "not live"` | 134 passed / 4 deselected |
| DoD-1/2 检索层 | context_debug off vs banded-on，q01–q10 | 唯 q08 top5 变；026::0172 进 final_context |
| DoD-3 live | smoke B（生产默认） | PASS 30s，引 026::0172（首跑 504 抖动重试通过） |
| DoD-4 | grep 机制文件 | clean（仅注释） |

## 4 DoD Review

| DoD | 判据 | 结论 |
|---|---|---|
| 1（主，检索） | 026::0172 进 q08 top_n / final_context | ✅ |
| 2（回归，检索） | 无题丢关键证据段；q04 保留 079::0004/0005；拒答题不污染 | ✅（唯 q08 变） |
| 3（旁证，live） | q08 答出 grounded R²/RMSE/IA 且非拒答 | ✅（旁证性，受 API 抖动影响，已记） |
| 4（防过拟合） | 机制无 q08/目标/期望字面量；词表通用 | ✅ |

## 5 关键审查判断

### 5.1 band 是必要的第二旋钮，不是过度设计

用户初始约束「只回调 weight 或 query gate」。DoD-2 实测证明对 q01 **二者皆无解**（weight
区间空集；gate 必开）。band 是对 boost 机制本身的**有原则**补强（"只重排相关竞争者"），仍在
`numeric_boost.py` 内，未触检索主链路——符合约束精神。已与用户对齐后落地。

### 5.2 标定可解释、可复现

weight 由全候选实际重排扫描得出（非 raw gap）；band 由 q08 含/q01 排的 gap 区间定。两者
默认值连同推导写入 report §3，换 reranker 模型需重标定（见 §6 风险）。

### 5.3 副作用已界定

043::0074 进 q08 top5 是通用 boost 的机制性结果（合法统计段），DoD-2 证其只影响 q08，
smoke B 证 q08 答案未混源。记录在案，非缺陷。

### 5.4 in-sample caveat（人审重点，不得弱化）

density 词表/分量权重、weight、band 全部在 q01–q10 上观察标定，**未做外样本验证**。本轮
**不声称泛化**；「该机制对集外定量题同样只抬相关数据段」是假设，待 20–30 题扩评（独立迭代）
检验。boost 默认开是基于「in-sample 仅 q08 受影响、其余九题零变化 + 一次 live 旁证」的工程
判断，非泛化证明。

## 6 风险与回滚

| 风险 | 缓解 |
|---|---|
| reranker logit 尺度漂移使 weight/band 失准 | 默认值记于 report；模型不变期内稳定；换模型重标定 |
| 集外定量题被无关数据段污染（泛化未验） | band 已挡 in-sample 尾部；扩评前保留 caveat；可调小 weight/band |
| live LLM 抖动致 smoke B 偶发 504 | 非本轮引入（M1.5-a 有界超时契约正确生效）；旁证性，不阻断检索层 DoD |
| **回滚** | `RAG_NUMERIC_BOOST_ENABLED=false` → 即回 M1.5-a A2 默认，零代码回滚 |

## 7 审查结论

**通过，可 push。** 检索层两条 gate（DoD-1/2）确定性通过，live 旁证（DoD-3）通过，防过拟合
边界（DoD-4）守住。范围未越界，回滚成本为零（一个开关）。唯一需在后续迭代闭合的是
**外样本泛化验证**（扩评），本轮已显式标注 in-sample caveat，不冒充泛化结论。
