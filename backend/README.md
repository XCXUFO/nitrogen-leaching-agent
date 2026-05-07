# Backend — 氮淋失风险决策 Agent

Python 3.11 + FastAPI 后端。

## 目录结构

```
backend/
├── src/
│   ├── main.py           # FastAPI 入口 + CORS
│   ├── config.py         # 应用配置 (pydantic-settings)
│   ├── api/              # HTTP 路由
│   ├── agent/            # Agent 编排 (ReAct + Workflow)
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

`POST /api/chat` 默认返回 503，因为 `RAG_ENABLED=false` 时不会加载 BGE、Chroma
或本地索引。启用真实问答前需要：装 RAG extras → 准备本地嵌入模型 → 生成 Chroma 索引。

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

### 4. 启用 chat 路由

在 `.env` 中设置：

```dotenv
RAG_ENABLED=true
RAG_CHROMA_DIR=./var/chroma
RAG_COLLECTION=papers
```

详细开发流程见仓库根目录的 [docs/development.md](../docs/development.md)。
