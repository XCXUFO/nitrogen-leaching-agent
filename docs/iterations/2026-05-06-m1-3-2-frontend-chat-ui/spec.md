# 说明文档 — M1.3.2 前端最小 Chat UI

> 本文档已回填实现与验证结果（v1.1）；落库 commit 见 §1。
> 上承 M1.3.1（`POST /api/chat` 已稳定），下接 M1.4（评测）。
> 目标：把 Walking Skeleton 前端从 health 探测页改造为**单轮**聊天页，
> 用户能在浏览器问答、看到带引用的回答、看到清晰的错误状态。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代名 | m1-3-2-frontend-chat-ui |
| 日期 | 2026-05-06 |
| 涉及 commit | `1c40ca5` feat(frontend) / `4b90906` docs spec+report / `c959456` docs review refresh |
| 文档版本 | v1.1（实现回填） |
| 父里程碑 | M1.3（前后端 RAG Chat 闭环） |
| 实现 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 范围

### 2.1 在做

把 M1.3.1 已稳定的 `POST /api/chat` 串到现有 Next.js 16 前端上：

1. **页面替换**：`src/app/page.tsx` 从 health 探测页改成 chat 页
   - 保留对 `NEXT_PUBLIC_API_BASE_URL` 的读取
   - 把 health 探测降级为页面底部"调试"折叠区（小字、不抢主流程视觉）
2. **API 客户端**：`src/lib/api.ts` 新增
   - `postChat(query, k?, signal?)`：返回 `ChatResponse` 或抛 `ApiError`
   - `getHealth(signal?)`：留给底部 debug 区
   - 统一异常翻译：HTTP 状态 + `detail.code` → `ApiError`
3. **类型定义**：`src/lib/types.ts` 新增
   - 与后端 `chat_schema.py` / `chat_service.Citation` / `llm.base.ChatUsage` 同形的 TS interface（手写镜像，**不**引代码生成器）
4. **错误码映射**：`src/lib/error-messages.ts` 新增
   - `detail.code` → 中文用户文案 map（见 §5）
   - 网络层失败 / 未识别 code 各有 fallback
5. **UI 组件**（`src/components/chat/`，新增子目录）：
   - `chat-form.tsx`：`<textarea>` + 提交按钮 + 字符计数
   - `chat-message.tsx`：渲染单条 user / assistant 消息（纯文本 `whitespace-pre-wrap`）
   - `citation-list.tsx`：渲染 citations 数组（默认折叠）
   - `chat-error.tsx`：错误条
6. **shadcn 组件按需补齐**：实现期先 `ls src/components/ui/` 看现有；缺什么补什么。**不预设**清单，避免 churn。当前已知：仅 `button.tsx`。
7. **健康调试入口**：保留但弱化
   - `src/components/debug/health-probe.tsx` 新增：复用原"测试后端连接"按钮逻辑
   - 在 chat 页底部以 `<details>` 折叠展示，标题"调试 / Backend health"
8. **文档**：
   - `frontend/README.md` 加"启动 chat 的前置条件 + 故障排查"段
   - `frontend/.env.local.example` 注释里说明本变量不变，但需后端 `RAG_ENABLED=true`

### 2.2 不在做（明确边界）

- ❌ 多轮历史 / 消息列表本地存储 → M2
- ❌ SSE / 流式输出 → M2
- ❌ Markdown 渲染（含数学公式 / 代码高亮）→ 本迭代用纯文本 + `whitespace-pre-wrap`，避免引 `react-markdown` 等大依赖；XSS、样式、表格、代码块的级联决策推到 M2
- ❌ Citation 点击跳原文（需要 `/api/chunk/{id}`，M2）
- ❌ 鉴权 / 用户体系 / `session_id` 实际使用 → 不发该字段
- ❌ vitest / Jest / RTL 单测框架引入 → M2 引入多轮 / 流式时再上，那时状态机复杂，收益更高
- ❌ Playwright E2E → M1.4 评测期一并评估
- ❌ 移动端适配精修 / 暗色主题精修 → 沿用 Tailwind 4 默认
- ❌ 后端任何改动 → 契约已稳，前端只消费

### 2.3 计划变更清单

| 项 | 文件 | 内容要点 |
|---|---|---|
| 主页改造 | `frontend/src/app/page.tsx` 修改 | 用 chat UI 替换 health 探测；底部加 health debug 折叠区 |
| API 客户端 | `frontend/src/lib/api.ts` 新增 | `postChat` / `getHealth` / `ApiError` |
| 类型镜像 | `frontend/src/lib/types.ts` 新增 | `ChatRequest` / `ChatResponse` / `Citation` / `ChatUsage` |
| 错误文案 | `frontend/src/lib/error-messages.ts` 新增 | `detail.code` → 中文 map |
| 输入区 | `frontend/src/components/chat/chat-form.tsx` 新增 | textarea + submit + 字符计数 |
| 消息气泡 | `frontend/src/components/chat/chat-message.tsx` 新增 | role-aware 渲染 |
| 引用列表 | `frontend/src/components/chat/citation-list.tsx` 新增 | 折叠展示 source / score / snippet |
| 错误条 | `frontend/src/components/chat/chat-error.tsx` 新增 | 按 code 切文案 |
| Health 调试 | `frontend/src/components/debug/health-probe.tsx` 新增 | 沿用原按钮逻辑，仅迁移到独立组件 |
| shadcn 增量 | `frontend/src/components/ui/` 修改（视实测） | 实现期 ls 后按需 `pnpm dlx shadcn add ...` |
| 环境变量样例 | `frontend/.env.local.example` 修改 | 注释补 backend RAG_ENABLED 前置 |
| README | `frontend/README.md` 修改 | 启动步骤 + 故障排查 |

## 3 关键判断

### 3.1 单一 client component 主页 + 子组件，不引 React Query / SWR

```
app/page.tsx ("use client")
  ├── <ChatForm />              ← onSubmit 回调上报到 page
  ├── <ChatMessage />[]         ← 消息列表（本迭代最多 1 user + 1 assistant）
  ├── <CitationList />          ← 跟在 assistant 消息下
  ├── <ChatError />             ← 错误态时渲染
  └── <details><HealthProbe /></details>  ← 底部弱化的调试入口
```

**理由**：

- 单轮交互 `useState + fetch` 足够；引状态库是 M2 多轮 / 流式才有价值
- 单一 page 持状态、子组件纯展示 + 回调，便于阅读，便于 M2 抽 `useChat` hook
- `"use client"` 加在 page 上即可，子组件继承（M1.3.1 前端框架笔记）

**反模式**：把 fetch 散在每个子组件里 → 状态分裂、loading 难协同、M2 改造代价大。

### 3.2 错误状态机集中在 `lib/api.ts`

```ts
class ApiError extends Error {
  constructor(
    public readonly code: string,           // detail.code 或合成的 'network' / 'unknown'
    public readonly httpStatus: number | null,
    public readonly userMessage: string,    // 已翻译过的中文文案
    cause?: unknown,
  ) { super(userMessage, { cause }); }
}
```

`postChat` 内部捕获三类错误并抛 `ApiError`：

1. **fetch 网络层失败**（DNS / connection / abort）：`code='network'`
2. **HTTP 非 2xx**：解析 body 取 `detail.code`；解析失败时 `code='unknown'`
3. **422 Pydantic**：FastAPI 默认结构体（`detail` 是数组），单独处理，提取首条 message

UI 层只看 `error.code` + `error.userMessage`，**不**直接读 HTTP status。

### 3.3 Citation 默认折叠

- 折叠：减少视觉噪声，回答本身才是主体
- 展开后每条显示：`[N]` 标号、source 文件名（取 path basename）、score（保留 3 位小数）、snippet（≤100 字，超出加 `…`）
- 用原生 `<details>` / `<summary>`，不引 shadcn collapsible（如 Tailwind 4 默认 prose 已能渲染好就用，否则再补）

### 3.4 加载态与冷启动提示

- 提交后立即禁用 form，按钮文案 "正在思考…"
- 加载持续 > 3 秒时再额外显示一行 hint："首次响应较慢（~10 秒），后端可能正在加载嵌入模型"
- 这条 hint 是 M1.3.1 spec §8 风险 6 的反推：BGE 首次冷加载 ~5–10s

实现：`useEffect` + `setTimeout` 在 loading 进入 3 秒后置一个 `slowHint` flag。

### 3.5 纯文本渲染，已知会丑，写明限制

DeepSeek 大概率吐 markdown 列表 / 加粗，本迭代渲染为 `<pre className="whitespace-pre-wrap break-words">{answer}</pre>`：

- `whitespace-pre-wrap`：保留换行 + 自动折行
- `break-words`：超长无空格字符串（URL）也能折
- 接受 `**强调**` `## 标题` 以源码形式可见 —— 这是已知妥协，README 故障排查段写明

**何时升级**：M2 引入流式时统一接 `react-markdown` + `rehype-sanitize`，那时一并解决 XSS、表格、代码块。

### 3.6 Citation 内联标号 `[N]` 的渲染

LLM 回答里会出现 `[1]` `[2][3]` 这类标记。本迭代：

- **不做**任何特殊渲染（不变成超链接、不上标）
- 用户能在文本里看到 `[N]`，对应展开 citation 列表第 N 条
- 视觉上够用；M2 上 markdown 渲染时再升级为可点击锚点

**理由**：自定义 `[N]` 解析器需要正则 + JSX 拼接，30+ 行代码，本迭代不值得；纯文本对照已能达成"看到引用→展开找出处"目标。

### 3.7 输入校验：前端先拦一道

- `query.trim().length === 0`：禁用提交按钮
- `query.length > 1000`：字符计数变红 + 禁用提交按钮
- 仍提交时显示前端校验错误，**不**发请求

后端有同款校验（`min_length=1` + `max_length=1000` + `strip` 后判空）。前端这层只是减少无效请求 + UX 即时反馈。**不**做正则 / 关键词过滤等"业务校验"。

### 3.8 Next.js 16 注意点（实现期需查 node_modules/next/dist/docs）

- 所有用 `useState` / `onClick` / `useEffect` 的组件加 `"use client"`
- `NEXT_PUBLIC_API_BASE_URL` 走 build-time inline，不通过 server 侧 `process.env` 读
- 不使用 RSC `fetch` cache（chat 是 mutation，本来也不该缓存）
- `app/layout.tsx` 维持 server component（Geist 字体已就位，不动）
- 实现期参考：
  - `01-getting-started/05-server-and-client-components.md`
  - `01-getting-started/06-fetching-data.md`
  - `01-getting-started/07-mutating-data.md`
  - `02-guides/data-security.md`

### 3.9 health 调试入口的取舍

直接删 → 演示 / 排障时少一个快速验证 API base URL 的入口；
保留为 `/health` 子路由 → 多一个路由段，绕路；
**采保留为底部折叠区**：

```tsx
<details className="mt-12 text-xs text-muted-foreground">
  <summary className="cursor-pointer">调试 / Backend health</summary>
  <HealthProbe />
</details>
```

不抢视觉、必要时 1 秒打开、本地排障留底牌。

### 3.10 不在 fetch 上做超时 / 重试

- 后端默认无 timeout 上限；DeepSeek 慢请求可能 30s+
- 加客户端 timeout 反而会让正常慢请求被误杀
- `RateLimitError` 后端已翻译为 429 + `llm_rate_limited`，前端展示文案让用户手动重试即可
- 重试逻辑放 M2（届时会有指数退避 + 用户取消按钮）

### 3.11 不引前端测试框架的成本与时机

| 不补的代价 | 不补的好处 |
|---|---|
| 错误状态机分支无自动覆盖 | 节省 4–6h 工程（vitest + RTL + happy-dom 配置） |
| 改 ChatForm 时只能靠浏览器手动 smoke | 维护栈最小化 |
| 重构压力大时心理负担 | M1 是单用户演示，重构频率低 |

**触发上 vitest 的条件**：M2 引入多轮 / 流式 / 工具调用，状态机分支爆炸时（届时手动测覆盖不到关键路径）。

## 4 实现细节

### 4.1 `lib/types.ts` 草图

```ts
// 与 backend/src/llm/base.py::ChatUsage 同形
export interface ChatUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

// 与 backend/src/agent/chat_service.py::Citation 同形
export interface Citation {
  index: number;
  chunk_id: string;
  source: string;
  score: number;
  snippet: string;
}

// 与 backend/src/api/chat_schema.py 同形
export interface ChatRequest {
  query: string;
  k?: number;
  session_id?: string;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  usage: ChatUsage;
  retrieved_count: number;
  model: string;
}

// 后端 HTTPException(detail={"code":..., "message":...}) 的形状
export interface BackendErrorDetail {
  code: string;
  message: string;
}
```

### 4.2 `lib/api.ts` 草图

```ts
import type { ChatRequest, ChatResponse, BackendErrorDetail } from "./types";
import { translateErrorCode, NETWORK_FAILURE, UNKNOWN_FAILURE } from "./error-messages";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    public readonly httpStatus: number | null,
    public readonly userMessage: string,
    cause?: unknown,
  ) {
    super(userMessage, { cause });
    this.name = "ApiError";
  }
}

export async function postChat(
  body: ChatRequest,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    throw new ApiError("network", null, NETWORK_FAILURE, err);
  }

  if (response.ok) {
    return (await response.json()) as ChatResponse;
  }

  // 422: FastAPI 默认 ValidationError 体
  if (response.status === 422) {
    const data = (await safeJson(response)) as
      | { detail?: Array<{ msg?: string }> }
      | null;
    const msg = data?.detail?.[0]?.msg ?? "输入校验失败";
    throw new ApiError("validation_error", 422, `输入校验失败：${msg}`);
  }

  // 业务错误：detail = {code, message}
  const data = (await safeJson(response)) as
    | { detail?: BackendErrorDetail | string }
    | null;
  if (data && typeof data.detail === "object" && data.detail.code) {
    const userMessage = translateErrorCode(data.detail.code);
    throw new ApiError(data.detail.code, response.status, userMessage);
  }
  throw new ApiError("unknown", response.status, UNKNOWN_FAILURE);
}

export async function getHealth(signal?: AbortSignal): Promise<unknown> {
  const r = await fetch(`${API_BASE_URL}/api/health`, { signal });
  if (!r.ok) throw new ApiError("unknown", r.status, UNKNOWN_FAILURE);
  return r.json();
}

export const apiBaseUrl = API_BASE_URL;

async function safeJson(r: Response): Promise<unknown | null> {
  try {
    return await r.json();
  } catch {
    return null;
  }
}
```

### 4.3 `lib/error-messages.ts` 草图

```ts
const MESSAGES: Record<string, string> = {
  rag_not_configured:
    "后端检索服务未启用，请联系管理员开启 RAG_ENABLED 并完成索引。",
  rag_query_failed:
    "检索过程出错，请稍后重试或检查向量库索引是否完整。",
  llm_unreachable:
    "无法连接到大模型服务，请检查网络后重试。",
  llm_rate_limited:
    "请求过于频繁，请稍后重试。",
  llm_upstream_error:
    "大模型服务暂时不可用，请稍后重试。",
  llm_auth_failed:
    "大模型 API key 配置异常，请联系管理员。",
};

export const NETWORK_FAILURE =
  "请求未发出，请检查后端是否启动（http://localhost:8000）。";

export const UNKNOWN_FAILURE =
  "请求失败，请稍后重试或查看浏览器控制台。";

export function translateErrorCode(code: string): string {
  return MESSAGES[code] ?? UNKNOWN_FAILURE;
}
```

### 4.4 `app/page.tsx` 骨架

```tsx
"use client";

import { useState, useEffect } from "react";
import { ChatForm } from "@/components/chat/chat-form";
import { ChatMessage } from "@/components/chat/chat-message";
import { CitationList } from "@/components/chat/citation-list";
import { ChatError } from "@/components/chat/chat-error";
import { HealthProbe } from "@/components/debug/health-probe";
import { postChat, ApiError, apiBaseUrl } from "@/lib/api";
import type { ChatResponse } from "@/lib/types";

type AssistantTurn =
  | { kind: "loading"; slow: boolean }
  | { kind: "ok"; response: ChatResponse }
  | { kind: "error"; error: ApiError };

export default function Home() {
  const [userQuery, setUserQuery] = useState<string | null>(null);
  const [assistant, setAssistant] = useState<AssistantTurn | null>(null);
  const [slowTimer, setSlowTimer] = useState<number | null>(null);

  async function handleSubmit(query: string) {
    setUserQuery(query);
    setAssistant({ kind: "loading", slow: false });
    const t = window.setTimeout(
      () => setAssistant((a) => (a?.kind === "loading" ? { kind: "loading", slow: true } : a)),
      3000,
    );
    setSlowTimer(t);
    try {
      const response = await postChat({ query });
      setAssistant({ kind: "ok", response });
    } catch (err) {
      const error = err instanceof ApiError
        ? err
        : new ApiError("unknown", null, "未知错误");
      setAssistant({ kind: "error", error });
    } finally {
      if (slowTimer !== null) window.clearTimeout(slowTimer);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col gap-6 px-6 py-10">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          氮淋失风险决策 Agent
        </h1>
        <p className="text-muted-foreground text-xs">
          单轮问答 · 基于本地论文知识库 · 回答带引用
        </p>
      </header>

      <ChatForm onSubmit={handleSubmit} disabled={assistant?.kind === "loading"} />

      {userQuery && <ChatMessage role="user" content={userQuery} />}

      {assistant?.kind === "loading" && (
        <ChatMessage role="assistant" content="正在思考…" pending slowHint={assistant.slow} />
      )}
      {assistant?.kind === "ok" && (
        <>
          <ChatMessage role="assistant" content={assistant.response.answer} />
          <CitationList citations={assistant.response.citations} retrievedCount={assistant.response.retrieved_count} />
        </>
      )}
      {assistant?.kind === "error" && <ChatError error={assistant.error} />}

      <details className="mt-auto pt-8 text-xs text-muted-foreground">
        <summary className="cursor-pointer">调试 / Backend health</summary>
        <div className="mt-2 space-y-2">
          <p>API base: <code>{apiBaseUrl}</code></p>
          <HealthProbe />
        </div>
      </details>
    </main>
  );
}
```

### 4.5 `chat-form.tsx` 草图

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

const MAX_LEN = 1000;

interface Props {
  onSubmit: (query: string) => void;
  disabled?: boolean;
}

export function ChatForm({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState("");
  const trimmed = value.trim();
  const tooLong = value.length > MAX_LEN;
  const canSubmit = !disabled && trimmed.length > 0 && !tooLong;

  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) onSubmit(trimmed);
      }}
    >
      <textarea
        className="w-full rounded-md border bg-background p-3 text-sm focus:outline-none focus:ring-2"
        rows={3}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="例如：氮素淋失主要受什么因素影响？"
        disabled={disabled}
      />
      <div className="flex items-center justify-between">
        <span className={`text-xs ${tooLong ? "text-destructive" : "text-muted-foreground"}`}>
          {value.length} / {MAX_LEN}
        </span>
        <Button type="submit" disabled={!canSubmit}>
          {disabled ? "正在思考…" : "提交"}
        </Button>
      </div>
    </form>
  );
}
```

### 4.6 `chat-message.tsx` 草图

```tsx
interface Props {
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  slowHint?: boolean;
}

export function ChatMessage({ role, content, pending, slowHint }: Props) {
  const isUser = role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={`max-w-[85%] rounded-lg px-4 py-3 text-sm ${
          isUser ? "bg-primary text-primary-foreground" : "bg-muted"
        }`}
      >
        <pre className="whitespace-pre-wrap break-words font-sans">
          {content}
        </pre>
        {pending && slowHint && (
          <p className="mt-2 text-xs opacity-70">
            首次响应较慢（约 10 秒），后端可能正在加载嵌入模型…
          </p>
        )}
      </div>
    </div>
  );
}
```

### 4.7 `citation-list.tsx` 草图

```tsx
import type { Citation } from "@/lib/types";

interface Props {
  citations: Citation[];
  retrievedCount: number;
}

export function CitationList({ citations, retrievedCount }: Props) {
  if (citations.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        本次回答未召回知识库资料（retrieved_count = {retrievedCount}）
      </p>
    );
  }
  return (
    <details className="rounded border bg-muted/40 px-4 py-2 text-xs">
      <summary className="cursor-pointer text-muted-foreground">
        引用来源（{citations.length}）
      </summary>
      <ol className="mt-2 space-y-2">
        {citations.map((c) => (
          <li key={c.chunk_id} className="space-y-0.5">
            <div className="font-mono text-[11px] text-muted-foreground">
              [{c.index}] {basename(c.source)} · score {c.score.toFixed(3)}
            </div>
            <p className="text-foreground">{c.snippet}…</p>
          </li>
        ))}
      </ol>
    </details>
  );
}

function basename(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] ?? path;
}
```

### 4.8 `chat-error.tsx` 草图

```tsx
import type { ApiError } from "@/lib/api";

interface Props {
  error: ApiError;
}

export function ChatError({ error }: Props) {
  return (
    <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
      <p>{error.userMessage}</p>
      <p className="mt-1 text-xs opacity-70">
        错误码：<code>{error.code}</code>
        {error.httpStatus !== null && <> · HTTP {error.httpStatus}</>}
      </p>
    </div>
  );
}
```

### 4.9 `debug/health-probe.tsx` 草图

把原 `app/page.tsx` 里的 health 探测逻辑迁过来，独立成可复用组件。
点击按钮调 `/api/health`，结果 JSON 用 `<pre>` 展示。

### 4.10 shadcn 增量决策（实现期补）

实现期先：

```bash
ls frontend/src/components/ui/
```

按缺失补：

| 可能用到的 | 当前状态 | 决策 |
|---|---|---|
| Button | ✅ 已有 | 不动 |
| Textarea | ❓ 待检查 | 缺则补，否则用裸 `<textarea>` + Tailwind |
| Card / Alert / Badge | ❓ 待检查 | 优先用裸 div + Tailwind；只有需要 a11y / 一致性强语义时才补 |

**原则**：能用 Tailwind utility class + 原生 element 实现的就不补 shadcn 组件，避免无意义 churn。Textarea 是唯一比较可能值得补的（因为有 focus ring 一致性诉求）。

### 4.11 `frontend/.env.local.example` 增量

```env
# Copy to .env.local and adjust as needed.
# NEVER commit .env.local to the repository.

# Backend API base URL (no trailing slash).
# 注意：M1.3 起 chat 页需要后端启用 RAG（backend/.env 设 RAG_ENABLED=true 并已建索引），
# 否则 /api/chat 会返回 503 + 错误码 rag_not_configured。
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

### 4.12 `frontend/README.md` 增量段（草稿）

新增一段"启动 chat 完整闭环"：

1. 后端：`cd backend && uv sync --extra rag`
2. 后端：建索引 `uv run python scripts/index_papers.py --paths ../data/papers/sample.txt --persist-dir var/chroma --collection papers --repo-root ..`
3. 后端：`backend/.env` 设 `RAG_ENABLED=true` `RAG_CHROMA_DIR=./var/chroma`
4. 后端：`uv run uvicorn src.main:app --reload`
5. 前端：`cp .env.local.example .env.local`
6. 前端：`pnpm dev`
7. 浏览器：`http://localhost:3000`，问问题
8. 故障排查：
   - 看不到回答 → 打开页面底部"调试"区点 health 按钮验证连通
   - 503 `rag_not_configured` → 后端 `.env` 没设 `RAG_ENABLED=true`
   - 503 `rag_query_failed` → chroma 索引目录不对或为空
   - 502 `llm_unreachable` → 樱花猫 VPN 把 `127.0.0.1` 加 ByPass

## 5 错误码 → 用户文案映射

| 后端 `detail.code` | HTTP | 前端 `userMessage` |
|---|---|---|
| `rag_not_configured` | 503 | 后端检索服务未启用，请联系管理员开启 RAG_ENABLED 并完成索引。 |
| `rag_query_failed` | 503 | 检索过程出错，请稍后重试或检查向量库索引是否完整。 |
| `llm_unreachable` | 502 | 无法连接到大模型服务，请检查网络后重试。 |
| `llm_rate_limited` | 429 | 请求过于频繁，请稍后重试。 |
| `llm_upstream_error` | 502 | 大模型服务暂时不可用，请稍后重试。 |
| `llm_auth_failed` | 500 | 大模型 API key 配置异常，请联系管理员。 |
| `validation_error` (合成) | 422 | 输入校验失败：{detail[0].msg} |
| `network` (合成) | — | 请求未发出，请检查后端是否启动（http://localhost:8000）。 |
| `unknown` (合成) | * | 请求失败，请稍后重试或查看浏览器控制台。 |

## 6 测试策略

前端**当前无单测框架**，本迭代不引入。沿用三层兜底：

### 6.1 编译 / 静态检查（必过）

| # | 命令 | 期望 |
|---|---|---|
| 1 | `cd frontend && pnpm install` | 干净，无新增 peerDep warning |
| 2 | `cd frontend && pnpm lint` | 0 error；warning 不增加 |
| 3 | `cd frontend && pnpm build` | 编译通过；无 `'use client'` 误用错误 |

### 6.2 浏览器手动 smoke（写入 review.md 作证据）

前置：后端启动 `RAG_ENABLED=true` + 索引就绪 + DeepSeek key 有效。

| # | 步骤 | 期望 |
|---|---|---|
| 1 | 打开 `http://localhost:3000` | 看到 chat 输入框；底部"调试"折叠区可见但默认折叠 |
| 2 | 提交"氮素淋失主要受什么因素影响？" | 5–15s 内显示回答 + ≥1 条 citation |
| 3 | 展开 citations | 看到 source / score / snippet |
| 4 | 提交空字符串 | 提交按钮禁用，前端不发请求 |
| 5 | 提交 1001 字符（粘贴长串） | 字符计数变红，提交按钮禁用 |
| 6 | 关掉后端再提交 | 错误条："请求未发出…"；code=`network` |
| 7 | 后端临时改 `RAG_ENABLED=false` 重启 | 错误条："后端检索服务未启用…"；code=`rag_not_configured` |
| 8 | 展开"调试"区点 health | 显示 `{"status":"ok"}`（或后端实际响应） |
| 9 | 桌面 Chrome / Edge 各看一眼 | 布局不破，文字不溢 |

### 6.3 后端契约回归（本迭代不动后端，仅校验未破坏）

```bash
cd backend && uv run pytest -q
```

期望：当前基线 **`101 passed, 3 skipped`** 不退化。

### 6.4 关于"是否要补单测"

**本迭代决策：不补**。
触发上 vitest 的条件：M2 引入多轮 / 流式 / 工具调用，状态机分支爆炸时（届时手动 smoke 覆盖不到关键路径）。

## 7 与父 / 子里程碑的衔接

### 与 M1.3.1 后端

| M1.3.1 提供 | 本迭代如何消费 |
|---|---|
| `POST /api/chat` | `lib/api.ts::postChat` |
| `ChatRequest` schema | `lib/types.ts::ChatRequest`（手写镜像） |
| `ChatResponse` schema | `lib/types.ts::ChatResponse` |
| 错误码稳定字符串 | `lib/error-messages.ts` 一对一翻译 |
| CORS 已配 `localhost:3000` | 默认开发端口直接用 |

### 与 M1.4 评测

本迭代为评测期提供"人工对照基线"：评测脚本批量跑题时，UI 是研究者目视抽检的入口。所以本迭代必须**视觉清晰**（区分 user / assistant / citation），但不必**自动化**。

### 与 M2 多轮 / 流式

预留扩展点：

| M2 改动 | 本迭代留白 |
|---|---|
| 多轮历史 | 把 `useState<AssistantTurn>` 升级为 `useState<Turn[]>`；page 已是单点状态 |
| 流式 | `postChat` 升级为 `postChatStream` 返回 ReadableStream；UI 加增量拼接 |
| 抽 hook | `useChat()` 自然抽出，page 变薄 |
| Markdown / 内联引用锚点 | citation `[N]` 升级为可点击锚点 |

**反向约束**：本迭代**不**为 M2 引入抽象层（如 `useChat` hook、`Turn` 类型在多个文件出现等）。当下用最直白形式。

## 8 度量基线

| 指标 | 计划值 | 实际值 |
|---|---|---|
| 前端代码新增行数（非测试） | ≤ 350 | 347（新增 `src/lib/*`、`src/components/chat/*`、`src/components/debug/*`） |
| 修改文件数 | ≤ 12 | 11 个前端/文档文件（不含本地索引数据与既有后端未提交改动） |
| 新增运行时依赖（npm） | 0（不引 react-markdown / SWR / 状态库） | 0 |
| `pnpm build` 耗时 | < 30s | 通过；Compiled 4.2s，TypeScript 3.6s，4 个 static page |
| 浏览器 smoke 通过率 | 9/9（§6.2 全过） | 核心闭环通过；详见 `review.md`（未强制执行关后端/改 RAG 开关等破坏性负向项） |
| 后端回归 | 不退化 `101 passed, 3 skipped` | 本迭代未改后端；未重跑完整 pytest |

## 9 风险

1. **Next.js 16 不熟**：`frontend/AGENTS.md` 已警告，训练数据落后于 16。
   缓解：实现期严格遵守"先读 `node_modules/next/dist/docs/`"流程；具体看
   `01-getting-started/05-server-and-client-components.md`、`06-fetching-data.md`、
   `07-mutating-data.md`、`02-guides/data-security.md`。
2. **shadcn@4.3 注册表 / 命令名变更**：
   缓解：实现期先 `pnpm dlx shadcn --help` 看可用命令；按需逐个 add，不预设全集。
   能用裸 `<textarea>` + Tailwind 解决就不补。
3. **CORS 漏配**：后端默认只允许 `http://localhost:3000`。换端口或部署时会被拦。
   缓解：本迭代仍跑 3000；README 写明"如换端口需同步改后端 `CORS_ORIGINS` env"。
4. **首次 chat 冷启动延迟**：BGE 首次加载 5–10s，UI 不展示进度会被误判挂死。
   缓解：§3.4 设计了 3 秒后展示 slow hint。
5. **VPN / 代理拦截 localhost:8000**：MEMORY 里记的樱花猫问题。
   浏览器 fetch 走系统代理，需要在 VPN 把 `127.0.0.1` 加 ByPass。
   缓解：README 故障排查段写明（§4.12 第 8 步）。
6. **响应体积**：`chat_top_k=5` × snippet 100 字 + answer 字符串 ≈ 3–5 KB，无问题。
   LLM 超长回答（理论可达 64K token）UI 不分页可能卡顿。
   缓解：本迭代不分页，M2 评估。
7. **Markdown 裸展示丑**：DeepSeek 大概率吐 `**强调**` `## 标题`。
   缓解：接受丑，README 写明已知限制，M2 接 `react-markdown` 时统一处理。
8. **review 文档机审 LLM 选择**：M1.3.1 用 GPT-5；本迭代由 Claude Opus 4.7 实现。
   缓解：机审 LLM ≠ 实现 LLM；review.md 用 GPT-5 / 其他模型机审，
   避免本会话 Claude 又写又审。
9. **删 health 主入口的可逆性**：演示当天若想立刻验证 API base URL，
   底部折叠区需要 1 秒打开。
   缓解：§3.9 已保留为底部折叠，可逆；如反馈不便再升级。
10. **shadcn add 修改 components.json 风险**：可能写入 registry / theme 字段冲突。
    缓解：实现期先 `git diff components.json` 校验改动是否合预期，再决定是否 commit。

## 10 实施顺序

按用户确认的顺序：

1. 写 spec.md（本文档）
2. inspect frontend 现状（`ls src/components/ui/`、`grep` page.tsx 当前实现、看 next docs 关键页）
3. 写 `lib/types.ts` + `lib/api.ts` + `lib/error-messages.ts`
4. 写 chat 子组件（form / message / citation / error）
5. 改 `app/page.tsx`，把 health 探测降级为 debug 折叠区
6. 写 `frontend/README.md` + `.env.local.example` 注释
7. `pnpm lint` / `pnpm build`
8. 启后端 + 启前端，跑 §6.2 浏览器 smoke
9. 按 §6.2 结果回填 review.md（机审 LLM ≠ Claude）
10. push 前确认两份文档（spec.md v1.1 实现回填 + review.md）齐备

## 11 参考

- M1.3.1 spec：[`../2026-05-05-m1-3-1-chat-rag-route/spec.md`](../2026-05-05-m1-3-1-chat-rag-route/spec.md)
- M1.3.1 review：[`../2026-05-05-m1-3-1-chat-rag-route/review.md`](../2026-05-05-m1-3-1-chat-rag-route/review.md)
- Walking Skeleton spec：[`../2026-04-21-walking-skeleton/spec.md`](../2026-04-21-walking-skeleton/spec.md)
- ARCHITECTURE.md：ADR-001（前后端分离）/ ADR-002（用户体系延后）
- Next.js 16 docs：`frontend/node_modules/next/dist/docs/01-app/`
- frontend/AGENTS.md：Next.js 16 breaking change 警告
- `frontend/.env.local.example`：当前 env 模板
