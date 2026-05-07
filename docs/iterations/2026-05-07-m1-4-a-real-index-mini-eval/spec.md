# 说明文档 — M1.4-a 真实论文索引 + Mini 评测

> 上承 M1.3.2（前端 chat UI 已稳定，能消费 `POST /api/chat`），
> 下接 M1.4-b（完整评测：20–50 题、`[N]` 合法性、token 预算、报告）
> 与 M1.5-Demo（cloudflared / frp 临时外链给 HR）。
>
> 本迭代不是"完整评测"。目标是**把 sample.txt 的 4 chunks 演示版升级为真实数据可用版本**，
> 用一个最小可信的 10 题评测验证"真实论文上能答、能引、错误率可接受"，
> 给 M1.5-Demo 的 HR 展示链接打质量底座。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代名 | m1-4-a-real-index-mini-eval |
| 日期 | 2026-05-07 |
| 涉及 commit | 待回填 |
| 文档版本 | v1.0（设计） |
| 父里程碑 | M1.4（评测） — 拆为 a / b 两步走 |
| 设计 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 范围

### 2.1 在做

把 RAG 链路从"sample.txt 4 chunks"升级到"真实论文 + 最小评测"：

1. **真实论文入库**
   - `data/papers/` 落 5–10 篇与本毕设主题相关的 PDF（氮淋失 / 氮循环 / 农田氮素管理 / WHCNS 等）
   - 用现有 `backend/scripts/index_papers.py` 批量索引（持久化目录 `backend/var/chroma`，collection 名 `papers`）
   - 入库后做一次基线快照（doc 数 / chunk 数 / 平均 chars / 截断率），写进 review.md
2. **题集 schema + 10 道 mini eval**
   - `data/eval/mini_questions.yaml`（仓内、可入库）：题面、类别、期望要点、是否应拒答
   - 类别覆盖：核心问答 / 概念解释 / 多文献综合 / 应拒答 / 引用一致性
3. **批量评测 runner**
   - `backend/scripts/run_mini_eval.py`：读题集 → 逐题调 `POST /api/chat` → 写一行 JSONL 到 `backend/var/eval/`
   - 每题记录：`question_id` / `category` / `query` / `answer` / `citations` / `retrieved_count` / `usage` / `latency_ms` / `model` / `error`（成功为 `null`）
   - 失败题不阻断全量；最后输出小结
4. **人工抽检评分**
   - 跑完后人工填一份 `data/eval/mini_eval_<runid>_judged.yaml`：每题打 `usable: true/false`，必要时加 `notes`
   - 评分维度收紧到 4 项（§5），目的是**先证明"能用"**，不追求复杂量化
5. **mini 评测报告**
   - `docs/iterations/2026-05-07-m1-4-a-real-index-mini-eval/report.md`
   - 含基线指标、题集说明、原始 JSONL 路径、人工评分结果、典型好/坏案例、HR demo 推荐题清单
6. **HR demo 推荐题清单（产出物）**
   - 在报告里挑 2–3 道"答得最像样"的题，标注预期回答要点 + 引用文件，作为 M1.5-Demo 演示脚本
7. **配套小修**
   - `data/papers/README.md`：补"如何放真实 PDF + .gitignore 已排除"操作指南
   - `data/eval/README.md`（新增）：题集 schema + runner 用法
   - 必要时给 `backend/scripts/index_papers.py` 加 `--clean` 选项（清空 collection 再重建），避免 sample 残留污染评测；如评估后觉得不必要，则不加

### 2.2 不在做（明确边界，挂账 M1.4-b 或 M1.5-Demo）

- ❌ 完整 20–50 题题集 → M1.4-b
- ❌ LLM-as-judge 自动评分 → M1.4-b（先用人工抽检，避免评分器本身成为新风险）
- ❌ `[N]` 引用合法性程序化校验（解析答案文本里的 `[N]` 并比对 citations 数组） → M1.4-b
- ❌ 精确 token 预算 / tokenizer 截断试验 → M1.4-b
- ❌ Reranker / 引用反查原文 → M1.4-b 之后评估
- ❌ Playwright E2E → M1.4-b 期一并评估
- ❌ 任何部署 / 公网链接 → M1.5-Demo
- ❌ 后端代码大改 → 本迭代后端只新增脚本与（必要时）`index_papers.py` 一个 flag，**不改** `chat_service` / `retriever` / 路由
- ❌ 前端任何改动 → 不动；HR demo 用现有 UI
- ❌ 改 chunker / embedder / chroma 参数（chunk size、top_k、context max_chars 等） → 评测就是用来验证当前默认值的，先观察再调；调整推到 M1.4-b 报告之后

### 2.3 计划变更清单

| 项 | 文件 | 内容要点 |
|---|---|---|
| 真实论文 | `data/papers/*.pdf` | 5–10 篇主题论文，**不入库**（已在 .gitignore） |
| 题集 | `data/eval/mini_questions.yaml` 新增 | 10 题 + schema 注释 |
| 评测说明 | `data/eval/README.md` 新增 | 题集结构、runner 用法、人工评分流程 |
| 数据目录说明 | `data/papers/README.md` 修改 | 补"放真实 PDF 的步骤" + 命名建议复读 |
| 评测 runner | `backend/scripts/run_mini_eval.py` 新增 | 读题集 → 调 chat → JSONL 落盘 → 终端小结 |
| 索引脚本（按需） | `backend/scripts/index_papers.py` 修改 | 视实际需求加 `--clean` flag；不加也行 |
| 评测产物（gitignored） | `backend/var/eval/*.jsonl` | runner 输出，不入库 |
| 评测人工评分 | `data/eval/mini_eval_<runid>_judged.yaml` 新增 | 每题 `usable` + `notes`，**入库**（小，便于追溯） |
| Mini 评测报告 | `docs/iterations/2026-05-07-m1-4-a-real-index-mini-eval/report.md` 新增 | 基线 + 题集说明 + 原始数据指针 + 人工评分汇总 + HR demo 题清单 |
| review.md | 同迭代目录新增 | 实现回填 + 机审/人审 |

## 3 关键判断

### 3.1 真实论文规模：先 5–10 篇，不一次到 90

ARCHITECTURE 里写过"基于 90 篇农学论文"，那是 M3 / M4 的目标。本迭代取下限：

- **5 篇**够覆盖 4–5 个子主题（氮淋失机制 / 影响因素 / 缓控释肥 / 田间管理 / WHCNS 模型），每篇切 30–80 chunks，整体 200–400 chunks，远超 sample 基线
- **10 篇**封顶，再多边际收益递减，且评测一次 LLM 调用成本上去了

> 决策：选 **6–8 篇**作为目标区间。少于 5 篇不开始评测；多于 10 篇推迟到 M1.4-b。

### 3.2 题集只 10 题，且类别明确

完整评测留给 M1.4-b 的 20–50 题。本迭代 10 题的分布：

| 类别 | 数量 | 目的 |
|---|---|---|
| 核心事实问答 | 4 | 期望召回 + 直接答案，验证主流程 |
| 概念解释 | 2 | 期望召回，但答案需要重组多个 chunk |
| 多文献综合 | 1 | 期望召回 ≥2 篇不同 source 的 chunks |
| 应拒答 / 不在范围 | 2 | 期望模型不胡编（"无相关资料" / 拒答） |
| 引用一致性人工抽检 | 1 | 答案里 `[N]` 与 citations 数组对应，本迭代靠人工看 |

**为什么 10 而不是 8 / 12 / 20**：
- < 8 题，类别覆盖不全
- > 12 题，人工评分时间从 ~30 分钟膨胀到 1 小时+，本迭代不值得
- 整十数便于报告里讲"7/10 通过"这类话

### 3.3 题集格式选 YAML 不选 JSON

- YAML 注释友好，可以在题面边注解"为什么选这道"，便于答辩文档复用
- 评测 runner 用 `pyyaml` 读；新增依赖小（pyyaml 是常见传递依赖）
- JSONL 留给 runner 输出（机器写）；YAML 留给题集与人工评分（人手写）

> 取舍：runner 入参 YAML / 出参 JSONL，分工清晰。

### 3.4 Runner 的最小职责

```
read_questions(yaml) → for q in questions: call_chat(q) → write_jsonl_line → print_summary
```

**不做的事**：
- 不重试。失败原样落盘，给人工分析
- 不并发。串行调用 `POST /api/chat`，避免触发 DeepSeek 限流；10 题 × 10–15s ≈ 2–3 分钟，可以接受
- 不内嵌评分。只跑只记，评分留给人工 / 后续 M1.4-b
- 不连 backend 模块。**通过 HTTP** 调真实运行的 backend，跟前端一样从外部接口验证；这样评测能反映线上行为

### 3.5 人工评分 4 维，二值化

不上 0/1/2 分制，避免主观空间太大：

| 维度 | 二值定义 |
|---|---|
| `relevant` | 答案是否回应了问题的核心（不跑题） |
| `cited` | 是否给出了 citations 且 ≥1 条与问题相关（应拒答题除外） |
| `not_hallucinated` | 答案中的事实是否都能在召回的 chunks 里找到支持（人工对照 snippet） |
| `usable_for_demo` | 综合判断：能不能给 HR 看（最严格的一项） |

`usable_for_demo == true` 视为"7/10 阈值"的计入项。

### 3.6 应拒答题的判定

- 题目示例：「请列出 2025 年诺贝尔化学奖获得者的主要工作」
- 期望行为：模型回答"知识库中没有相关资料" / "本系统聚焦氮素淋失，请提问相关主题"
- 不期望：模型胡编 / 强行用召回到的农业 chunks 拼一个答案

判定规则（人工）：
- 模型明确说"无资料 / 不在范围 / 无法回答" → `relevant=true`、`cited=false（合理）`、`not_hallucinated=true`
- 模型瞎答或硬塞农业内容 → 全部 false

### 3.7 评测产物落盘位置

| 产物 | 路径 | 是否入库 |
|---|---|---|
| 真实 PDF | `data/papers/*.pdf` | ❌（gitignored） |
| 题集 | `data/eval/mini_questions.yaml` | ✅ |
| 题集说明 | `data/eval/README.md` | ✅ |
| Runner 原始输出 | `backend/var/eval/mini_eval_<runid>.jsonl` | ❌（gitignored） |
| 人工评分 | `data/eval/mini_eval_<runid>_judged.yaml` | ✅ |
| 报告 | `docs/iterations/2026-05-07-m1-4-a-real-index-mini-eval/report.md` | ✅ |

`<runid>` 用 `YYYYMMDD-HHMMSS`，runner 启动时打印，方便人工评分文件配对。

> `backend/var/` 已被 .gitignore；新增 `backend/var/eval/` 子目录无需改 .gitignore。

### 3.8 不在 runner 里改 backend 配置

- backend 用什么 `RAG_ENABLED` / `RAG_CHROMA_DIR` / `chat_top_k`，由它启动时的 `.env` 决定
- runner 只调 `POST /api/chat`，**不**临时改 settings、**不**直接 import 后端模块
- 评测希望复现线上行为，配置变更应在启动 backend 之前完成

### 3.9 索引前是否清空 collection

可选两种方式：

1. **不清空**：`upsert` 已是幂等的（M1.2.3 spec），sample 数据被保留但 chunk_id 不冲突。代价是评测回答可能偶尔召回到 sample.txt（`derive_document_id` 按当前实现产出 `data/papers/sample`，`/` 在保留字符集里）。
2. **清空**：删除整个 `backend/var/chroma/` 后从零索引，干净但破坏性。

> 决策：**清空一次**再索引真实论文。理由：sample 在评测里是噪声，干扰人工判读；本迭代结束后真实论文已就位，sample 不再需要。
> 实现：spec 阶段不在脚本里加 `--clean`，分两步走（避免脚本侧引入新风险）。具体命令以 `data/papers/README.md` 为准，大致是：从 repo root 删 `backend/var/chroma`，再 `cd backend` 跑 `index_papers.py`。如果实际跑得不顺，再补 flag。
>
> 注意：Chroma 持久化结构是 `var/chroma/chroma.sqlite3` + 若干 UUID 目录，
> `papers` 是 **collection 名**而非目录。早期草稿里写的 `rm -rf var/chroma/papers` 是错的，**打不到任何东西**，
> 必须删整个 `var/chroma`（或在 Python 里 `client.delete_collection("papers")`）。

### 3.10 Backend 复用现有运行实例 / 现有索引参数

不为评测开第二个 backend 进程；不为评测改 `target-size` / `overlap` / `chat_top_k`。

理由：本迭代评测对象就是"现状能给 HR 看吗"，**改参数会让评测变成调参，失去基线意义**。调优放 M1.4-b 报告之后。

### 3.11 题面用中文，answer 也只评中文质量

- 题集里 query 全用中文
- 不混入英文题面（论文虽然多为英文，但 RAG 跨语言能力靠 BGE-large-zh，本迭代不验证英文 query）
- `not_hallucinated` 维度允许"答案中文 + 引用 snippet 英文" — 这是预期行为

## 4 实现细节

### 4.1 题集文件 `data/eval/mini_questions.yaml`

```yaml
# Mini eval question set for M1.4-a.
# Schema:
#   id: stable string id (used to join with judged.yaml)
#   category: one of [factual, concept, synthesis, refuse, citation_check]
#   query: 中文题面，<= 200 chars
#   expected_points: list of 中文要点 (人工对照用，runner 不读)
#   should_refuse: bool, true 表示这题期望模型拒答
#   notes: 可选，备注为什么选这道

version: 1
questions:
  - id: q01
    category: factual
    query: 氮素淋失主要受哪些环境与管理因素影响？
    expected_points:
      - 降雨 / 灌溉强度
      - 土壤质地与孔隙
      - 施肥量与施肥时间
      - 作物覆盖与吸收
    should_refuse: false
    notes: 主流程基线题，期望召回多篇

  # ... 其余 9 题在实现期补齐，分布按 §3.2 表
```

> 题面与要点在实现期由责任人结合手头论文敲定；spec 不预设全部 10 题以避免脱离实际语料。

### 4.2 Runner `backend/scripts/run_mini_eval.py` 草图

```python
"""Mini eval runner: read questions YAML → call POST /api/chat → write JSONL.

Usage:
    cd backend
    uv run python scripts/run_mini_eval.py \
        --questions ../data/eval/mini_questions.yaml \
        --api http://localhost:8000 \
        --out var/eval

Backend must be running with RAG_ENABLED=true and a populated chroma index.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", required=True, type=Path)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--timeout", type=float, default=60.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    data = yaml.safe_load(args.questions.read_text(encoding="utf-8"))
    questions = data["questions"]

    runid = datetime.now().strftime("%Y%m%d-%H%M%S")
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"mini_eval_{runid}.jsonl"

    print(f"[runid] {runid}")
    print(f"[out]   {out_path}")
    print(f"[api]   {args.api}")
    print(f"[count] {len(questions)} questions\n")

    ok = 0
    err = 0
    with httpx.Client(timeout=args.timeout) as client, out_path.open("w", encoding="utf-8") as fh:
        for q in questions:
            t0 = time.perf_counter()
            record: dict = {
                "runid": runid,
                "question_id": q["id"],
                "category": q["category"],
                "query": q["query"],
                "should_refuse": q.get("should_refuse", False),
            }
            try:
                resp = client.post(
                    f"{args.api}/api/chat",
                    json={"query": q["query"]},
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                record["latency_ms"] = latency_ms
                if resp.status_code == 200:
                    body = resp.json()
                    record.update(
                        answer=body["answer"],
                        citations=body["citations"],
                        retrieved_count=body["retrieved_count"],
                        usage=body["usage"],
                        model=body["model"],
                        error=None,
                    )
                    ok += 1
                    print(f"[ok]  {q['id']} {latency_ms}ms cites={len(body['citations'])}")
                else:
                    record["error"] = {
                        "http_status": resp.status_code,
                        "body": _safe_json(resp),
                    }
                    err += 1
                    print(f"[err] {q['id']} HTTP {resp.status_code}")
            except Exception as exc:
                record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
                record["error"] = {"http_status": None, "body": str(exc)}
                err += 1
                print(f"[err] {q['id']} {exc!r}")

            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()

    print(f"\nsummary: {ok} ok, {err} err, total {len(questions)}; out={out_path}")
    return 0 if err == 0 else 1


def _safe_json(resp: "httpx.Response"):
    try:
        return resp.json()
    except Exception:
        return resp.text[:500]


if __name__ == "__main__":
    sys.exit(main())
```

依赖：
- `httpx` — backend 已在 deps（DeepSeek client 走 httpx）；评测 runner 在 backend 上下文跑，`uv run` 可直接用
- `pyyaml` — 不在当前 backend deps；实现期 `uv add pyyaml --group dev` 或放入 `[project.optional-dependencies].eval`，先用前者，最简

### 4.3 人工评分文件 `data/eval/mini_eval_<runid>_judged.yaml`

```yaml
runid: "20260507-153000"
judge: XCXUFO
judged_at: 2026-05-07
questions:
  - id: q01
    relevant: true
    cited: true
    not_hallucinated: true
    usable_for_demo: true
    notes: "回答完整列出了 4 个因素，引用 [1][2][3] 都对应到 wang_2024 / li_2023"
  - id: q02
    relevant: true
    cited: true
    not_hallucinated: false
    usable_for_demo: false
    notes: "提到了一个论文里没有的具体数值（'15-20%'），疑似幻觉"
  # ...
summary:
  total: 10
  usable_for_demo: 7
  not_hallucinated: 8
  refuse_correct: 2  # should_refuse=true 题里答得对的数量
```

填写顺序：跑完 runner → 打开对应 JSONL → 边看 answer 边核对 citations.snippet → 填 yaml。

### 4.4 报告 `report.md` 大纲

```
1. 元信息（runid / commit / backend 配置快照）
2. 索引基线（doc 数 / chunk 数 / 平均 chars / 截断率）
3. 题集说明（10 题分布 / yaml 路径）
4. Runner 输出（JSONL 路径 / 总耗时 / HTTP 错误数）
5. 人工评分汇总（usable_for_demo X/10、refuse_correct Y/2 等）
6. 典型好案例（2 例：query / answer 摘要 / citations）
7. 典型坏案例（1–2 例：暴露的问题，挂账 M1.4-b）
8. HR demo 推荐题清单（2–3 题，配预期演示话术）
9. 已知风险与改进项（喂给 M1.4-b 的 backlog）
```

### 4.5 索引基线快照怎么取

入库后跑：

```bash
cd backend
uv run python -c "
from src.storage import ChromaStore
s = ChromaStore('var/chroma', 'papers')
print(s.count())
"
```

或更详细：写一个一次性 inspect 小脚本（不入仓）打印 chunk 长度分布。报告里只要总数与平均长度即可。

### 4.6 文档侧的小修

#### `data/papers/README.md` 增量

在"索引"段之前补一段"放真实 PDF":

```markdown
## 放真实 PDF（M1.4-a 起）

1. 在本目录放 5–10 篇主题论文 PDF（命名建议见上）
2. PDF 已被 .gitignore 排除，**不会**入库
3. 索引前确认 backend `.env` 已设：
   ```
   RAG_ENABLED=true
   RAG_CHROMA_DIR=./var/chroma
   ```
4. 清空旧索引（首次切真实数据时建议）：
   ```
   rm -rf backend/var/chroma
   ```
5. 重建索引（路径用 glob 展开）：
   ```
   cd backend
   uv run python scripts/index_papers.py \
     --paths ../data/papers/*.pdf \
     --persist-dir var/chroma \
     --collection papers \
     --repo-root ..
   ```
```

#### `data/eval/README.md` 新增

题集 schema、runner 用法、人工评分流程，三段落即可。不重复 spec。

## 5 评测题集与评分规范

### 5.1 类别定义

| category | 含义 | should_refuse | 示例（实现期补题面） |
|---|---|---|---|
| `factual` | 单点事实问答，期望召回 + 直接答 | false | 「氮素淋失主要受哪些因素影响？」 |
| `concept` | 概念解释，期望整合多 chunk | false | 「什么是缓控释肥？」 |
| `synthesis` | 多文献综合，期望 ≥2 source | false | 「不同灌溉方式对氮素淋失的影响差异？」 |
| `refuse` | 不在知识范围，期望拒答 | true | 「2025 年诺贝尔化学奖获得者的主要工作？」 |
| `citation_check` | 引用一致性人工核查 | false | 任一 factual 题加重核查重点 |

### 5.2 4 维评分定义（重申）

| 维度 | true 的判定 |
|---|---|
| `relevant` | 答案围绕题面核心，没有跑题 |
| `cited` | 至少 1 条 citation 与答案中的事实对应（refuse 题可为 false） |
| `not_hallucinated` | 答案里出现的所有具体事实（数值、机制、结论）能在召回 chunks.snippet 里找到对应 |
| `usable_for_demo` | 综合判断：拿给 HR 看不丢人 |

### 5.3 通过阈值（DoD 量化）

- `usable_for_demo` ≥ 7 / 10
- `refuse` 题里 `not_hallucinated` 必须 2 / 2（应拒答场景**绝不允许胡编**，最关键的一项）
- 总 HTTP 错误 ≤ 1 / 10（允许偶发 502 / 429，但不能系统性失败）

未达 DoD 不进入 M1.5-Demo。会回到 M1.4-a 内部分析失败原因（索引问题？top_k 太小？prompt 缺约束？），可能短回路调一次参数后重跑。

## 6 测试策略

本迭代是脚本 + 数据 + 评测，不是新业务模块，单测投入产出比低。

### 6.1 静态检查

| # | 命令 | 期望 |
|---|---|---|
| 1 | `cd backend && uv run ruff check scripts/run_mini_eval.py` | 0 error |
| 2 | `cd backend && uv run python scripts/run_mini_eval.py --help` | 正常打印 usage |
| 3 | `cd backend && uv run pytest -q` | 沿用 M1.3.2 基线 `101 passed, 3 skipped` 不退化 |

### 6.2 端到端冒烟（人工执行，写入 review.md）

前置：6–8 篇真实 PDF 入库完成；backend 跑 `RAG_ENABLED=true`；DeepSeek key 有效。

| # | 步骤 | 期望 |
|---|---|---|
| 1 | 看索引基线 | doc 数 ≥ 5；chunk 数 ≥ 200 |
| 2 | 跑 runner | 全部 10 题落盘；HTTP error ≤ 1 |
| 3 | 抽 1 题进前端 UI 重问 | 回答与 JSONL 中的近似（小波动允许） |
| 4 | 人工评分填 yaml | `usable_for_demo` ≥ 7 |
| 5 | refuse 题人工核查 | 都没胡编 |
| 6 | 写报告 + 推荐 demo 题 | 2–3 题候选明确 |

### 6.3 不补单测

理由：runner 是"调 HTTP + 写 JSONL"的胶水脚本；最值得测的是网络异常，但本迭代恰恰希望异常被原样落盘交给人工分析，**测了反而和"不重试不掩盖"原则打架**。M1.4-b 完整评测时如有判分逻辑再考虑测。

## 7 与父 / 子里程碑的衔接

### 与 M1.3.2（已完成）

- 直接消费 `POST /api/chat` 现有契约，**不改契约**
- 前端 UI 在抽检与 demo 时复用，不动代码

### 与 M1.4-b 完整评测（后续）

挂账给 M1.4-b 的事项：

| 项 | 留给 M1.4-b 的理由 |
|---|---|
| 题集扩到 20–50 题 | 类别覆盖加深 + 边界 / 多语言 / 长文本 |
| `[N]` 引用合法性程序化校验 | 需要解析答案正则 + chunk_id 比对，体量大 |
| LLM-as-judge 自动评分 | 评分器本身要做 prompt 与一致性校准 |
| Token 预算精确化 | 改 chunker / context 拼接，需配套回归 |
| 报告自动化（每次跑后生成 md） | 报告稳定后再模板化 |

> 接力契约：**不改 question_id 命名**。M1.4-b 题集是 M1.4-a 题集的超集（追加，不重排）。

### 与 M1.5-Demo 临时外链（后续）

- M1.4-a 完成 = HR 链接拥有"质量底座"
- M1.5-Demo 直接复用 M1.4-a 的索引（同一份 chroma）与推荐题清单
- M1.5-Demo 不依赖 M1.4-b

## 8 度量基线

| 指标 | 计划值 |
|---|---|
| 真实 PDF 数 | 5–10（目标 6–8） |
| 索引后总 chunks | ≥ 200 |
| Runner 跑 10 题总耗时 | < 5 分钟 |
| HTTP error / 10 | ≤ 1 |
| `usable_for_demo` / 10 | ≥ 7 |
| `refuse` 题 `not_hallucinated` / 2 | = 2（必须） |
| 新增依赖 | `pyyaml`（dev / scripts 用） |
| 新增代码行数（非测试，非数据） | ≤ 250（runner + 文档） |
| 后端回归 | 不退化 |

## 9 风险

1. **真实论文版权**
   - 风险：PDF 不能入库；但开发机本地存放是合理使用范围。注意分享给他人时只发引用文件名，不发原文。
   - 缓解：`.gitignore` 已排除 `*.pdf`；HR demo 链接对外不暴露 PDF 下载入口。
2. **PDF 解析质量**
   - 风险：PyMuPDF 对扫描版 PDF / 双栏排版 / 公式可能丢字；BGE 在乱码上召回质量塌方。
   - 缓解：实现期 `load_text` 后人工抽查 1–2 段长度 / 字符是否合理；选论文时优先文字版（非扫描版）PDF。
3. **DeepSeek 限流 / 网络**
   - 风险：评测期 10 次串行调用碰到限流或网络抖动。
   - 缓解：runner 不重试，按 §3.4 让失败原样落盘；人工评分时把网络错误剔除"分母"。
4. **VPN 拦 localhost**
   - 风险：MEMORY 里记的樱花猫问题；runner 调 `127.0.0.1:8000` 可能被代理。
   - 缓解：调用前先 `curl --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health`；必要时 `NO_PROXY=127.0.0.1,localhost uv run python scripts/run_mini_eval.py ...`。
5. **题集偏向已知论文，被批"自我验证"**
   - 风险：出题人就是放论文的人，潜意识里只出"知道答案"的题。
   - 缓解：在报告里**坦诚声明**这是 mini eval，目的是底线验证；M1.4-b 题集要由不熟语料的人 / LLM 出，避免该偏差。这是答辩材料里值得讲的方法论自觉。
6. **mini 评测过早调参导致后续失真**
   - 风险：跑了一次发现 7/10 不达标，立刻调 `chat_top_k` 直到达标，等于针对题集过拟合。
   - 缓解：§3.10 已写明"评测结束前不调参"。如不达标，先在报告里记录原因，调参作为新一次迭代独立做。
7. **HR demo 推荐题挑选偏样本好的，掩盖系统性问题**
   - 风险：报告 / demo 链接展示的都是好案例。
   - 缓解：报告里**强制写"典型坏案例"段**（§4.4 第 7 段）；M1.5-Demo 演示脚本备注"这是 mini eval 中表现最好的题，整体水平见报告"。
8. **`var/chroma` 体积膨胀**
   - 风险：6–8 篇 PDF 切几百到上千 chunks，每条 1024 维 float32 ≈ 4 KB，加索引文件总量约 10–30 MB；不大但应避免误入库。
   - 缓解：确认 `backend/var/` 已被 .gitignore 排除（应是已有规则），实现期复核。
9. **review 文档机审 LLM 不能是 Claude**
   - 缓解：沿用 M1.3.2 / M1.3.1 做法，机审用 GPT-5（或同等他家模型），人审走自己看。spec / review 的实现作者署名 Claude，机审作者 ≠ 实现作者，避免会话内自审自夸。

## 10 实施顺序

1. **Spec & 题集 schema 敲定**（本文件 + `data/eval/README.md`）
2. **挑论文 + 落 PDF 到 `data/papers/`**（手动，6–8 篇）
3. **清空旧索引并重建**（§3.9 命令）
4. **写 10 道 mini 题**到 `data/eval/mini_questions.yaml`
5. **写 runner**：`backend/scripts/run_mini_eval.py`
6. **静态检查**：`ruff` / `pytest` 不退化
7. **跑 runner**：得到 `mini_eval_<runid>.jsonl`
8. **抽 1 题在前端 UI 重问**作为 sanity check
9. **人工评分**：填 `mini_eval_<runid>_judged.yaml`
10. **写报告 `report.md`**（含 HR demo 推荐题清单）
11. **写 review.md**：机审（非 Claude）+ 人审
12. **拆 commit 推送**（按 MEMORY 里"按模块拆分 Conventional Commits"原则）：
    - `chore(data): add eval question set schema and mini set`
    - `feat(eval): add mini eval runner`
    - `docs(papers): document real-paper indexing flow`
    - `docs(iteration): add m1-4-a spec/report/review`
    - 真实 PDF 与 JSONL 因 .gitignore 不进 commit
    - judged.yaml 单独入库（小，便于答辩追溯）

## 11 参考

- M1.3.2 spec：[`../2026-05-06-m1-3-2-frontend-chat-ui/spec.md`](../2026-05-06-m1-3-2-frontend-chat-ui/spec.md)
- M1.3.1 spec：[`../2026-05-05-m1-3-1-chat-rag-route/spec.md`](../2026-05-05-m1-3-1-chat-rag-route/spec.md)
- M1.2.3 spec（chunk_id / document_id 规则）：[`../2026-05-05-m1-2-3-ingest-index-retriever/spec.md`](../2026-05-05-m1-2-3-ingest-index-retriever/spec.md)
- ARCHITECTURE.md：里程碑与"评测在 M4"的旧定位（本迭代将评测前置一部分到 M1.4，须与文档保持一致或在后续修订时更新）
- `backend/scripts/index_papers.py`：当前索引脚本
- `backend/src/rag/ingest.py`：PDF 加载（PyMuPDF）
- `data/papers/README.md`：语料目录约定
