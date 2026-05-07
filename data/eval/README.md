# data/eval/

M1.4-a Mini 评测的题集与人工评分文件。

## 目录约定

| 文件 | 入仓 | 用途 |
|---|---|---|
| `mini_questions.yaml` | ✅ | Mini 评测题集（10 题），M1.4-b 时会扩展为超集 |
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

类别配额（M1.4-a 固定 10 题）：

| category | 数量 | 说明 |
|---|---|---|
| `factual` | 4 | 单点事实问答 |
| `concept` | 2 | 概念解释，需整合多 chunk |
| `synthesis` | 1 | 跨论文比较，期望召回 ≥2 source |
| `citation_check` | 1 | 重点核查 `[N]` 与 citations 数组对应 |
| `refuse` | 2 | 不在范围，期望拒答 |

## 跑评测

前置：

1. `data/papers/` 已落 6–8 篇真实 PDF（参见 `data/papers/README.md`）
2. 已清空旧索引并基于真实 PDF 重建（同上）
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

## 与 M1.4-b 的契约

- `id` 命名稳定，M1.4-b 题集是 M1.4-a 的**超集**（追加，不重排）
- 类别字符串可以新增，但已有 5 个不重命名
- judged 文件 schema 可以新增字段（如 LLM-as-judge 评分），不删旧字段
