# Backend — 氮淋失风险决策 Agent

Python 3.11 + FastAPI 后端。

M2.0 新增本地 WHCNS 结果读取工具，支持氮/水平衡表及证据定位；
已接入聊天上传 API，文件计算不依赖 RAG 或 LLM。见 [模型文件工具使用说明](src/model_tools/README.md)。

## 目录结构

```
backend/
├── src/
│   ├── main.py           # FastAPI 入口 + CORS
│   ├── config.py         # 应用配置 (pydantic-settings)
│   ├── api/              # HTTP 路由
│   ├── agent/            # 有界执行入口、Skills、路由、状态与证据
│   ├── rag/              # 检索增强模块
│   ├── llm/              # LLM 客户端抽象
│   ├── storage/          # SQLite / Chroma 持久化
│   ├── simulator/        # WHCNS 仿真封装
│   └── utils/            # 通用工具
├── tests/
└── pyproject.toml
```

## 本地启动

```bash
# 安装依赖（会自动创建 .venv 并拉取 Python 3.11）
uv sync

# 启动开发服务器
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 运行测试
uv run pytest
```

启动后访问 <http://localhost:8000/api/health> 确认服务可用。

## RAG Chat

`POST /api/chat` 的文献问答在默认配置下返回 503，因为 `RAG_ENABLED=false` 时不会加载 BGE、Chroma
或本地索引。启用真实问答前需要：装 RAG extras → 准备本地嵌入模型 → 生成 Chroma 索引。

M1.6 起 `/api/chat` 支持轻量多轮。旧请求体仍可用：

```json
{"query": "氮素淋失主要受什么因素影响？"}
```

追问时可附带最近历史，后端会用历史增强检索，但答案仍只依据本轮召回资料：

```json
{
  "query": "那侧向渗漏贡献多少？",
  "history": [
    {"role": "user", "content": "湖北荆州稻田地下径流和地表径流相比如何？"},
    {"role": "assistant", "content": "地下径流氮损失约为地表径流 2 倍。"}
  ]
}
```

### 1. 安装 RAG 依赖

```bash
uv sync --extra rag
```

### 2. 准备 BGE 嵌入模型（默认走本地路径）

`config.py` 默认 `embedding_model="data/models/bge-large-zh-v1.5"`，相对当前工作目录解析；
启动 `uvicorn` / 索引脚本时通常应在 `backend/`。
首次使用前跑下载脚本（仓库根目录）拉到该路径（约 1.3 GB）：

```bash
# 在仓库根
bash scripts/download_models.sh
```

脚本默认走 `https://hf-mirror.com`，并通过 `http://127.0.0.1:7890` 代理（可用
`HF_ENDPOINT` / `PROXY_URL` 环境变量覆盖）。下载落到 `backend/data/models/bge-large-zh-v1.5/`。

如果不想准备本地模型，可在 `.env` 中改用 HuggingFace cache：

```dotenv
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
```

### 3. 生成 Chroma 索引

```bash
uv run python scripts/index_papers.py \
  --paths ../data/papers/sample.txt \
  --persist-dir var/chroma \
  --collection papers \
  --repo-root ..
```

索引脚本会读 `settings.embedding_model`，与运行期 `lifespan` 用同一份模型，
避免索引/查询走不同模型导致检索错位。

M1.6 demo 内容入库可以直接递归扫描论文目录：

```bash
uv run python scripts/index_papers.py \
  --dir ../data/papers \
  --glob '*.pdf' \
  --persist-dir var/chroma_m16 \
  --collection papers \
  --repo-root .. \
  --embed-batch-size 16 \
  --skip-existing
```

### 4. 启用 chat 路由

在 `.env` 中设置：

```dotenv
RAG_ENABLED=true
RAG_CHROMA_DIR=./var/chroma_m16
RAG_COLLECTION=papers
```

### 5. 启用 Reranker（M1.4-b，可选）

二阶段检索：embedding 召回 `RAG_RERANKER_TOP_K_RECALL=20` 候选 →
`BAAI/bge-reranker-v2-m3` 重排取 `RAG_RERANKER_TOP_N=5` 给 LLM。
模型约 2.2 GB，只在需要 reranker 时拉：

```bash
# 在仓库根
bash scripts/download_models.sh reranker
```

启用：

```dotenv
RAG_RERANKER_ENABLED=true
RAG_RERANKER_TOP_K_RECALL=20
RAG_RERANKER_TOP_N=5
RAG_RERANKER_MODEL=data/models/bge-reranker-v2-m3
```

`RAG_RERANKER_ENABLED=false` 时纯 embedding 路径不变，与 M1.3.x 完全一致
（用于 A/B 对照）。Retriever 只在 `enabled=true` 时实例化 reranker，避免
仅 BGE 用户白下 2.2 GB。

### 6. Retrieval 调试

`scripts/retrieval_debug.py` 不调 LLM，单独看 retrieval 命中：

```bash
uv run python scripts/retrieval_debug.py \
  --questions ../data/eval/mini_questions.yaml \
  --persist-dir var/chroma \
  --collection papers \
  --out var/retrieval \
  --top-n 20            # 加 --rerank 切到 reranked 输出
```

每题落 `var/retrieval/<runid>/<qid>.json`，便于 embedding-only vs reranked
做 diff。

详细开发流程见仓库根目录的 [docs/development.md](../docs/development.md)。

## Agent Harness

`POST /api/chat` 保留原请求字段，新增返回 `run_id`、`conversation_id`、
`agent_route`、`evidence` 和 `trace_saved`。原 `route`、`citations`、`file_evidence` 兼容保留。
若要承接文件指标，连续请求使用同一 `session_id` 和显式 `file_id`；未提供 session 时返回
一个新的 conversation_id，调用方可在后续请求中作为 session_id 使用。ID 限制为 1–100 位字母、数字、下划线或连字符。
省略 file_id 不会静默复用旧附件；清空对话应生成新的 session_id。

当前规则路由优先识别文献问题、文件统计、能力引导和最小追问。
`COMPOSED` 支持“硝态氮最大值是多少，为什么可能这么高？”等有限语法；
文件事实、一般文献机理、局限分别返回，附 `sections`、`outcome`、`warnings`。
某一步失败时保留可回答部分；额外时间窗、指标或无法识别的要求仍明确追问。
未引入模型分类器或无限循环。
同会话并发请求返回 `409 conversation_busy`。文件与 State 仍限单 worker。

`POST /api/files` 先检查格式、可读性与资源上限，返回 `status=pending`，
`kind/rows=null`。首次文件分析再检查字段、单位和数值；结果通过聊天的 `attachment`
返回 ready/invalid/expired 状态。业务不合格时解释问题且不提供数值证据。
待分析原件仅在内存暂存（总量 64 MiB、最多 32 份、30 分钟有效期），
分析后释放原件、缓存摘要或诊断；清理过期项发生在访问时。

`AGENT_TRACE_DB` 默认 `var/agent/runs.sqlite3`，相对路径按 backend 目录解析；
`AGENT_BUILD_VERSION` 请设成实际构建/工作区快照标识。Run 的 `config_manifest` 记录
Agent、Prompt、Retriever 代码、依赖锁、回答配置和启动时本地索引/模型身份；超过 256 MiB
的目录只记录元数据指纹，外部 LLM 权重未验证。运行记录不保存凭据、原始提示或思维链。
`trace_saved=false` 表示该回答没有成功入库。启用评测后台后，开发者可以通过受保护的
`/api/eval/runs` 接口读取单轮 Trace，也可通过 `/api/eval/sessions` 按会话查询、分页，
通过 `/api/eval/sessions/{session_id}` 读取完整会话及逐轮 Trace。测试者和匿名请求不能读取。
前台会话自动进入运行记录，但不会自动生成评测 Execution 或评分；操作人是浏览器本地
生成的游客标识，未登录时不能作为真实身份认证。历史 Run 只有会话哈希，会以该哈希作为
旧会话 ID 展示，无法还原原始前台会话 ID。

用例导入（从 backend 执行）：

```bash
.venv/bin/python scripts/import_acceptance_cases.py
```

详见 [范围与迁移规格](../docs/iterations/2026-09-29-agent-harness/spec.md)。

独立真实文件核验（不重启运行中的服务，输出到 `var/eval/harness-*`）：

```bash
.venv/bin/python scripts/run_harness_smoke.py
# 加 --live 使用当前 RAG/LLM；需要代理时显式配置 DEEPSEEK_PROXY。
.venv/bin/python scripts/run_harness_smoke.py --live
```

报告与 SQLite Trace 单独保存；真实联调通过不替代专业人工审核。

## 评测工作台

前端入口 `/evaluation`，接口 `/api/eval/*`。默认 `EVAL_ENABLED=false`；
启用时从 `EVAL_ACCESS_FILE` 加载身份与密钥摘要。首次使用执行
`scripts/create_eval_access.py --tester local-tester --developer local-developer --reviewer local-expert` 生成本地凭据。
用例版本、执行事件、评分与 Trace 共享 `AGENT_TRACE_DB`。评分由用户明确提交，
不会依据 HTTP 成功或自动测试结果生成专业审核结论。

开发者专用 `/api/eval/regressions` 保存不可覆盖的执行/Trace 基线；
`/regressions/{id}/replays` 启动最多两项并行的后台重跑，
`/api/eval/replays/{id}/comparison` 返回逐轮差异。
重跑使用新执行，旧评分保留；仅支持可复原的提问、上下文操作和已登记且指纹一致的本地附件。
重跑按顺序执行可复原步骤，遇人工步骤或无法复原的上传失败时保留已完成轮次并标记受阻；
重启会标记未完成重跑为中断。Task 冻结用例版本与版本清单；Issue 关联失败评分、
原问题和 Run，复测使用新执行与独立评分。AI 辅助复核与专家审核分别存档。
开发者可通过 `/api/eval/assets`、`/case-drafts` 登记文件来源、维护草稿并发布新 Case；
输入输出配对先记候选，`reviewer` 身份依据证据资产另存核实记录。新 Case 的冻结附件也可按指纹重放。

详见 [使用与部署说明](../docs/iterations/2026-09-29-agent-harness/evaluation-guide.md)。
