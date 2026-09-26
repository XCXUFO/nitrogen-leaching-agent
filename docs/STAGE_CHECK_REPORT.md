# 氮素淋失风险决策 Agent 阶段性检查说明

> 文档用途：阶段性检查、项目备案、阶段汇报、后续答辩材料整理。
> 当前状态日期：2026-07-17。
> 项目性质：农业水氮管理领域的检索增强生成（RAG）智能问答原型，不是生产级农业、环保或监管决策系统。
> 2026-09-26 路线调整：本文主体保留 M1.6 历史成果与当时验证记录；
> 后续目标改为 [M2.0 模型认知与使用辅助版](iterations/2026-09-26-m2-0-model-assistant/spec.md)。
> 历史运行成功不代表当前服务在线；WHCNS 在线执行与生产化不作为 M2.0 前提。

## 1. 项目概述

本项目名称为 **Nitrogen Leaching Risk Decision Agent**，中文可表述为
**氮素淋失风险决策 Agent**。项目目标是构建一个面向农田水氮管理、氮素淋失风险分析和相关文献证据查询的智能问答原型系统。

系统目前围绕“本地论文知识库 + 向量检索 + 二阶段重排 + 大语言模型回答 + 前端引用展示”的技术路线展开。用户在网页中提出关于氮素淋失、稻田氮损失、水氮管理、WHCNS 模型、灌溉施肥优化等问题后，系统会先从本地论文库中检索相关片段，再将片段交给大语言模型生成答案，并在答案下方展示引用来源。

现阶段系统已经实现从论文资料整理、离线索引、后端问答 API、前端多轮对话、引用展示、错误降级、检索调试到小规模评测的完整研发闭环。它适合用于阶段检查、技术路线展示、原型演示和后续论文/项目开发的工程基础。

## 2. 建设背景与意义

氮素淋失是农田氮肥管理、水环境保护和农业绿色生产中的重要问题。实际研究中，相关知识分散在大量论文、模型报告和区域试验材料中，常见问题包括：

- 不同作物、区域、土壤和灌溉施肥制度下氮素淋失差异较大。
- 论文中包含大量数值、模型参数、试验结论和区域化结果，人工查找耗时。
- WHCNS、WHCNS_Rice、WHCNS_Veg 等模型相关材料较多，跨论文比较和复核较复杂。
- 直接使用通用大模型回答容易出现资料来源不明、数值不可靠、无法追溯的问题。

因此，本项目采用 RAG 方式：让模型在回答前先检索本地可信资料，并要求回答必须基于检索片段。这样可以在一定程度上降低无依据回答风险，也便于检查人员或研究人员通过引用片段追溯答案来源。

## 3. 当前阶段定位

当前阶段可以定位为 **M1.6 研发原型阶段**。该阶段已经完成“可运行、可演示、可追溯、可评测”的基础能力，但还没有进入生产部署和正式决策支持阶段。

### 3.1 已达到的阶段目标

- 已有前后端分离的完整 Web 问答闭环。
- 已有基于本地论文库的 RAG 检索问答能力。
- 已支持多轮追问，能够结合最近对话理解指代。
- 回答附带 citation 列表，能展示被检索到的证据片段。
- 已整理 M1.6 本地论文目录，共 90 篇 PDF，形成可追溯 catalog。
- 已构建 Chroma 向量索引，M1.6 索引包含 12472 个 chunk 和 90 个 document_id。
- 已接入 BGE 中文/多语嵌入模型和 bge-reranker-v2-m3 重排模型。
- 已实现数字证据增强机制，用于改善数值型问题的证据召回。
- 已有 mini eval 和 M1.6 扩展题集的人工评分流程。
- 已通过多轮本地 smoke 和 targeted tests 验证核心链路。

### 3.2 未声称达到的目标

- 未声称系统已经达到农业专家系统水平。
- 未声称回答可作为施肥、灌溉、环保或监管决策的唯一依据。
- 未完成 WHCNS 黑盒仿真模型的真实调用接入。
- 未完成生产部署、用户体系、权限体系、审计后台和长期稳定性验证。
- 未完成大规模专家人工评测。

## 4. 系统总体架构

项目采用前后端分离架构。后端负责资料索引、检索、重排、提示词构造、大模型调用和 API 输出；前端负责用户交互、对话展示、错误提示和引用展示。

整体流程如下：

```text
本地论文 PDF / 文本资料
        ↓
离线解析与切块 ingest / chunk
        ↓
BGE embedding 向量化
        ↓
Chroma 本地向量库持久化
        ↓
用户问题进入 /api/chat
        ↓
构造检索 query，包括最近对话和中英领域提示
        ↓
向量召回 top_k_recall 候选片段
        ↓
可选 reference filter 过滤引用编号相关片段
        ↓
可选 bge-reranker-v2-m3 二阶段重排
        ↓
可选 numeric/evidence boost 调整数值证据排序
        ↓
将 top_n 片段打包为 prompt context
        ↓
DeepSeek API 生成回答
        ↓
返回 answer + citations + usage + model
        ↓
Next.js 前端展示多轮对话和引用
```

### 4.1 后端

后端位于 `backend/`，使用 Python 3.11 + FastAPI。主要模块如下：

| 模块 | 作用 |
|---|---|
| `src/main.py` | FastAPI 入口、生命周期初始化、CORS、RAG 组件加载 |
| `src/config.py` | 环境变量和默认配置 |
| `src/api/health.py` | 健康检查接口 |
| `src/api/chat.py` | 问答接口和错误降级契约 |
| `src/api/chat_schema.py` | 请求/响应数据结构 |
| `src/agent/chat_service.py` | 检索、prompt、LLM 调用的编排层 |
| `src/agent/prompt.py` | 系统提示词、上下文格式化、多轮历史和检索 query 构造 |
| `src/rag/` | 嵌入、切块、入库、检索、重排、数值增强等 RAG 逻辑 |
| `src/storage/chroma_store.py` | Chroma 向量库封装 |
| `src/llm/deepseek.py` | DeepSeek API 兼容客户端 |
| `scripts/index_papers.py` | 离线索引脚本 |
| `scripts/run_mini_eval.py` | 评测脚本 |

### 4.2 前端

前端位于 `frontend/`，使用 Next.js 16 + TypeScript + Tailwind 4 + shadcn/ui。主要能力包括：

- 单页聊天界面。
- 多轮对话展示。
- 用户输入提交和 loading 状态。
- 3 秒以上慢请求提示。
- 后端错误码友好化展示。
- 错误后可重试。
- 每条回答下方展示 citations。
- 可折叠的 Backend health 调试区。
- 可清空当前会话。

### 4.3 数据与运行产物

仓库中提交的是代码、元数据、评测题集和人工评分文件；受版权和体积影响，论文 PDF、本地模型权重、Chroma 索引和 eval 原始 JSONL 输出不提交到仓库。

| 类型 | 是否入仓 | 说明 |
|---|---|---|
| 源代码 | 是 | 后端、前端、脚本、测试 |
| 文档 | 是 | 架构、迭代报告、发布说明、本文档 |
| 论文 catalog | 是 | `data/papers/catalog_m16.md/json` |
| 论文 PDF | 否 | 版权材料，本地放置 |
| 模型权重 | 否 | BGE、reranker 本地下载 |
| Chroma 索引 | 否 | 本地 `backend/var/chroma_m16` |
| eval 原始 JSONL | 否 | 本地 `backend/var/eval` |
| judged YAML | 是 | 便于追溯人工评分结论 |

## 5. 核心功能说明

### 5.1 RAG 问答

用户通过前端输入问题，前端调用后端 `POST /api/chat`。后端先检索论文知识库，再让大模型在参考资料范围内回答。

当前系统提示词明确要求：

- 回答必须基于给出的参考资料。
- 如果资料不足以回答，需要明确说明“资料中未涉及”。
- 回答中的事实引用使用 `[1][2]` 形式，对应本次检索返回的资料编号。
- 追问时可以结合最近对话理解指代，但事实依据仍只能来自本轮检索资料。
- 对多数值、多指标问题，需要逐条检查参考资料 chunk。

这种设计的重点是把“模型自由发挥”约束为“基于检索证据回答”。

### 5.2 多轮对话

M1.6 已支持轻量多轮。接口允许最多 12 条历史消息，前端会把最近对话发送给后端。后端使用历史增强检索 query，解决“那这个贡献比例是多少？”这类依赖前文的追问。

需要注意的是：历史只用于理解当前问题，不直接作为事实来源。最终答案仍以当前轮检索到的论文片段为依据。

### 5.3 引用展示

后端响应中包含 `citations` 数组，每条 citation 包括：

- 引用序号 `index`
- 知识块 ID `chunk_id`
- 来源文件 `source`
- 检索/重排分数 `score`
- 证据片段摘要 `snippet`

前端在每条回答下方展示 citation 列表。检查时可以通过 citation 判断答案是否确实由论文片段支撑。

### 5.4 检索与重排

现阶段检索链路包括：

- BGE embedding：将问题和论文 chunk 转成向量。
- Chroma：本地向量库，负责近似相似度检索。
- top_k_recall：重排前召回候选，当前 demo 口径为 20。
- reference filter：改善用户提到论文编号时的召回稳定性。
- bge-reranker-v2-m3：对候选片段进行二阶段重排。
- top_n：最终交给 LLM 的片段数，当前 reranker 路径下为 5。

单纯向量召回有时会错过具体数值段或把“主题相近但证据不足”的段落排在前面。二阶段重排和后处理机制是为了解决这类问题。

### 5.5 数值证据增强

M1.5-b 引入了 numeric/evidence boost。该机制用于处理农业论文中常见的数值型问题，例如 R²、RMSE、IA、kg N/ha、百分比、减少比例等。

机制要点：

- 只在 RAG + reranker 路径启用。
- 通过通用统计词表和数值密度识别“可能包含答案数值”的片段。
- 使用 relevance band，避免把完全不相关但数字很多的片段抬到前面。
- 默认参数为 `weight=0.445`、`band=0.30`。
- 该机制不是为某一道题硬编码答案，而是通用后处理策略。

在 M1.5-b 评测中，该机制解决了 q08 中 WHCNS 模型精度证据片段被 reranker 压出 top5 的问题，同时保持 q01-q10 中除目标题外的 top5 基本不变。

### 5.6 错误处理与演示稳定性

系统针对常见错误给出结构化错误码，避免前端只显示不可理解的异常信息。

| 错误码 | HTTP 状态 | 含义 |
|---|---:|---|
| `rag_not_configured` | 503 | RAG 未启用或初始化失败 |
| `rag_query_failed` | 503 | 检索阶段失败 |
| `llm_auth_failed` | 500 | LLM API key 或鉴权失败 |
| `llm_rate_limited` | 429 | LLM 上游限流 |
| `llm_timeout` | 504 | LLM 请求超时 |
| `llm_unreachable` | 502 | LLM 上游不可达 |
| `llm_upstream_error` | 502 | LLM 上游其他错误 |
| `internal_error` | 500 | 后端未预期内部错误 |

M1.5-a 已将 DeepSeek SDK 默认长超时替换为显式有界超时和重试：默认 `timeout=60s`，`max_retries=2`。前端也提供错误提示和重试入口。

## 6. 数据资料整理情况

M1.6 对本地论文资料进行了集中整理。

### 6.1 论文库规模

当前整理后的本地论文库：

- 90 篇 PDF。
- 文件命名统一为 `NNN_author_year_topic.pdf`。
- 重复 PDF 已移动出索引目录。
- 目录文件为 `data/papers/catalog_m16.md` 和 `data/papers/catalog_m16.json`。
- 重命名和重复隔离记录为 `data/papers/rename_manifest_m16.json`。

### 6.2 主题覆盖

根据 M1.6 catalog 统计，主要主题包括：

| 主题标签 | 数量 |
|---|---:|
| WHCNS | 24 |
| rice_paddy | 21 |
| irrigation | 19 |
| maize | 15 |
| nitrogen_leaching | 14 |
| greenhouse_vegetable | 12 |
| model_calibration | 8 |
| wheat | 8 |
| n2o_nh3 | 8 |
| fertilization | 7 |

资料覆盖了 WHCNS 模型、稻田氮损失、灌溉优化、设施蔬菜、玉米、小麦、氨挥发、氧化亚氮、水氮利用效率等方向。

### 6.3 索引情况

M1.6 当前索引状态：

- 索引 PDF 文件数：90。
- Chroma collection：`papers`。
- Chroma 持久化目录：`backend/var/chroma_m16`。
- chunk 总数：12472。
- distinct document_id：90。
- 当前 demo `.env` 指向 `RAG_CHROMA_DIR=./var/chroma_m16`。

## 7. API 说明

### 7.1 健康检查

```http
GET /api/health
```

成功响应示例：

```json
{
  "status": "ok",
  "service": "nitrogen-leaching-agent-backend",
  "version": "0.1.0"
}
```

### 7.2 聊天问答

```http
POST /api/chat
Content-Type: application/json
```

最小请求：

```json
{
  "query": "氮素淋失主要受什么因素影响？"
}
```

带历史的请求：

```json
{
  "query": "那这个贡献比例具体是多少？",
  "history": [
    {
      "role": "user",
      "content": "湖北荆州稻田水稻生长季的地下径流氮损失和地表径流相比量级如何？"
    },
    {
      "role": "assistant",
      "content": "地下径流氮损失约为地表径流的 2 倍。"
    }
  ]
}
```

请求字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | string | 必填，1-1000 字符，用户当前问题 |
| `k` | int/null | 可选，1-20，指定返回检索片段数 |
| `session_id` | string/null | 可选，前端会生成会话 ID |
| `history` | array | 可选，最多 12 条，元素 role 为 `user` 或 `assistant` |

成功响应字段：

| 字段 | 说明 |
|---|---|
| `answer` | 模型生成的回答 |
| `citations` | 本次回答使用的参考片段列表 |
| `usage` | LLM token 用量信息 |
| `retrieved_count` | 本次返回给模型的检索片段数量 |
| `model` | 实际调用的 LLM 模型名 |

## 8. 运行与部署说明

### 8.1 后端本地运行

```bash
cd backend
uv sync --extra rag
cp ../.env.example .env
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

关键环境变量：

```dotenv
DEEPSEEK_API_KEY=sk-...
RAG_ENABLED=true
RAG_CHROMA_DIR=./var/chroma_m16
RAG_COLLECTION=papers
RAG_RERANKER_ENABLED=true
RAG_RERANKER_TOP_K_RECALL=20
RAG_RERANKER_TOP_N=5
RAG_RERANKER_MODEL=data/models/bge-reranker-v2-m3
RAG_NUMERIC_BOOST_ENABLED=true
```

### 8.2 离线索引

```bash
cd backend
uv run python scripts/index_papers.py \
  --dir ../data/papers \
  --glob '*.pdf' \
  --persist-dir var/chroma_m16 \
  --collection papers \
  --repo-root .. \
  --embed-batch-size 16 \
  --skip-existing
```

### 8.3 前端本地运行

```bash
cd frontend
pnpm install
cp .env.local.example .env.local
pnpm dev
```

打开 `http://localhost:3000` 即可使用 Web 问答界面。前端默认连接 `http://localhost:8000`，可通过 `NEXT_PUBLIC_API_BASE_URL` 修改。

## 9. 评测与验证情况

### 9.1 单元测试和工程检查

项目包含后端 pytest 测试和前端 lint/build 检查。不同迭代中已记录的验证包括：

- M1.4-b：前端 `pnpm lint`、`pnpm build` 通过；后端非 live 核心测试子集通过。
- M1.5-a：后端 `uv run pytest -q` 记录为 121 passed / 4 skipped；前端 lint 与 TypeScript 检查通过。
- M1.5-b：`test_numeric_boost.py` 11 passed；`pytest -k "not live"` 134 passed / 4 deselected；q08 live smoke 通过。
- M1.6：后端 targeted tests 50 passed；DeepSeek tests 5 passed；前端 `pnpm lint` 和 `pnpm build` 通过。

由于 live 测试依赖真实 DeepSeek API、本地模型和本地 Chroma 索引，不适合全部纳入普通 CI。仓库采用 offline pytest + 手动 smoke + eval runner 的组合方式验证。

### 9.2 M1.4-b 基础评测

M1.4-b 是第一个可交付端到端 RAG 原型版本。该阶段完成了：

- 8 篇 PDF 基线语料。
- 1348 个 chunk。
- reranker 接入。
- mini eval runner。
- 引用展示。

质量结果：

| 指标 | 结果 |
|---|---|
| HTTP errors | 0 / 10 |
| q01-q08 expected source in reranked top5 | 7 / 8 |
| `usable_for_demo` | 2 / 10 |
| refuse `not_hallucinated` | 2 / 2 |

结论：工程链路成立，但答案质量未达到展示阈值，主要瓶颈是证据抽取、数值事实恢复和多源综合。

### 9.3 M1.5-a 演示稳定性

M1.5-a 主要解决默认配置、上游超时和错误体验问题。

代表性 live smoke：

- 问题：湖北荆州稻田地下径流氮损失与地表径流相比量级如何。
- 结果：系统答出地下径流氮损失约 6.2 kg N ha-1，占施氮 4%，约为地表径流 2 倍，侧向渗漏贡献 33%。
- HTTP 200，引用 5 条，关键数值有证据支持。

### 9.4 M1.5-b 数值证据增强

M1.5-b 解决 q08 数值证据片段被 reranker 压出 top5 的问题。调整后：

- q08 的目标证据 `026::0172` 进入 final context。
- q08 live answer 能答出 R²、RMSE、IA 等模型精度指标。
- q01-q10 中除 q08 外 top5 基本不变。
- 保留明确 caveat：该结论基于 q01-q10 frozen set，是 in-sample 结果，不外推为全局效果。

### 9.5 M1.6 扩展语料与多轮评测

M1.6 将语料扩展到 90 篇论文，并增加 24 题扩展评测集。评测过程分为多轮：

| runid | 结果摘要 |
|---|---|
| `20260708-174735` | 24 ok / 0 err；5/24 usable；2/2 correct refusals |
| `20260710-161708` | 24 ok / 0 err；14/24 usable；2/2 correct refusals；24/24 not hallucinated |
| `20260710-172602` | 24 ok / 0 err；21/24 usable；2/2 correct refusals；4/4 synthesis usable |

最后一轮 M1.6 自评显示系统已经能在扩展语料下完成多数 demo 问题，且拒答题保持安全。但仍有 3 个 self-reviewed 失败点：

- `m16_q06`：检索已修复，但回答仍漏掉 NH3 受温度/降水影响的空间驱动表述。
- `m16_q14`：能答出 2050 NUE 目标需要管理和育种共同推进，但漏掉 national NUE = 0.31。
- `m16_q18`：检索已修复，但回答未按要求显式列出 77.2、65.6、81.5 kg N/ha 及 33.6%、31.5%、40.8%。

这些问题说明当前系统已经具备可演示能力，但对表格化数值、多指标完整抽取和严格格式回答仍需进一步增强。

## 10. 阶段成果清单

### 10.1 代码成果

- FastAPI 后端服务。
- Next.js 前端聊天界面。
- DeepSeek API 兼容 LLM 客户端。
- BGE embedding 封装。
- Chroma 向量库封装。
- PDF/text ingest 和 chunk pipeline。
- Retriever 检索编排。
- bge-reranker-v2-m3 二阶段重排。
- reference filter。
- numeric/evidence boost。
- `/api/health` 和 `/api/chat`。
- 多轮对话历史输入。
- 引用结果 schema。
- 结构化错误处理。
- eval runner 和 retrieval debug 脚本。

### 10.2 数据与文档成果

- `data/papers/catalog_m16.md/json`：M1.6 论文目录。
- `data/papers/rename_manifest_m16.json`：论文整理操作记录。
- `data/eval/mini_questions.yaml`：10 题冻结 mini 题集。
- `data/eval/m16_questions.yaml`：24 题扩展评测集。
- `data/eval/*_judged.yaml`：人工评分结果。
- `docs/ARCHITECTURE.md`：架构决策记录。
- `docs/iterations/*/spec.md`：各阶段需求说明。
- `docs/iterations/*/report.md`：各阶段实现报告。
- `docs/iterations/*/review.md`：各阶段复盘。
- `docs/releases/v0.1.0-m1.4b.md`：阶段发布说明。
- 本文档：阶段性检查说明。

## 11. 技术路线合理性说明

### 11.1 为什么采用 RAG

农业论文问答高度依赖具体实验、区域、作物和数值结果。直接让通用大模型回答，容易产生来源不明或数值错误的问题。RAG 可以先检索本地可信文献，再让模型基于证据回答，更适合阶段原型。

### 11.2 为什么采用前后端分离

前后端分离便于后续接入已有平台。后端只暴露 REST API，未来如果需要对接学校/实验室平台或已有决策系统，只需替换前端或增加 adapter，不必推翻 RAG 核心链路。

### 11.3 为什么使用 Chroma

当前语料规模为几十到上百篇论文，Chroma 文件持久化模式足够支撑本地研发和演示，部署成本低，不需要额外维护向量数据库服务。未来规模扩大后可迁移到 Qdrant 或 Milvus。

### 11.4 为什么使用 DeepSeek

DeepSeek 提供 OpenAI API 兼容接口，中文问答效果和成本适合原型开发。项目通过 `LLMClient` 抽象隔离模型调用，未来可替换为 OpenAI、Claude 或本地模型。

### 11.5 为什么不用重型 Agent 框架

当前核心需求是“检索论文证据并回答”，不需要复杂工具编排。自研轻量编排可以让 prompt、检索逻辑、错误处理和评测路径更透明，便于论文写作和阶段检查说明。

## 12. 安全边界与风险说明

当前系统必须按照研究原型理解，不能直接作为生产决策系统。

主要风险包括：

- 检索可能漏掉正确论文或正确段落。
- PDF 解析可能丢失表格结构或导致数值上下文不完整。
- 大模型可能遗漏部分指标，尤其是多指标、多数值问题。
- 大模型可能在引用充分时仍表达不完整。
- 上游 LLM API 存在延迟波动、限流和超时风险。
- 当前人工评分主要由项目内自评完成，尚未经过外部领域专家系统性复核。
- 论文 PDF 不入仓，复现实验需要本地准备相同资料和模型。

系统当前采取的缓解措施包括：

- 要求回答基于参考资料。
- 展示 citations，便于人工追溯。
- 对资料不足情况要求说明“资料中未涉及”。
- 对 LLM 上游错误进行结构化降级。
- 使用 frozen eval 和 judged YAML 记录质量变化。
- 保留明确 caveat，不把 demo 结果包装成生产结论。

## 13. 当前不足

现阶段主要不足如下：

- 对表格、扫描 PDF、跨页数值的抽取能力有限。
- 对多指标问题有时会漏列部分数值。
- 对跨论文综合问题依赖检索命中和 prompt 压缩效果，仍不稳定。
- 前端是原型界面，没有用户登录、权限、审计、导出报告等生产功能。
- WHCNS 模型真实仿真调用尚未集成，`simulator/` 仍是后续扩展位置。
- 没有生产部署脚本和运维监控。
- 评测集规模仍偏小，需要更多外部问题和专家审核。

## 14. 后续计划

2026-09-26 调整为 M2.0 模型认知与使用辅助版：帮助初学者理解用途、
判断使用条件、准备资料并解读一个真实案例，核心流程独立于原平台运行。

1. 固定 M1.6 回归基线，控制投入修复答案遗漏，补充未参与调优的相似问题。
2. 确认 WHCNS 版本、手册、参数说明、一套真实输入输出及展示许可。
3. 以“认识模型／准备使用／解读结果”组织首页、分层回答、任务状态和引用。
4. 基于实际材料选择一种输入检查或结果表读取工具，并保留可复核记录。
5. 从 10 个试评任务开始，提供冻结回答评审入口，分别开展专业审核和新手试用。

在线模型执行、自动决策、复杂权限和原平台深度集成暂缓。
完整范围、周交付与验收见 [M2.0 spec](iterations/2026-09-26-m2-0-model-assistant/spec.md)。

## 15. 阶段性结论

截至 2026-07-17，本项目已经完成一个可运行的氮素淋失领域 RAG 智能问答原型。它具备本地论文资料整理、离线索引、向量检索、重排、数值证据增强、DeepSeek 生成、多轮前端交互、引用展示和小规模评测闭环。

从阶段检查角度看，项目已具备清晰的技术路线、可演示系统、可追溯数据目录、可复核评测结果和明确的风险边界。当前最适合的表述是：

> 本项目已完成面向农田氮素淋失风险与水氮管理文献问答的 RAG 原型系统建设，形成了“本地论文知识库—检索增强问答—引用追溯—评测反馈”的完整研发闭环。系统可用于阶段演示和后续研究开发，但仍需在数值抽取、专家评测、WHCNS 模型接入和生产化部署方面继续完善，暂不作为正式农业或环境决策依据。

## 16. 参考材料索引

- 项目总览：`README.md`
- 后端说明：`backend/README.md`
- 前端说明：`frontend/README.md`
- 架构决策：`docs/ARCHITECTURE.md`
- 开发指南：`docs/development.md`
- M1.4-b 发布说明：`docs/releases/v0.1.0-m1.4b.md`
- M1.5-a 演示稳定性报告：`docs/iterations/2026-06-16-m1-5-a-demo-hardening/report.md`
- M1.5-b 数值证据增强报告：`docs/iterations/2026-06-16-m1-5-b-q08-evidence-boost/report.md`
- M1.6 多轮与扩展语料报告：`docs/iterations/2026-07-07-m1-6-demo-content-multiturn/report.md`
- M1.6 论文目录：`data/papers/catalog_m16.md`
- 评测说明：`data/eval/README.md`
