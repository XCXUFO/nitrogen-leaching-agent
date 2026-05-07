# Frontend — 氮淋失风险决策 Agent

Next.js 16 (App Router) + TypeScript + Tailwind 4 + shadcn/ui。

## 本地启动

```bash
# 安装依赖
pnpm install

# 复制环境变量示例
cp .env.local.example .env.local

# 启动开发服务器（Turbopack）
pnpm dev
```

打开 <http://localhost:3000>，输入问题后查看带引用的回答。
页面底部"调试 / Backend health"折叠区可单独验证 `${NEXT_PUBLIC_API_BASE_URL}/api/health`。

## 启动 chat 完整闭环（M1.3 起）

前提：后端启用 RAG，并已建好向量索引。

```bash
# 1. 后端：装 rag extra
cd backend && uv sync --extra rag

# 2. 后端：建索引（首次或资料更新时跑）
uv run python scripts/index_papers.py \
    --paths ../data/papers/sample.txt \
    --persist-dir var/chroma --collection papers --repo-root ..

# 3. 后端：backend/.env 设
#    DEEPSEEK_API_KEY=sk-...
#    RAG_ENABLED=true
#    RAG_CHROMA_DIR=./var/chroma

# 4. 后端：启动
uv run uvicorn src.main:app --reload

# 5. 前端
cd ../frontend
cp .env.local.example .env.local
pnpm dev
```

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | 后端地址（末尾斜杠会自动剔除） | `http://localhost:8000` |

## 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 错误条 `请求未发出…`（code=`network`） | 后端未启动 / 端口不通 / VPN 拦了 localhost | 检查 `uvicorn` 是否在跑；樱花猫 VPN 把 `127.0.0.1` 加 ByPass |
| 503 + `rag_not_configured` | 后端 `.env` 没设 `RAG_ENABLED=true` | 改 `.env` 后重启后端 |
| 503 + `rag_query_failed` | chroma 索引目录不对或为空 | 重新跑 `scripts/index_papers.py`，确认 `RAG_CHROMA_DIR` 路径正确 |
| 502 + `llm_unreachable` | DeepSeek 不可达 / 代理设置 | 检查网络与 `DEEPSEEK_BASE_URL` |
| 422 + `输入校验失败` | query 为空白 / 超 1000 字 | 调整输入；前端字符计数变红时已禁用提交 |
| 首次回答 ~10s 才出 | BGE 嵌入模型冷加载 | 正常现象；UI 3 秒后会显示 hint |

## 目录结构

```
frontend/
├── src/
│   ├── app/                   # 路由（App Router）
│   ├── components/
│   │   ├── chat/              # 单轮 chat UI（form / message / citations / error）
│   │   ├── debug/             # 弱化的 health 探测入口
│   │   └── ui/                # shadcn/ui 原语
│   └── lib/                   # types / api / error-messages / cn
├── public/
└── package.json
```

## shadcn/ui

- baseColor: `slate`
- icon library: `lucide`
- 添加新组件：`pnpm dlx shadcn@latest add <component>`

详细开发流程见仓库根目录的 [docs/development.md](../docs/development.md)。
