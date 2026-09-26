# data/eval/

评测题集与人工评分文件。

## 目录约定

| 文件 | 入仓 | 用途 |
|---|---|---|
| `mini_questions.yaml` | ✅ | M1.4-a 冻结 mini 题集（10 题），后续调参对照用 |
| `m16_questions.yaml` | ✅ | M1.6 扩展题集（24 题）；后续已参与定向优化，现作为回归集 |
| `mini_eval_<runid>_judged.yaml` | ✅ | 人工评分结果（小，便于答辩追溯） |
| `README.md` | ✅ | 本文件 |

> Runner 原始输出 `mini_eval_<runid>.jsonl` 落在 `backend/var/eval/`，受
> `backend/var/` ignore 规则覆盖，**不入库**。

## 题集 schema

```yaml
version: 1
questions:
  - id: q01                  # 稳定 id，不要改名（M1.4-b 会扩展为超集）
    category: factual         # factual | concept | synthesis | refuse | citation_check
    query: 中文题面            # <= 200 chars
    expected_points:           # 人工评分对照用，runner 不读
      - 要点 1
    should_refuse: false       # true 表示期望拒答
    notes: 备注                # 可选，写"为什么选这道""指向哪篇论文"
```

M1.4-a 类别配额（固定 10 题）：

| category | 数量 | 说明 |
|---|---|---|
| `factual` | 4 | 单点事实问答 |
| `concept` | 2 | 概念解释，需整合多 chunk |
| `synthesis` | 1 | 跨论文比较，期望召回 ≥2 source |
| `citation_check` | 1 | 重点核查 `[N]` 与 citations 数组对应 |
| `refuse` | 2 | 不在范围，期望拒答 |

M1.6 题集覆盖：

| category | 数量 | 说明 |
|---|---:|---|
| `factual` | 15 | 新增论文中的单点和多点事实 |
| `citation_check` | 3 | 重点核查数值事实与 citations 数组是否一致 |
| `synthesis` | 4 | 要求至少两篇 source 的综合 |
| `refuse` | 2 | 扩展语料边界附近的拒答 |

## 跑评测

前置：

1. `data/papers/` 已放入本地真实 PDF（M1.6 当前整理为 90 篇，参见 `data/papers/README.md`）
2. 已基于目标语料重建 Chroma 索引；M1.6 demo 默认使用 `backend/var/chroma_m16`
3. backend 已启动且 `RAG_ENABLED=true`：

   ```bash
   cd backend
   uv run uvicorn src.main:app --reload
   ```

4. DeepSeek API key 有效

跑：

```bash
cd backend
uv run python scripts/run_mini_eval.py \
  --questions ../data/eval/mini_questions.yaml \
  --api http://localhost:8000 \
  --out var/eval
```

M1.6 扩展题集：

```bash
cd backend
uv run python scripts/run_mini_eval.py \
  --questions ../data/eval/m16_questions.yaml \
  --api http://localhost:8000 \
  --out var/eval \
  --timeout 180
```

输出：

- 终端逐题打印 `[ok]` / `[err]` + 耗时
- `backend/var/eval/mini_eval_<runid>.jsonl` 每行一题完整记录
- 末尾打印 `summary: X ok, Y err, total Z`

`<runid>` 形如 `20260507-153000`，启动时打印；用同一个 runid 写 judged.yaml 文件名以便配对。

## 人工评分流程

1. 打开对应 `backend/var/eval/mini_eval_<runid>.jsonl`
2. 逐行核对 `answer` / `citations.snippet`，对照 `mini_questions.yaml` 的 `expected_points`
3. 新建 `mini_eval_<runid>_judged.yaml`，按下表 4 维填二值

   | 维度 | true 的判定 |
   |---|---|
   | `relevant` | 答案围绕题面核心，没跑题 |
   | `cited` | 至少 1 条 citation 与答案中的事实对应（refuse 题可为 false） |
   | `not_hallucinated` | 答案中所有具体事实在召回 chunks 里都能找到支持 |
   | `usable_for_demo` | 综合判断：能不能给 HR 看 |

4. 文件末尾填一份 `summary` 段（spec §4.3 模板）

## 通过阈值（M1.4-a DoD）

- `usable_for_demo` ≥ 7 / 10
- `refuse` 题里 `not_hallucinated` 必须 2 / 2（应拒答**绝不允许胡编**）
- 总 HTTP 错误 ≤ 1 / 10

未达阈值不进入 M1.5-Demo。详见迭代 spec §5.3。

## M1.6 判读建议（首次评测时的流程）

- 先跑完整 `m16_questions.yaml`，再人工写 `mini_eval_<runid>_judged.yaml`。
- 不用 M1.6 首轮结果即时调参；先把失败分为 retrieval miss、wrong source、
  numeric extraction error、citation mismatch、over-refusal、under-refusal。
- `synthesis` 题要求至少两个不同 source 支撑；只答单篇论文即使事实正确也不能算完全 usable。
- `citation_check` 题重点查答案中的 `[N]` 是否能对应 citations 数组里的实际证据。

当前 M1.6 追溯文件：

| runid | raw JSONL | judged YAML | 结果 |
|---|---|---|---|
| `20260708-174735` | `backend/var/eval/mini_eval_20260708-174735.jsonl` | `mini_eval_20260708-174735_judged.yaml` | 首轮 baseline，5/24 usable，2/2 refuse safe |
| `20260710-161708` | `backend/var/eval/mini_eval_20260710-161708.jsonl` | `mini_eval_20260710-161708_judged.yaml` | retrieval hint pass 后，14/24 usable，2/2 refuse safe |
| `20260710-172602` | `backend/var/eval/mini_eval_20260710-172602.jsonl` | `mini_eval_20260710-172602_judged.yaml` | follow-up numeric/synthesis alias pass 后，21/24 usable，2/2 refuse safe |

## M2.0 评测定位

M1.6 的 24 题已用于检索提示和答案优化，21/24 是开发侧自评结果，
不再作为独立测试集或泛化准确率。旧题目与评分原件保留作回归记录。

M2.0 分别准备：旧 RAG 回归集、10 个可修改的试评任务、正式比较前冻结的
未参与调参测试集。试评任务需经熟悉模型的人确认必答要点、依据和结论边界，
未确认项保持待审核，不能由模型生成的答案替代审核。

评价正确性、完整性、证据支持和可理解性；新手试用另记任务完成、卡点、
耗时与满意度。无法判断及超出专长单列，不当作通过。
比较旧 RAG 与新版时固定资料与模型条件；比较手册与助手时记录材料版本、
任务顺序和先验经验，避免练习效应被误计为助手收益。

详见 [M2.0 spec](../../docs/iterations/2026-09-26-m2-0-model-assistant/spec.md)
及 [10 个试评任务草案](../../docs/iterations/2026-09-26-m2-0-model-assistant/pilot-tasks.md)。

## 与后续迭代的契约

- `mini_questions.yaml` 的 `id` 命名稳定，不重排、不改义
- `m16_questions.yaml` 保留为 M1.6 扩展语料回归集，不回填到旧 mini set
- 类别字符串可以新增，但已有 5 个不重命名
- judged 文件 schema 可以新增字段（如 LLM-as-judge 评分），不删旧字段
