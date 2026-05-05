# 说明文档 — M1.3.1 后端 RAG Chat API

> 本文档是 **设计阶段** 产物（v1.0），落地后回填实际 commit、统计与偏离。
> 上承 M1.2.3（Retriever 已就绪），下接 M1.3.2（前端最小 chat UI）。
> 目标：把 `Retriever + LLMClient` 串成可调用的 `POST /api/chat` 单轮接口，
> **默认可启动**，未配置 RAG 时 chat 返回 503，配置完整时走真实链路。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代名 | m1-3-1-chat-rag-route |
| 日期 | 2026-05-05 |
| 涉及 commit | `069ea67` |
| 文档版本 | v1.1（实现回填） |
| 父里程碑 | M1（基础对话闭环） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 范围

### 2.1 在做

把 M1.1（LLM 客户端）+ M1.2（RAG 索引）的两个原语串成 **可调用的单轮 RAG 问答接口**：

1. **`api/chat.py`**：FastAPI 路由
   - `POST /api/chat`：接受 `ChatRequest`，返回 `ChatResponse`
   - 未启用 RAG（`rag_enabled=False` 或 lifespan 构造失败）→ `HTTPException(status_code=503)`
   - 入参校验：query 非空、长度 ≤ 1000 字符、k ∈ [1, 20]
2. **`api/chat_schema.py`**：Pydantic models
   - `ChatRequest` / `ChatResponse` / `Citation` / `ChatUsage`（复用 `llm.base.ChatUsage`）
3. **`agent/chat_service.py`**：编排层
   - `ChatService` 类：构造期注入 `Retriever` + `LLMClient`
   - `answer(query, k) -> ChatServiceResult`：retrieve → 拼 prompt → LLM → 组装 citations
   - 内部 `await asyncio.to_thread(retriever.retrieve, query, k)` 调 sync retriever
4. **`agent/prompt.py`**：prompt builder
   - `build_messages(query, retrieved) -> list[ChatMessage]`：system + user 两条
   - `format_context(retrieved, max_chars) -> str`：把 chunks 编号 `[1] [2]...` 后拼接，按 char 预算截断
5. **`main.py` lifespan 扩展**：资源装配
   - 始终构造 `LLMClient`（key 已在 M1.1 校验）
   - 若 `settings.rag_enabled`：构造 `BGEEmbedder` + `ChromaStore` + `Retriever`，挂到 `app.state.chat_service`
   - 若 RAG 未启用或构造失败：log warning，`app.state.chat_service = None`，启动不中断
6. **`config.py` 新增 env**：
   - `rag_enabled: bool = False`
   - `rag_chroma_dir: str | None = None`（None → 用 `chroma_persist_dir` 默认）
   - `rag_collection: str = "papers"`
   - `chat_top_k: int = 5`
   - `chat_max_context_chars: int = 4000`
   - `chat_temperature: float = 0.3`
7. **测试**：
   - `tests/test_chat_schema.py`：Pydantic 验证规则
   - `tests/test_chat_prompt.py`：prompt 拼接、char 预算截断、空 retrieved 行为
   - `tests/test_chat_service.py`：FakeRetriever + FakeLLMClient 编排
   - `tests/test_chat_route.py`：FastAPI TestClient 200/400/503 三态
   - `tests/test_chat_live.py`：`RUN_LIVE_RAG_CHAT=1` 守门，真链路 smoke

### 2.2 不在做（明确边界）

- ❌ 多轮对话历史 / 会话存储 / 上下文压缩 → M2
- ❌ 流式输出（SSE / WebSocket）→ M2
- ❌ tool-calling / Agent ReAct 循环 → M2（但 `agent/` 模块为此预留）
- ❌ 重排（reranker）/ 引用反查原文 → M1.4 评测之后评估
- ❌ 后端鉴权 / `user_id` 字段实际使用（仅 schema 预留 `session_id` 可选字段）→ ADR-002，未来对接平台
- ❌ 引用质量评测（LLM 是否真按 `[N]` 标注、引用是否相关）→ M1.4
- ❌ tokenizer 精确截断 → 沿用 M1.2.2 §3.4 / M1.2.3 §3.10 字符门槛
- ❌ Markdown 高级渲染 / 数学公式 / 代码高亮 → M1.3.2 前端按需，且最小化
- ❌ 速率限制 / 缓存 / 重试 → M2 观察真实失败模式后再加

### 2.3 计划变更清单

| 项 | 文件 | 内容要点 |
|---|---|---|
| Chat 路由 | `backend/src/api/chat.py` 新增 | `router` + `POST /api/chat`；从 `request.app.state` 取 service |
| Chat schema | `backend/src/api/chat_schema.py` 新增 | `ChatRequest` / `ChatResponse` / `Citation` |
| Chat service | `backend/src/agent/chat_service.py` 新增 | `ChatService` + `ChatServiceResult` dataclass |
| Prompt builder | `backend/src/agent/prompt.py` 新增 | `build_messages` / `format_context` / `SYSTEM_PROMPT` 常量 |
| Agent 公开导出 | `backend/src/agent/__init__.py` 修改 | 导出 `ChatService` / `ChatServiceResult` / `build_messages` |
| API 公开导出 | `backend/src/api/__init__.py` 修改 | 导出 `chat.router` 让 main.py 注册（保留现状直接 import 也行）|
| Settings 新增字段 | `backend/src/config.py` 修改 | 6 个新 env 字段（见 §2.1.6）|
| Lifespan 资源装配 | `backend/src/main.py` 修改 | 构造 LLM + 可选 RAG 链路；挂 `app.state.chat_service` |
| Router 注册 | `backend/src/main.py` 修改 | `app.include_router(chat.router, prefix="/api", tags=["chat"])` |
| 测试 schema | `backend/tests/test_chat_schema.py` 新增 | 字段校验、长度边界、k 范围 |
| 测试 prompt | `backend/tests/test_chat_prompt.py` 新增 | 拼接顺序、char 预算、citation 标记 |
| 测试 service | `backend/tests/test_chat_service.py` 新增 | 编排顺序、空 retrieved fallback、LLM 异常透传 |
| 测试 route | `backend/tests/test_chat_route.py` 新增 | 200 happy / 400 invalid / 503 disabled |
| Live smoke | `backend/tests/test_chat_live.py` 新增 | `RUN_LIVE_RAG_CHAT=1` 守门 |
| `.env.example` 更新 | `backend/.env.example` 修改（如存在） | 列出 6 个新 env 默认值 + 注释 |
| 自审 README 入口 | `backend/src/api/README.md` 修改 | 简述 chat 路由 + RAG 启用步骤 |

## 3 关键判断

### 3.1 默认 `rag_enabled=False`，启动不被 BGE/Chroma 绑死

**问题**：本地或 CI 没装 `rag` extra、没建 chroma 索引时，若 lifespan 强行
`BGEEmbedder()` / `ChromaStore(...)` 会直接抛 ImportError 或目录不存在，
应用启动失败，`/api/health` 也不可用。

**决策**：

- `settings.rag_enabled` 默认 `False`
- lifespan 仅在 `rag_enabled=True` 时构造 RAG 链路
- 构造失败（ImportError / 目录不存在 / chromadb 异常）时 log warning，
  把 `app.state.chat_service = None`，**启动继续**
- `POST /api/chat` 在 `chat_service is None` 时返回 `HTTPException(503,
  detail={"code": "rag_not_configured", "message": "..."})`

**何时启用**（部署 / 演示场景）：

```bash
# backend/.env
DEEPSEEK_API_KEY=sk-xxx
RAG_ENABLED=true
RAG_CHROMA_DIR=./var/chroma          # 离线索引脚本生成
RAG_COLLECTION=papers
CHAT_TOP_K=5
```

启动前先跑离线索引（M1.2.3 提供的 `scripts/index_papers.py`）。
启动后 `/api/health` 200，`/api/chat` 可用。

### 3.2 Service / Schema / Route 三层切分

```
HTTP 层（api/chat.py）            ← 只做 FastAPI 适配 + 异常翻译
  ↓
Service 层（agent/chat_service.py）← 编排：retrieve → prompt → LLM
  ↓
原语（rag.Retriever / llm.LLMClient / agent.prompt）
```

理由：

- Service 层用普通类（不依赖 FastAPI），方便单测注入 Fake
- Route 层只做"取 service / 翻译异常 / 包 response"，逻辑薄
- Schema 层独立文件，测试时 import 不带路由副作用

**反模式**：把编排塞 route handler 里 → 测试必须起 TestClient + mock app.state，
比直接 new ChatService 多一层依赖；且 service 无法被未来 CLI / 后台任务复用。

### 3.3 Service 注入而非内部 new

```python
class ChatService:
    def __init__(self, retriever: Retriever, llm: LLMClient,
                 *, top_k: int, max_context_chars: int, temperature: float) -> None:
        ...
```

- 与 M1.2.3 §3.7 Retriever 同形：不持有"如何构造依赖"的知识
- lifespan 期 new 一次复用，不在请求路径上 new
- 测试注入 FakeRetriever + FakeLLMClient

参数（top_k / max_context_chars / temperature）也走构造期注入，
**不**从 `settings` 全局读：让 service 可被多套配置实例化（未来评测场景）。

### 3.4 ChatService 是 sync 编排还是 async 编排？

**决策：async**。理由：

- LLMClient.chat 是 async（M1.1 §2.1）→ service 必须 async
- Retriever.retrieve 是 sync（M1.2.3 §3.9）→ service 内 `await asyncio.to_thread(...)`
- FastAPI 路由 `async def chat(...)` 直接 `await service.answer(...)`，无适配层

```python
async def answer(self, query: str, k: int | None = None) -> ChatServiceResult:
    effective_k = k if k is not None else self._top_k
    retrieved = await asyncio.to_thread(self._retriever.retrieve, query, effective_k)
    messages = build_messages(query, retrieved, max_context_chars=self._max_context_chars)
    chat_result = await self._llm.chat(messages, temperature=self._temperature)
    return ChatServiceResult(
        answer=chat_result.content,
        citations=_make_citations(retrieved),
        usage=chat_result.usage,
        retrieved_count=len(retrieved),
    )
```

### 3.5 Prompt 设计：context 塞 system，问题塞 user

```text
[system]
你是面向中国农业研究者的氮素淋失风险问答助手。
回答必须基于下面给出的参考资料。如果资料不足以回答，明确说"资料中未涉及"。
回答末尾用 [1][2] 形式标注引用来源。

【参考资料】
[1] (来源: data/papers/sample.txt)
土壤氮素淋失主要受降雨量、土壤质地和施肥方式影响……
[2] (来源: data/papers/zhang2023.pdf)
华北平原冬小麦-夏玉米轮作系统氮淋失通量实测……

[user]
{query}
```

**为什么 context 进 system**：

- DeepSeek / OpenAI 协议下 system 比 user 更稳定地引导风格与约束
- 避免"用户能伪造引用"问题（虽然单轮单用户场景影响小）
- 后续切多轮时，user 历史保持纯净（不夹带 RAG context）

**为什么用 `[N]` 而不是 `[chunk_id]`**：

- chunk_id 形如 `data/papers/sample::3::120-389`，进 prompt 浪费 token
- `[N]` 短、人类友好；后端用 N 反查 citations 数组对应项
- LLM 对 `[N]` 的引用习惯训练充分

**不做**：

- ❌ 强制 LLM 必须引用（提示但不校验）
- ❌ 校验输出里 `[N]` 是否合法 N（M1.4 评测做）
- ❌ 把 metadata 全塞 prompt（只塞 source）

### 3.6 字符预算，不引 tokenizer

```python
def format_context(retrieved: list[RetrievalResult], max_chars: int) -> str:
    """按引用顺序拼接 chunk text，逐条加入直到累计字符数 > max_chars 截断。
    单条 chunk 内部不截断（保持语义完整）。"""
```

- 默认 `chat_max_context_chars=4000`：约 6000 token（中英混合 1.5 char/token 估算）
- DeepSeek V3 上下文 128K，4000 char 留足回答空间
- 单条 chunk 上限由 chunker 控制（M1.2.2 max_size=450）→ 不在 service 内再裁
- 累计超 max_chars 后**整条**丢弃，不在 chunk 中段切（避免破句）

理由对齐 M1.2.2 §3.4：MVP 不让运行路径拉 transformers tokenizer。
精确 token 预算留 M1.4 评测做。

### 3.7 Citation schema：精简且稳定

```python
class Citation(BaseModel):
    index: int                   # 1-based, 对应 prompt 里的 [N]
    chunk_id: str
    source: str                  # 取自 metadata["source"]
    score: float                 # Retriever 给的相似度
    snippet: str                 # chunk text 截前 N 字（默认 100）作预览
```

**不返回完整 chunk text** 的理由：

- chunk 可能 ~450 字，n=5 时单 response ~2KB 全是 chunk
- 前端展示只需 snippet；用户点开"查看原文"再单独取（M2 加 `/api/chunk/{id}`）
- 减少响应体积，控制带宽

`source` 字段取自 chunker 写入的 `metadata["source"]`（即 CLI `--paths` 原值），
若 chunker 元数据缺 source（不应发生）则 fallback 为 `"unknown"`。

### 3.8 ChatRequest schema 字段

```python
class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    k: int | None = Field(default=None, ge=1, le=20)
    session_id: str | None = None    # 预留，本迭代不用
```

- `query` max 1000 字符：防输入失控；中文 1000 字够覆盖任何复杂问句
- `k` 可选：None → 用 `chat_top_k` 默认；显式传走 service 接口
- `session_id`：ADR-002 预留字段，本迭代仅校验类型，不消费

不做：`temperature` / `max_tokens` 等 LLM 参数对外开放 → 安全 / 成本风险。

### 3.9 ChatResponse schema 字段

```python
class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    usage: ChatUsage             # 复用 llm.base.ChatUsage
    retrieved_count: int         # 实际召回数（≤ k；空集合时 0）
    model: str                   # LLM 实际响应的 model id
```

`retrieved_count=0` 是合法状态：让前端能展示"未找到相关资料，以下是模型直答"。
service 在 0 召回时**仍调 LLM**（不短路），但 prompt 会切换到一个"无参考资料"模板：

```text
[system]
你是面向中国农业研究者的氮素淋失风险问答助手。
当前未检索到相关参考资料，请基于通用知识谨慎回答，
并明确告知用户"以下回答未引用本知识库资料"。
```

理由：短路返回固定文案 UX 太差；让 LLM 自己谨慎回答 + 提示"未引用"，
比"对不起我不知道"友好。

### 3.10 错误翻译：openai SDK 异常 → HTTP 状态

| 异常类型 | HTTP | detail.code |
|---|---|---|
| `openai.APIConnectionError` | 502 | `llm_unreachable` |
| `openai.AuthenticationError` | 500 | `llm_auth_failed` |
| `openai.RateLimitError` | 429 | `llm_rate_limited` |
| `openai.APIError` 其他 | 502 | `llm_upstream_error` |
| `chromadb` 查询异常 | 503 | `rag_query_failed` |
| Service 未配置 | 503 | `rag_not_configured` |
| ValidationError（pydantic 自动） | 422 | (FastAPI 默认格式) |

实现位置：`api/chat.py` 内一段 try/except，**不**在 service 层翻译
（service 应保持框架无关）。

### 3.11 lifespan 装配的 fail-soft 策略

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置；请检查 backend/.env")

    llm = DeepSeekClient(...)
    chat_service: ChatService | None = None

    if settings.rag_enabled:
        try:
            embedder = BGEEmbedder()                    # lazy load，构造期不下载
            chroma_dir = settings.rag_chroma_dir or settings.chroma_persist_dir
            store = ChromaStore(chroma_dir, settings.rag_collection)
            retriever = Retriever(embedder, store)
            chat_service = ChatService(
                retriever, llm,
                top_k=settings.chat_top_k,
                max_context_chars=settings.chat_max_context_chars,
                temperature=settings.chat_temperature,
            )
            logger.info("RAG enabled | chroma={} | collection={}",
                        chroma_dir, settings.rag_collection)
        except Exception as exc:
            logger.warning("RAG enabled in config but failed to initialize: {}",
                           exc, exc_info=True)
            chat_service = None
    else:
        logger.info("RAG disabled (rag_enabled=False); /api/chat returns 503")

    app.state.chat_service = chat_service
    app.state.llm = llm
    yield
    logger.info("Backend shutting down")
```

- `DEEPSEEK_API_KEY` 缺失 = 硬错（fail-fast，承袭 M1.1 §2.5）
- RAG 装配失败 = 软错（warning + 降级）：动机是开发期、文档构建期、CI 都不应被向量库状态绑死
- `BGEEmbedder()` 是 lazy 的（M1.2.1 §3.x），构造期不会下载 1.5GB 权重；
  首次 chat 调用时才加载（约 5s 冷启动延迟，spec 提示用户）

### 3.12 测试隔离：默认全 mock-free + Fake 实现

参考 M1.1 / M1.2 的"默认零外网零模型加载"原则：

| 测试 | 依赖 | 默认跑？ |
|---|---|---|
| test_chat_schema.py | 仅 pydantic | ✅ |
| test_chat_prompt.py | 仅纯函数 | ✅ |
| test_chat_service.py | FakeRetriever + FakeLLM | ✅ |
| test_chat_route.py | TestClient + 注入 fake service | ✅ |
| test_chat_live.py | 真 BGE + 真 Chroma + 真 DeepSeek | ❌（`RUN_LIVE_RAG_CHAT=1` 守门）|

`test_chat_route.py` 的关键招式：

```python
@pytest.fixture
def app_with_fake_service(monkeypatch):
    """启 FastAPI app 但替换 lifespan，跳过真实资源构造，
    把 FakeChatService 直接挂到 app.state。"""
```

`test_chat_route.py` 的 503 用例：构造一个 `app.state.chat_service = None` 的实例，
断言 `/api/chat` 返回 503 + detail.code == "rag_not_configured"。

## 4 实现细节

### 4.1 `api/chat_schema.py` 草图

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from src.llm.base import ChatUsage


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    k: int | None = Field(default=None, ge=1, le=20)
    session_id: str | None = None


class Citation(BaseModel):
    index: int = Field(..., ge=1)
    chunk_id: str
    source: str
    score: float
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    usage: ChatUsage
    retrieved_count: int
    model: str
```

### 4.2 `agent/prompt.py` 草图

```python
from __future__ import annotations

from src.llm.base import ChatMessage
from src.rag.retriever import RetrievalResult

SYSTEM_PROMPT_WITH_CONTEXT = """\
你是面向中国农业研究者的氮素淋失风险问答助手。
回答必须基于下面给出的参考资料。如果资料不足以回答，请明确说明"资料中未涉及"。
回答时请用 [1][2] 形式标注你引用的资料编号，与下方资料编号对应。

【参考资料】
{context}
"""

SYSTEM_PROMPT_NO_CONTEXT = """\
你是面向中国农业研究者的氮素淋失风险问答助手。
当前未检索到相关参考资料。请基于通用知识谨慎回答，
并在回答开头明确告知用户"以下回答未引用本知识库资料"。
"""


def format_context(retrieved: list[RetrievalResult], max_chars: int) -> str:
    """按检索顺序编号 [1][2]... 拼接，累计超 max_chars 时整条丢弃。"""
    if not retrieved:
        return ""
    pieces: list[str] = []
    used = 0
    for i, r in enumerate(retrieved, start=1):
        source = r.metadata.get("source", "unknown")
        block = f"[{i}] (来源: {source})\n{r.document}\n"
        if used + len(block) > max_chars and pieces:
            break
        pieces.append(block)
        used += len(block)
    return "\n".join(pieces)


def build_messages(
    query: str,
    retrieved: list[RetrievalResult],
    *,
    max_context_chars: int,
) -> list[ChatMessage]:
    if retrieved:
        context = format_context(retrieved, max_context_chars)
        system = SYSTEM_PROMPT_WITH_CONTEXT.format(context=context)
    else:
        system = SYSTEM_PROMPT_NO_CONTEXT
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=query),
    ]
```

### 4.3 `agent/chat_service.py` 草图

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src.agent.prompt import build_messages
from src.api.chat_schema import Citation
from src.llm.base import ChatUsage, LLMClient
from src.rag.retriever import RetrievalResult, Retriever

_SNIPPET_LEN = 100


@dataclass(frozen=True, slots=True)
class ChatServiceResult:
    answer: str
    citations: list[Citation]
    usage: ChatUsage
    retrieved_count: int
    model: str


class ChatService:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        *,
        top_k: int,
        max_context_chars: int,
        temperature: float,
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._top_k = top_k
        self._max_context_chars = max_context_chars
        self._temperature = temperature

    async def answer(self, query: str, k: int | None = None) -> ChatServiceResult:
        effective_k = k if k is not None else self._top_k
        retrieved = await asyncio.to_thread(
            self._retriever.retrieve, query, effective_k,
        )
        messages = build_messages(
            query, retrieved, max_context_chars=self._max_context_chars,
        )
        chat = await self._llm.chat(messages, temperature=self._temperature)
        return ChatServiceResult(
            answer=chat.content,
            citations=_make_citations(retrieved),
            usage=chat.usage,
            retrieved_count=len(retrieved),
            model=chat.model,
        )


def _make_citations(retrieved: list[RetrievalResult]) -> list[Citation]:
    return [
        Citation(
            index=i,
            chunk_id=r.chunk_id,
            source=str(r.metadata.get("source", "unknown")),
            score=r.score,
            snippet=r.document[:_SNIPPET_LEN],
        )
        for i, r in enumerate(retrieved, start=1)
    ]
```

⚠️ schema 跨模块 import：`agent.chat_service` import `api.chat_schema.Citation`。
这是反向依赖（业务 → HTTP 适配层）。两条出路：

- (A) 把 `Citation` 上移到 `agent/chat_service.py`，`api/chat_schema.py` re-export
- (B) 接受现状：`Citation` 是产品语义对象，恰好被 HTTP 复用

**采 (A)**：避免 agent 依赖 api。`agent/chat_service.py` 定义 `Citation`，
`api/chat_schema.py` 从 agent 导入。这样依赖方向只走 `api → agent → llm/rag`。

修订后：`Citation` 实际定义在 `agent/chat_service.py`（用 pydantic.BaseModel
保持序列化），api/chat_schema.py 写 `from src.agent.chat_service import Citation`。

### 4.4 `api/chat.py` 草图

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError

from src.agent.chat_service import ChatService
from src.api.chat_schema import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    service: ChatService | None = getattr(request.app.state, "chat_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "rag_not_configured",
                "message": "RAG 未启用或初始化失败；请检查 RAG_ENABLED 与 chroma 索引",
            },
        )

    try:
        result = await service.answer(body.query, k=body.k)
    except AuthenticationError as exc:
        logger.exception("LLM auth failed")
        raise HTTPException(500, {"code": "llm_auth_failed", "message": str(exc)}) from exc
    except RateLimitError as exc:
        raise HTTPException(429, {"code": "llm_rate_limited", "message": str(exc)}) from exc
    except APIConnectionError as exc:
        raise HTTPException(502, {"code": "llm_unreachable", "message": str(exc)}) from exc
    except APIError as exc:
        raise HTTPException(502, {"code": "llm_upstream_error", "message": str(exc)}) from exc

    return ChatResponse(
        answer=result.answer,
        citations=result.citations,
        usage=result.usage,
        retrieved_count=result.retrieved_count,
        model=result.model,
    )
```

### 4.5 `main.py` 修改要点

见 §3.11 草图。新增 import：

```python
from src.agent.chat_service import ChatService
from src.api import chat
from src.llm.deepseek import DeepSeekClient
from src.rag.bge import BGEEmbedder
from src.rag.retriever import Retriever
from src.storage.chroma_store import ChromaStore
```

⚠️ 这些 import 在模块加载期不会触发 BGE / Chroma 实际加载（lazy），但
`from src.storage.chroma_store import ChromaStore` 模块顶层已 import chromadb 风险：
查 `chroma_store.py` 现状是把 `import chromadb` 放在 `__init__` 内 try/except
（M1.2.1 已做），所以**模块 import 安全**，仅实例化时才需要 rag extra。

`app.include_router(chat.router, prefix="/api", tags=["chat"])`

### 4.6 `config.py` 新增字段

```python
rag_enabled: bool = False
rag_chroma_dir: str | None = None
rag_collection: str = "papers"
chat_top_k: int = 5
chat_max_context_chars: int = 4000
chat_temperature: float = 0.3
```

不写 `field_validator`（保持简单）。`rag_chroma_dir` 为 None 时 lifespan 内
fallback 到 `settings.chroma_persist_dir`（已有字段）。

### 4.7 `.env.example` 增量

```
# RAG 启用开关；默认 false 时 /api/chat 返回 503
RAG_ENABLED=false
RAG_CHROMA_DIR=./var/chroma
RAG_COLLECTION=papers
CHAT_TOP_K=5
CHAT_MAX_CONTEXT_CHARS=4000
CHAT_TEMPERATURE=0.3
```

（如 `backend/.env.example` 不存在则不创建；改 `backend/.env` 模板说明同步至 `backend/README.md`。）

## 5 测试策略

### 5.1 `tests/test_chat_schema.py`（默认跑）

| # | 名称 | 断言 |
|---|---|---|
| 1 | `test_chat_request_query_required` | 缺 query 抛 ValidationError |
| 2 | `test_chat_request_query_min_length` | `query=""` 抛 ValidationError |
| 3 | `test_chat_request_query_max_length` | `len(query)=1001` 抛 ValidationError；1000 通过 |
| 4 | `test_chat_request_k_optional` | 不传 k 默认 None；传 5 通过；传 0 / 21 抛 |
| 5 | `test_chat_request_session_id_optional` | 不传 session_id 默认 None；传字符串通过 |
| 6 | `test_citation_index_must_be_positive` | `index=0` 抛；`index=1` 通过 |
| 7 | `test_chat_response_serializes_citations` | 嵌套 Citation 能正确 model_dump |

### 5.2 `tests/test_chat_prompt.py`（默认跑）

用 `RetrievalResult` 直接构造（无需真 retriever）：

| # | 名称 | 断言 |
|---|---|---|
| 1 | `test_format_context_empty_returns_empty_string` | retrieved=[] → `""` |
| 2 | `test_format_context_numbers_from_one` | 3 条返回字符串含 `[1]` `[2]` `[3]` |
| 3 | `test_format_context_includes_source_metadata` | 字符串含 `metadata["source"]` 值 |
| 4 | `test_format_context_truncates_by_max_chars` | 5 条 + max_chars 小 → 只拼前 N 条；累计字符数 ≤ max_chars + len(单条) |
| 5 | `test_format_context_keeps_at_least_one_chunk` | max_chars 小于第一条 → 仍返回第一条整体（不截中间）|
| 6 | `test_build_messages_with_retrieved_uses_with_context_prompt` | system 含 "参考资料"；user 是 query 原文 |
| 7 | `test_build_messages_no_retrieved_uses_no_context_prompt` | retrieved=[] → system 含 "未检索到相关参考资料" |
| 8 | `test_build_messages_returns_two_messages` | len == 2，role 顺序 system→user |

### 5.3 `tests/test_chat_service.py`（默认跑）

```python
class FakeRetriever:
    def __init__(self, results: list[RetrievalResult]) -> None: self._r = results
    def retrieve(self, query: str, k: int) -> list[RetrievalResult]:
        return self._r[:k]

class FakeLLMClient(LLMClient):
    def __init__(self, content: str = "fake answer") -> None:
        self._content = content
        self.last_messages: list[ChatMessage] | None = None
        self.last_temperature: float | None = None
    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        self.last_messages = messages
        self.last_temperature = temperature
        return ChatResult(content=self._content, model="fake-model",
                          usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
```

| # | 名称 | 断言 |
|---|---|---|
| 1 | `test_answer_uses_top_k_default_when_k_none` | k=None → retriever 收到 service 注入的 top_k |
| 2 | `test_answer_overrides_top_k_when_k_explicit` | 传 k=3 → retriever 收到 3 |
| 3 | `test_answer_passes_temperature_to_llm` | LLM.chat 收到 service.temperature |
| 4 | `test_answer_returns_citations_for_each_retrieved` | 3 条 retrieved → 3 条 citation；index 1/2/3 |
| 5 | `test_answer_snippet_truncates_to_100_chars` | chunk text 200 字 → snippet 长度 ≤ 100 |
| 6 | `test_answer_handles_empty_retrieval` | retrieved=[] → 仍调 LLM；citations=[]；retrieved_count=0 |
| 7 | `test_answer_propagates_llm_exceptions` | FakeLLM 抛 APIConnectionError → service 透传 |
| 8 | `test_answer_runs_retriever_in_thread` | 用 threading.current_thread 验证 retrieve 不在主线程跑（asyncio.to_thread 行为）|

### 5.4 `tests/test_chat_route.py`（默认跑，FastAPI TestClient）

```python
def make_app_with_service(service: ChatService | None) -> FastAPI:
    app = FastAPI()
    app.state.chat_service = service
    app.include_router(chat.router, prefix="/api")
    return app
```

| # | 名称 | 断言 |
|---|---|---|
| 1 | `test_chat_503_when_service_none` | state.chat_service=None → 503 + detail.code="rag_not_configured" |
| 2 | `test_chat_200_happy_path` | 注入 FakeChatService → 200；body 含 answer / citations / usage |
| 3 | `test_chat_422_when_query_missing` | 空 body → 422 |
| 4 | `test_chat_422_when_query_too_long` | query 长度 1001 → 422 |
| 5 | `test_chat_422_when_k_out_of_range` | k=0 / k=21 → 422 |
| 6 | `test_chat_429_on_llm_rate_limit` | FakeService 抛 RateLimitError → 429 + code="llm_rate_limited" |
| 7 | `test_chat_502_on_llm_connection_error` | 抛 APIConnectionError → 502 + code="llm_unreachable" |

### 5.5 `tests/test_chat_live.py`（守门，默认跳）

```python
import os, pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_RAG_CHAT"),
    reason="set RUN_LIVE_RAG_CHAT=1 to run end-to-end DeepSeek + BGE + Chroma chat",
)
```

| # | 名称 | 断言 |
|---|---|---|
| 1 | `test_live_chat_with_indexed_sample` | 前置：跑过 `scripts/index_papers.py --paths data/papers/sample.txt`；构造真链路调 `/api/chat` 问 "氮素淋失受什么影响"；返回 answer 非空、citations 非空、retrieved_count > 0 |

### 5.6 验证命令

```bash
cd backend

# 1. 单元测试（默认）
uv run pytest tests/test_chat_schema.py tests/test_chat_prompt.py \
              tests/test_chat_service.py tests/test_chat_route.py -v

# 2. 全套回归（应在 < 10s 内通过）
uv run pytest

# 3. 启用 RAG + 跑离线索引（首次）
uv sync --extra rag
uv run python scripts/index_papers.py \
    --paths ../data/papers/sample.txt \
    --persist-dir var/chroma --collection papers --repo-root ..

# 4. 启动后端（需要 .env 设 RAG_ENABLED=true 与 RAG_CHROMA_DIR=./var/chroma）
uv run uvicorn src.main:app --reload

# 5. 手动 smoke
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  --noproxy 127.0.0.1 \
  -d '{"query":"氮素淋失主要受什么因素影响？","k":3}'

# 6. live 集成测
RUN_LIVE_RAG_CHAT=1 uv run pytest tests/test_chat_live.py -v
```

注：`--noproxy 127.0.0.1` 是樱花猫 VPN 适配（项目环境特定）。

## 6 与 M1.3.2 / M2 的衔接

### 与 M1.3.2 前端 chat UI

| M1.3.2 需要 | 本迭代提供 |
|---|---|
| HTTP 端点 | `POST /api/chat` |
| 请求体 schema | `{query: string, k?: number, session_id?: string}` |
| 响应体 schema | `{answer, citations[], usage, retrieved_count, model}` |
| 错误状态机 | 422 / 429 / 502 / 503 + `detail.code` 稳定字符串 |
| CORS | M0 walking-skeleton 已配置，本迭代不动 |

**契约一句话**：M1.3.2 直接 fetch `/api/chat`，按 `detail.code` 区分错误展示文案。

### 与 M2 ReAct Agent

| M2 需要替换的 | 本迭代如何留出空间 |
|---|---|
| 多轮历史 | `ChatRequest.session_id` 字段已预留 |
| ReAct 循环 | `agent/` 模块已开；`ChatService.answer` 是当前的"最简 agent"，M2 可演化为 `ChatService.run_react(...)` 或新增 `AgentService` 并存 |
| 流式 | 路由签名换成 `StreamingResponse`；service 层 `answer` 升级 `answer_stream` |
| Tool calling | LLMClient.chat 接口需扩展（M1.1 §1 显式留 M2）|

**反向约束**：M1.3.1 不允许引入"为 M2 准备"的抽象（如 BaseAgent / Tool 接口）。
当前 ChatService 直接用具体类型，M2 重构时再抽。

## 7 度量基线

| 指标 | 计划值 | 实际值 |
|---|---|---|
| 后端代码新增行数（非测试） | ≤ 250 | 约 317 行（超计划；包含 route/schema/service/prompt/export/lifespan/config） |
| 新增单测数 | ≥ 30（schema 7 + prompt 8 + service 8 + route 7）| 32 个默认测试 |
| Live 测数 | ≥ 1 | 1 个 `RUN_LIVE_RAG_CHAT=1` 守门测试 |
| 新增依赖 | 0（openai / fastapi / pydantic / chromadb / sentence-transformers 已有）| 0 |
| pytest 默认全套耗时 | < 10s | `84 passed, 20 skipped in 1.75s` |
| 默认启动时间（RAG_ENABLED=false） | < 1s | 未单独计时；默认测试路径不加载 RAG |
| 启用 RAG 后首次 chat 冷启动 | < 10s（含 BGE 权重加载） | 未实测；live smoke 默认跳过 |

## 8 风险

1. **`Citation` 跨模块依赖循环风险**：spec §4.3 已定方案 A（在 agent 定义，api re-export）。
   缓解：实现时严格按方向 `api → agent → llm/rag/storage`，加 import lint（手动检查）。
2. **lifespan fail-soft 可能掩盖配置错误**：用户写错 `RAG_CHROMA_DIR` 路径只看到 warning，
   不知道 chat 为什么 503。
   缓解：503 detail.message 写明"检查 RAG_ENABLED / RAG_CHROMA_DIR / 索引是否生成"；
   lifespan 的 warning log 用 `logger.warning(... exc_info=True)` 打全栈。
3. **Citation snippet 截 100 字可能截到半个字 / 半个 emoji**：中文严格按 char 数切，
   不会出现半字符；emoji 极少出现在论文。
   缓解：本迭代不补复杂 grapheme cluster 处理；前端在 `…` 末尾兜底。
4. **未启用 RAG 时模型直答可能与"农业助手"人设不符**：retrieved=[] 时仍调 LLM，
   提示模型"未引用本知识库"，但 LLM 仍可能给出错误信息。
   缓解：spec §3.9 已加显式提示；M1.4 评测会单独测无召回回答质量。
5. **DeepSeek API 失败模式未观察过**：错误翻译表（§3.10）是经验估计，可能漏边角异常。
   缓解：实测后回填；遗漏的异常 fallback 到 500 + log，不让请求挂起。
6. **`asyncio.to_thread` 默认线程池可能被 BGE 加载拖死**：单线程池，多并发请求时
   首个 retrieve 触发权重加载会阻塞后续。
   缓解：M1 单用户场景不构成问题；M2 高并发时再评估专用 thread executor。
7. **`backend/.env.example` 是否存在未确认**：实现期先 ls 检查，不存在则改 README 写明。
8. **session_id 字段预留可能误导**：前端可能以为传了就有多轮记忆。
   缓解：spec / API doc / FastAPI Field description 写明"M1 阶段仅校验类型，不消费"。

## 9 参考

- M1.1 spec：[`../2026-05-04-m1-1-llm-client/spec.md`](../2026-05-04-m1-1-llm-client/spec.md)
- M1.2.3 spec：[`../2026-05-05-m1-2-3-ingest-index-retriever/spec.md`](../2026-05-05-m1-2-3-ingest-index-retriever/spec.md)
- v0.1.0-m1.2 release：[`../../releases/v0.1.0-m1.2.md`](../../releases/v0.1.0-m1.2.md)
- ARCHITECTURE.md：ADR-002（用户体系延后）/ ADR-003（DeepSeek）/ ADR-005（Agent 自研）
- FastAPI lifespan / TestClient 文档：<https://fastapi.tiangolo.com/advanced/events/>
- DeepSeek API 文档：<https://api-docs.deepseek.com/>
