# 说明文档 — Walking Skeleton

> **目标读者**：未来翻阅本仓库的研究者、本人在毕设论文写作阶段、
> 接手维护的工程师。本文档不是 API 文档，而是 **设计意图与实现要点的沉淀**。

| 元信息 | 值 |
|---|---|
| 迭代名 | walking-skeleton |
| 日期 | 2026-04-21 |
| 涉及 commit | `dd7d4ad` `794533e` `e2e2aec` `5ccb990` |
| 文档版本 | v1.0 |

---

## 1 本次迭代的目标

实现 Alistair Cockburn 在 *Crystal Clear* 中提出的 **Walking Skeleton**：
一个端到端贯通、但每层只做最小实现的可运行系统。具体到本项目：

> **用户在浏览器点击一个按钮 → 前端调用后端 → 后端返回 health JSON → 前端展示**

之所以先做骨架而非任何业务功能，目的有三：

1. **暴露集成风险**：跨语言（Python / TypeScript）、跨进程、跨端口、
   跨 CORS 边界的链路常常在最后一公里翻车。先把链路打通，把
   "环境问题" 与 "业务问题" 解耦。
2. **建立部署单元**：后续每加一个能力（RAG、Agent、Simulator），
   都是在已经能跑的骨架上挂载，而不是在写完逻辑后再去拼装运行时。
3. **形成可被审查的 baseline**：导师 / 评审 / 评测脚本可以在
   `46c10d8..5ccb990` 之间跑回归，确认任何后续退化都不是基础引起的。

> 在毕设论文方法论一章可以引用此节，作为 "增量交付策略" 的实践证据。

## 2 技术栈选型与定型

技术栈在 `46c10d8` 已写入 `README.md` 与 ADR；本次迭代是把决策"落地"。

| 层 | 选型 | ADR / 出处 |
|---|---|---|
| LLM | DeepSeek (deepseek-chat) | ADR-003 — 性价比 |
| Embedding | BGE-large-zh-v1.5 | 中文学术领域强基线 |
| 向量库 | Chroma | ADR-004 — 文件持久化、零运维 |
| Agent | 自研 ReAct + Workflow | ADR-005 — 论文需要算法可见 |
| 后端 | Python 3.11 + FastAPI | 异步 / 类型 / Pydantic 生态 |
| Web | Next.js 16 (App Router) + TS + Tailwind 4 + shadcn/ui | 演示门槛低、便于平台对接 |
| 前后端关系 | RESTful，完全解耦 | ADR-001 — 未来对接已有平台 |
| 包管理 | `uv`（Python） / `pnpm`（Node） | 新一代、速度快、锁文件可复现 |

注：本次迭代尚未引入 LLM / Embedding / Chroma 的代码或依赖；
只是把它们的"位置"通过模块占位 (`backend/src/{llm,rag,storage}/`)
预留好。

## 3 关键设计决策

### 3.1 后端目录采用扁平 `src/` 而非 `src/<package>/`

`uv init --package` 默认生成 `src/backend/__init__.py` 的包结构，
入口就要写成 `backend.main:app`。本项目反其道而行之，把 `src` 本身
作为命名空间，入口写成 `src.main:app`。

**理由**：

1. 模块前缀更短、导入更直观（`from src.api import health` 比
   `from backend.api import health` 更贴近"目录结构即模块路径"
   的心智模型）。
2. 应用型项目（非可发布的库）不需要 build-system，省掉了
   `[build-system]` 和包打包的概念负担。
3. 对论文写作友好——作者可以直接说"`src/agent/` 实现了 ReAct"，
   读者一眼就能找到。

**代价**：失去 `pip install backend` 的能力。本项目永远不会作为
PyPI 包发布，故无影响。

### 3.2 配置层：单点 `Settings` + `.env`

参见 `backend/src/config.py`：

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    cors_origins: str = "http://localhost:3000"
    deepseek_api_key: str = ""
    ...
```

所有配置经由 `pydantic-settings` 从 `.env` 注入；
`extra="ignore"` 允许 `.env` 里出现未使用的键，避免因新增
未注册字段导致启动崩溃。`cors_origins` 用逗号分隔字符串
+ `cors_origin_list` 计算属性的方式承载多源，简化 `.env` 编写。

**对论文的意义**：所有关于 "外部依赖参数" 的讨论都可以收敛到
`Settings`，便于在论文里画"系统配置面板"图。

### 3.3 FastAPI 用 `lifespan` 管理生命周期

`backend/src/main.py` 用 `@asynccontextmanager` 的 `lifespan` 函数
代替已弃用的 `@app.on_event("startup")`：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Backend starting | env={} | cors_origins={}", ...)
    yield
    logger.info("Backend shutting down")

app = FastAPI(..., lifespan=lifespan)
```

**理由**：M2 之后会在启动时初始化 LLM 客户端、加载 BGE 模型、
连接 Chroma；这些都需要"启动 + 关闭"成对的 hook。`lifespan` 是
唯一未弃用的方案，提前用上避免后期重构。

### 3.4 模块切分原则：垂直能力 + 横向工具

```
backend/src/
├── api/         (横向：HTTP 入口，无业务)
├── agent/       (垂直：编排能力)
├── rag/         (垂直：检索增强能力)
├── llm/         (横向：LLM 客户端抽象)
├── storage/     (横向：持久化抽象)
├── simulator/   (垂直：WHCNS 仿真能力)
├── utils/       (横向：通用工具)
├── config.py
└── main.py
```

每个模块的 `README.md` 说明其职责边界。**关键纪律**：

- `api/` 不写业务逻辑，仅做参数校验 + 调度
- `agent/` 不直接调 OpenAI SDK，必须经 `llm/`
- `utils/` 不放业务，只放跨模块通用工具
- 模块间禁止反向依赖（如 `llm/` 不能 import `agent/`）

这套切分是论文 "系统设计" 一章的章节骨架。

### 3.5 前端：从脚手架到"项目自有页面"的最小修改

`pnpm create next-app` 生成的默认 `src/app/page.tsx` 是 Vercel 模板。
本次保留所有结构，仅替换 `page.tsx` 内容为业务页面，并改两处
`layout.tsx`：

- `lang="en"` → `lang="zh-CN"`
- metadata title / description 改为项目专属

**为什么不重写**：脚手架的字体加载、Tailwind 配置、文件命名都是
Next 16 的最佳实践。重写要么照抄、要么踩坑，不如复用。

### 3.6 shadcn/ui 配色：手动落地 Slate

新版 shadcn CLI（commit 时已是 latest）不再接受 `--base-color slate`
参数；预设 (`preset`) 系统改用星系命名 `nova/vega/maia/...`，
与色板解耦。本次方案：

1. `pnpm dlx shadcn@latest init --defaults` 用 nova preset 初始化
2. 手改 `frontend/components.json` 的 `baseColor` 字段为 `"slate"`
3. 手写 `frontend/src/app/globals.css` 中 `:root` 与 `.dark` 块的
   `oklch(...)` 值为 Tailwind slate 调色板的官方值

slate 与 nova 默认的 neutral 区别在 **色相略偏冷蓝**（`oklch` 第三位
非 0），视觉更"科研感"，契合农业 / 环境领域的严谨基调。

## 4 重点代码导读

### 4.1 后端：health 路由（4 行核心）

`backend/src/api/health.py:8`：

```python
@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok",
            "service": "nitrogen-leaching-agent-backend",
            "version": "0.1.0"}
```

JSON 三个字段都是契约：

- `status` 给 LB / k8s 探针读
- `service` 给多服务环境下的日志聚合系统读
- `version` 给前端 / 客户端做兼容性判断（未来会接 `__version__`）

### 4.2 后端：CORS 装配

`backend/src/main.py:30`：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

注意 `cors_origin_list` 是 `Settings` 的 **计算属性**（`@property`），
从逗号分隔字符串生成 list。这种写法兼顾了 "`.env` 文件易写" 与
"FastAPI 中间件需要 list" 两种诉求。

### 4.3 后端：测试 — 用 TestClient 不启服务

`backend/tests/test_health.py`：

```python
client = TestClient(app)

def test_health_endpoint_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    ...
```

`TestClient` 直接以 ASGI 调用栈调起 app，不开端口、不走真实 HTTP，
跑得快、隔离好，是 FastAPI 项目的事实标准测试入口。

### 4.4 前端：状态机 + fetch 错误兜底

`frontend/src/app/page.tsx:18`：

```tsx
type HealthResult =
  | { ok: true; data: unknown }
  | { ok: false; error: string };

async function checkHealth() {
  setLoading(true); setResult(null);
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    if (!response.ok) {
      setResult({ ok: false, error: `HTTP ${response.status} ${response.statusText}` });
      return;
    }
    const data: unknown = await response.json();
    setResult({ ok: true, data });
  } catch (err) {
    setResult({ ok: false, error: err instanceof Error ? err.message : String(err) });
  } finally {
    setLoading(false);
  }
}
```

要点：

- `HealthResult` 用 **判别联合**（discriminated union）建模成功 / 失败
  两态，UI 渲染时类型收窄无需 `as any`
- `data: unknown` 而非 `any`，强迫调用方显式处理类型
- HTTP 错误 + 网络错误两类都有兜底，不会出现"按钮点完没反应"

未来 M1 / M2 的所有 fetch 调用都应遵循这个模式。可以抽到 `lib/api.ts`，
但本次不做，避免过早抽象。

### 4.5 前端：API base URL 来自环境变量

```tsx
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
```

`NEXT_PUBLIC_*` 是 Next.js 的约定：编译时注入到客户端 JS。
本地用默认值，生产 / 预览环境通过 `.env.production` 或 Vercel 控制台
覆盖。**禁止**把后端地址写成相对路径（如 `/api/health`），因为
ADR-001 决定前后端独立部署，未来后端域名可能与前端不同。

## 5 验证方法

详见 [`review.md`](./review.md) §4。本节补充几个 **可复现** 的快速命令：

```bash
# 一键验证后端
cd backend && uv sync && uv run pytest && \
  uv run uvicorn src.main:app --port 8000 &
sleep 2 && curl -s --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health

# 一键验证前端
cd frontend && pnpm install && pnpm exec tsc --noEmit && pnpm lint && \
  pnpm exec next dev -H 0.0.0.0 -p 3000 &
sleep 5 && curl -s --noproxy 127.0.0.1 http://127.0.0.1:3000 | grep "氮淋失"
```

## 6 偏离原始规范的清单与理由

| 原规范 | 实际实现 | 理由 |
|---|---|---|
| `uv init` 默认包模式 | 改为扁平 `src/`，删 `[build-system]` | 见 §3.1 |
| `on_event("startup")` | 改为 `lifespan` | 弃用警告 + 预留 LLM 初始化 |
| shadcn `--base-color slate` | 用 `--defaults` + 手改 components.json + globals.css | 新版 CLI 已无该参数 |
| `pnpm dev -- -H 0.0.0.0` | `pnpm exec next dev -H 0.0.0.0` | pnpm 把 `--` 之后参数当 project dir，会报 ENOENT |

## 7 已知坑与缓解

### 7.1 樱花猫 VPN 拦截 localhost

WSL2 shell 中存在以下代理变量（来自宿主 Windows 的樱花猫客户端）：

```
http_proxy=http://127.0.0.1:7897
HTTP_PROXY=http://1.1.1.1
ALL_PROXY=http://1.1.1.1
```

直接 `curl http://127.0.0.1:8000` 返回 `502 Bad Gateway`。
**缓解**：所有本地 curl 加 `--noproxy 127.0.0.1,localhost`；
浏览器侧需在樱花猫面板把 localhost 加入直连规则。
此条记入 `docs/development.md` 与项目记忆。

### 7.2 Next.js 16 / shadcn 新版超出训练数据

Next 16 (App Router 默认 + Turbopack 默认 + React 19) 与 shadcn
新版 CLI 都晚于本会话所用模型的训练数据。前端目录下自带
`frontend/AGENTS.md` + `frontend/CLAUDE.md` 警示。
**缓解**：未来改前端代码前必读 `frontend/node_modules/next/dist/docs/`。

## 8 与下一迭代（M1）的衔接

M1 目标：基础对话闭环（用户提问 → RAG 检索 → LLM 生成带引用回答）。
本次迭代留下的"挂载点"：

| M1 需要的能力 | 本次留下的挂载点 |
|---|---|
| `POST /api/chat` 接口 | 在 `backend/src/api/` 新增 `chat.py`，套用 `health.py` 的 router 模式 |
| LLM 客户端 | `backend/src/llm/` 已是空模块，预留 `LLMClient` 抽象基类位置 |
| 文档检索 | `backend/src/rag/` 已是空模块；Chroma 持久化目录由 `Settings.chroma_persist_dir` 控制 |
| 会话状态 | `backend/src/storage/` 已是空模块；`Settings.database_url` 默认 SQLite |
| 前端聊天 UI | `frontend/src/app/page.tsx` 现为 Hello World，可直接替换为聊天界面；shadcn Button 已就绪，按需 add `input`/`textarea`/`scroll-area` 等组件 |
| 配置项 | DeepSeek key、Chroma 目录、模型名均已在 `Settings` 占位 |

## 9 度量基线

将以下数据作为 M0 完成时的"出厂值"，便于 M1 后回看：

| 指标 | 值 |
|---|---|
| 后端代码行数（非空） | 约 65 行（main.py + config.py + health.py + lifespan） |
| 后端单测数 | 1 |
| 后端冷启时间 | 0.49s（pytest 全套） |
| 前端 dev server 冷启 | 862ms (Turbopack) |
| 前端首页编译时间 | 见 `pnpm dev` 首次 GET 日志 |
| Python 依赖安装包数 | 29 |
| Node 依赖（生产） | 3 |
| Node 依赖（开发） | 8 + shadcn 装入 |

## 10 参考与延伸阅读

- ADR 全集：[`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md)
- 提交规范：[`docs/COMMIT_CONVENTION.md`](../../COMMIT_CONVENTION.md)
- 启动指引：[`docs/development.md`](../../development.md)
- Cockburn, A. *Crystal Clear*, 2004 — Walking Skeleton 原始定义
- FastAPI 官方 Lifespan Events：<https://fastapi.tiangolo.com/advanced/events/>
- shadcn/ui 文档（最新）：<https://ui.shadcn.com/docs>
