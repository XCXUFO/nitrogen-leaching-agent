# 本地开发指南

本项目是 monorepo，包含 Python 后端 (`backend/`) 和 Next.js 前端 (`frontend/`)。
Walking Skeleton 阶段只做一件事：**前端按钮 → 后端 `/api/health` → 显示返回 JSON**。

## 前置依赖

| 工具 | 版本 | 安装 |
|---|---|---|
| Python | 3.11（由 uv 自动管理） | 无需手装；`uv` 会下载 |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.11 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | ≥ 20 | [nodejs.org](https://nodejs.org/) |
| pnpm | ≥ 10 | `corepack enable pnpm`（Node 20 内置 corepack） |
| Git | 任意新版 | 系统包管理器 |

## 克隆并初始化

```bash
git clone git@github.com:XCXUFO/nitrogen-leaching-agent.git
cd nitrogen-leaching-agent
```

## 后端：backend/

```bash
cd backend

# 复制环境变量模板；再按需填 DeepSeek Key 等
cp ../.env.example .env

# 安装依赖 + 创建 .venv（uv 会自动拉取 Python 3.11）
uv sync

# 启动开发服务器（http://localhost:8000）
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 另起一个终端跑测试
uv run pytest
```

验证：`curl http://localhost:8000/api/health` 应返回

```json
{"status":"ok","service":"nitrogen-leaching-agent-backend","version":"0.1.0"}
```

## 前端：frontend/

```bash
cd frontend

# 复制环境变量模板
cp .env.local.example .env.local

# 安装依赖
pnpm install

# 启动开发服务器（http://localhost:3000）
pnpm dev
```

打开 <http://localhost:3000>，点击 **"测试后端连接"** 按钮，应在页面显示后端返回的 JSON。

## 端口约定

| 服务 | 端口 |
|---|---|
| 后端 FastAPI | 8000 |
| 前端 Next.js | 3000 |

后端 CORS 默认允许 `http://localhost:3000`。如需放开其它来源，修改
`backend/.env` 中的 `CORS_ORIGINS`（逗号分隔）并重启后端。

## 常用命令速查

```bash
# 后端
uv sync                          # 安装/同步依赖
uv run uvicorn src.main:app --reload
uv run pytest                    # 运行测试
uv add <package>                 # 添加依赖
uv add --dev <package>           # 添加开发依赖

# 前端
pnpm install                     # 安装依赖
pnpm dev                         # 开发
pnpm build && pnpm start         # 生产构建（build 阶段会访问 fonts.googleapis.com 下载字体；国内网络可能需要代理）
pnpm lint                        # ESLint
pnpm dlx shadcn@latest add <comp># 添加 shadcn 组件
```

## 下一步

Walking Skeleton 跑通后，按里程碑推进（详见 [ARCHITECTURE.md](./ARCHITECTURE.md)）：

- **M1**：基础对话闭环（RAG + LLM + 单轮问答）
- **M2**：完整 Agent 能力
- **M3**：WHCNS 集成
- **M4**：评测 + 上线
