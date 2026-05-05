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
或本地索引。启用真实问答前先安装 RAG extras 并生成 Chroma 索引：

```bash
uv sync --extra rag
uv run python scripts/index_papers.py \
  --paths ../data/papers/sample.txt \
  --persist-dir var/chroma \
  --collection papers \
  --repo-root ..
```

然后在 `.env` 中设置：

```dotenv
RAG_ENABLED=true
RAG_CHROMA_DIR=./var/chroma
RAG_COLLECTION=papers
```

详细开发流程见仓库根目录的 [docs/development.md](../docs/development.md)。
