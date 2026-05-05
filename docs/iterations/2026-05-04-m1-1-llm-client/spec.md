# 说明文档 — M1.1 LLM 客户端骨架

> **目标读者**：未来翻阅本仓库的研究者、本人在毕设论文写作阶段、
> 后续接续 M1.2~M1.4 的实现者。本文档是 **设计阶段** 产物，
> 在落地实施后会回填具体 commit 与度量值，不重写设计判断。

| 元信息 | 值 |
|---|---|
| 迭代名 | m1-1-llm-client |
| 日期 | 2026-05-04 |
| 涉及 commit | `838f59b` `df61d29` `6c9b2d5` `5da6a3d`（fix）|
| 文档版本 | v1.2（含复审修订） |
| 父里程碑 | M1（基础对话闭环） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

---

## 1 本次迭代的目标

为 M1.2~M1.4 的所有 "调用 LLM" 路径建立 **单一抽象点**。M1 的核心叙事是
"用户提问 → RAG 检索 → LLM 生成带引用回答"；其中 LLM 是最稳定的依赖
（API 协议成熟、错误模型清晰），先把它的 wrapper 钉死，可以让后续
RAG（M1.2）与 chat 路由（M1.3）在已知契约上并行展开。

具体交付：

1. `backend/src/llm/base.py` — `LLMClient` 抽象基类 + 统一数据模型
2. `backend/src/llm/deepseek.py` — 基于 OpenAI 兼容协议的 DeepSeek 实现
3. `backend/src/llm/__init__.py` — 公开导出
4. `backend/src/main.py` — lifespan 启动钩子加 `DEEPSEEK_API_KEY` 非空校验（顺手收 M0 遗留 #5）
5. `backend/tests/test_llm_*.py` — 抽象契约测试 + DeepSeek client 单测（mock）
6. 依赖：新增 `openai>=1.50,<2.0`

**不做**（保持 M1.1 边界）：

- 流式输出（M2）
- tool-calling（M2）
- 重试 / 熔断（M2，需先观察真实失败模式）
- 多模型动态切换（不在路标）
- 对真实 DeepSeek 的强制集成测试（默认跳过，环境变量开关）

## 2 关键设计决策

### 2.1 `chat()` 只暴露 async，不提供 sync 版本

FastAPI 路由是 async-first；DeepSeek 调用是 I/O-bound；同时维护
sync 与 async 两套接口会双倍维护成本，且 sync 版本最终会被吞进
`asyncio.run`。

**结论**：`async def chat(...)` 是唯一对外接口。脚本场景手动包
`asyncio.run()`。

### 2.2 选 `openai` 官方 SDK 而非裸 `httpx`

DeepSeek 官方文档明确推荐用 OpenAI SDK + 自定义 `base_url`。
`openai>=1.0` 提供：

- `AsyncOpenAI` 异步客户端
- 完整错误层级（`APIError` / `APIConnectionError` /
  `RateLimitError` / `AuthenticationError`）
- 超时与重试基础设施

自己写 httpx wrapper 会重新实现一遍，且偏离社区共识。

**与 ADR-005 的一致性**：ADR-005 写"所有调用经 LLMClient 抽象"，
没禁止 wrapper 内部用 openai SDK。在 `llm/` 目录内部 import openai
是被允许的；在 `agent/` / `rag/` / `api/` 等业务层 import openai
仍然禁止。这条纪律由 §3.2 的目录隔离与未来 lint 规则共同维护。

### 2.3 数据模型用 pydantic 而非 dataclass

项目其他地方（`Settings`、未来 API request/response）都用 pydantic。
统一一种数据模型减少认知负担，也方便未来直接把 `ChatResult`
作为 API 响应字段嵌入。

```python
class ChatUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class ChatResult(BaseModel):
    content: str
    model: str
    usage: ChatUsage
```

`finish_reason` 暂不返回 — M1.1 只关心 "成功 / 抛错" 二态；
M2 上 tool-calling 时再加。

### 2.4 错误层级最小化：透传 openai 异常

`LLMClient.chat()` **不** 自造异常层。openai SDK 的
`APIError` / `APIConnectionError` / `AuthenticationError` 已足够。
约定：调用方应捕获 `openai.APIError` 基类。

未来需要"模型无关错误"（比如切到 Claude 时统一异常类型）时，
再在 `llm/exceptions.py` 引入 — 当前没有需求，避免过早抽象。

### 2.5 启动期校验 DeepSeek key（收 M0 遗留 #5）

`main.py` 的 `lifespan` 启动段：

```python
if not settings.deepseek_api_key:
    raise RuntimeError(
        "DEEPSEEK_API_KEY 未配置；请检查 backend/.env"
    )
```

fail-fast，避免延迟到第一次 chat 调用才暴露。

测试与 CI 通过 `tests/conftest.py` 在顶层注入哨兵值绕过；
具体实现见 §4.4，要点：

- 用 `os.environ[...] = ...` 而不是 fixture（fixture 在 collection
  之后才执行，那时 `Settings()` 已在 `src.config` 导入期实例化，来不及）
- 整个覆盖动作由 `RUN_LIVE_LLM` 环境变量门控：默认（mocked）模式强制
  哨兵值；`RUN_LIVE_LLM=1` 时让真实 key 与代理透传，便于 live smoke

### 2.6 `LLMClient` 是 ABC 而非 Protocol

**Protocol** 适合 duck-typed、第三方对象适配的场景；
**ABC** 适合"我们自己定义所有实现"的场景。本项目是后者
（DeepSeek、未来 OpenAI / Claude 都由我们写）。ABC 还能强制
签名一致与未实现方法的早期发现。

## 3 模块结构

```
backend/src/llm/
├── __init__.py          # 公开导出 LLMClient / DeepSeekClient / ChatMessage / ChatResult / ChatUsage
├── base.py              # ABC + pydantic 数据模型
└── deepseek.py          # DeepSeekClient(LLMClient)

backend/tests/
├── conftest.py          # 注入测试 DEEPSEEK_API_KEY（新增）
├── test_llm_base.py     # 契约测试（FakeLLMClient 验证 ABC 强制约束）
└── test_llm_deepseek.py # mock AsyncOpenAI 验证参数与返回映射
```

## 4 重点代码导读（计划）

### 4.1 `llm/base.py`

```python
from abc import ABC, abstractmethod
from typing import Literal
from pydantic import BaseModel


class ChatUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatResult(BaseModel):
    content: str
    model: str
    usage: ChatUsage


class LLMClient(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult: ...
```

**默认参数选择**：

- `temperature=0.3` — 学术 RAG 场景偏好一致性，不要 0.0（DeepSeek 在 0.0
  下偶现退化），也不要 0.7（创意写作风）
- `max_tokens=None` — 服务端默认接管，客户端不硬编码上限；
  长文摘要场景由调用方按需指定

### 4.2 `llm/deepseek.py`

```python
from openai import AsyncOpenAI

from src.llm.base import ChatMessage, ChatResult, ChatUsage, LLMClient


class DeepSeekClient(LLMClient):
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[m.model_dump() for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        return ChatResult(
            content=choice.message.content or "",
            model=response.model,
            usage=ChatUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            ),
        )
```

构造器显式接收三参数（不直接 `from src.config import settings`），
便于：

- 测试时构造 `DeepSeekClient(api_key="x", base_url="...", model="...")`
- 未来同时跑多个实例（不同模型 / 不同 endpoint）

`content or ""` 是因为 OpenAI SDK 在 tool-calling 场景下 `content`
可能为 `None`；M1.1 不走 tool-calling，但保留兜底以防 DeepSeek
返回空 content（如内容审核拦截）。

### 4.3 `main.py` lifespan 校验

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.deepseek_api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 未配置；请检查 backend/.env"
        )
    logger.info(
        "Backend starting | env={} | model={} | cors_origins={}",
        settings.app_env,
        settings.deepseek_model,
        settings.cors_origin_list,
    )
    yield
    logger.info("Backend shutting down")
```

注意 logger 中加了 `model=`，便于后续运行时日志能直接看到实际生效的模型名。

### 4.4 `tests/conftest.py`

```python
import os

# 默认（mocked）模式下强制测试隔离：把 DEEPSEEK_API_KEY 设为哨兵值，
# 并清空 WSL2 樱花猫客户端可能注入的非法 *_PROXY 值（含换行，会让
# openai SDK 构造时经 httpx 报 InvalidURL，见 walking-skeleton spec §7.1）。
#
# 但当 RUN_LIVE_LLM=1 时，调用方在用真实 DeepSeek 跑 smoke：必须保留
# 真实 key 与真实代理设置，否则 live 测试拿不到 key、连不上 api。
if not os.environ.get("RUN_LIVE_LLM"):
    os.environ["DEEPSEEK_API_KEY"] = "test-key-not-real"
    for _var in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    ):
        os.environ.pop(_var, None)
```

为什么写在 `conftest.py` 顶层而不是 fixture：`Settings()` 在
`src.config` 模块导入期就读取 env，pytest 的 fixture 在 collection
完成后才执行，那时 settings 已经实例化、改 env 来不及。

为什么用 `RUN_LIVE_LLM` 门控而不是无条件覆盖：spec §5 规划了
`RUN_LIVE_LLM=1 DEEPSEEK_API_KEY=<real>` 的 live smoke 路径；
若 conftest 无条件改写 `DEEPSEEK_API_KEY`，live 测试会拿到哨兵 key
直接 401，整个设计先天失效。代理同理 — live 模式下宿主代理设置
是合法的真实需求。

## 5 验证方法

```bash
cd backend

# 1. 装新依赖
uv add 'openai>=1.50,<2.0'

# 2. 跑全套单测（应在 < 2s 内通过；无网络）
uv run pytest

# 3. 启动校验：不配 key 时应失败
unset DEEPSEEK_API_KEY
uv run uvicorn src.main:app --port 8000
# 期望：RuntimeError: DEEPSEEK_API_KEY 未配置

# 4. 启动校验：配上后正常启动
DEEPSEEK_API_KEY=test uv run uvicorn src.main:app --port 8000

# 5.（可选）实调 DeepSeek 的 smoke：默认跳过
RUN_LIVE_LLM=1 DEEPSEEK_API_KEY=<real-key> uv run pytest tests/test_llm_live.py
```

`tests/test_llm_live.py` 用 `@pytest.mark.skipif(not os.getenv("RUN_LIVE_LLM"))`
默认跳过，避免 CI 真实计费。

结构化证据矩阵详见同目录 `review.md`（push 前定稿）。

## 6 与 M1.2 / M1.3 的衔接

| M1.x 需要的能力 | M1.1 提供的挂载点 |
|---|---|
| RAG 检索（M1.2） | 不依赖本迭代；`Embedder` 抽象与 `LLMClient` 平行 |
| `POST /api/chat`（M1.3）| 路由内 `from src.llm import LLMClient, ChatMessage`，构造 `DeepSeekClient(*settings)`，组装 system/user 消息后调 `chat()` |
| 启动期初始化客户端（M2 之后）| 当 LLM 客户端持有连接池等重资源时，可在 lifespan 里 `app.state.llm = DeepSeekClient(...)`；M1.1 不上，调用方按需构造即可 |

## 7 度量基线

| 指标 | 计划值 | 实际值 |
|---|---|---|
| 后端代码新增行数（非测试） | ≤ 100 | 76 行（base 32 + deepseek 36 + `__init__` 8） |
| 新增单测数 | ≥ 3 | 6（base 3 + deepseek 3） |
| 新增 Python 直接依赖 | 1（`openai`） | 2（`openai>=1.50,<2.0` + `pytest-asyncio>=0.24`） |
| 新增 Python 间接依赖 | TBD | 4（`distro` / `jiter` / `sniffio` / `tqdm`） |
| pytest 全套耗时 | < 2s | 1.25s（11 tests，含 pre-m1-prep 新增） |
| Settings 校验失败时启动耗时 | < 1s（fail-fast） | < 0.3s（lifespan 直接 raise） |

## 8 偏离与遗留

### 8.1 与原 spec 的偏离

| 原计划 | 实际 | 理由 |
|---|---|---|
| 直接依赖只加 `openai` | 加了 `openai` + `pytest-asyncio` | `@pytest.mark.asyncio` 必需。spec 起草时未列入，实施时补 |
| pytest 配置不动 | 加 `asyncio_mode = "strict"` | pytest-asyncio 默认模式弃用警告，显式声明避免 |
| `conftest.py` 仅注 DEEPSEEK_API_KEY | 同时清空 8 个代理环境变量（HTTP_PROXY 等）| WSL2 宿主代理含换行非法值，openai SDK 构造时经 httpx 读 env 直接 `InvalidURL`（walking-skeleton spec §7.1 已记录的坑）。测试不应触网，统一清掉 |
| `conftest.py` 用 `os.environ.setdefault` | 改为 `if not RUN_LIVE_LLM: os.environ[...] = ...` 门控覆盖 | 默认 mocked 模式强制哨兵以避免宿主 env 污染；`RUN_LIVE_LLM=1` 时让真实 key 与代理透传（修复了一次过渡期的 bug：曾改成无条件直接赋值，会堵死 spec §5 规划的 live smoke 路径，已纠正）|
| `DeepSeekClient.chat()` 总传 `max_tokens` 给 SDK | `max_tokens is None` 时不入 kwargs | 请求体语义更精确；新增对应回归测 `test_chat_omits_max_tokens_when_not_provided` |

### 8.2 M0 遗留项处置

| 项 | 处理 |
|---|---|
| #1 `__init__.py` 读 pyproject | **pre-m1-prep 中收掉**（2026-05-04-pre-m1-prep）|
| #2 Python 版本三处冗余 | 不收，跨基础设施改动 |
| #3 PR 模板 `pnpm test` 缺脚本 | 不收，等 M1.4 引入前端测试再处理 |
| #4 前端 fetch 抽 lib/api.ts | 不收，等 M1.4 |
| #5 DeepSeek key 启动期校验 | **本迭代收掉** — 见 §2.5 |
| #6 api/__init__.py 空文件 | 不触发（本迭代不动 api/），M1.3 chat 路由时自然解决 |

## 9 已知风险

1. **openai SDK breaking change**：锁版本 `>=1.50,<2.0`。
   升级 openai 主版本时需重新跑契约测试。
2. **DeepSeek 字段缺失**：`logprobs`、`tool_calls` 等可选字段
   在某些场景下为 `None`；本迭代 ChatResult 只取
   `content` / `model` / `usage`，不依赖可选字段。
3. **空响应**：内容审核拦截时 `content` 可能为空字符串。
   本迭代用 `content or ""` 兜底，不抛错；上层（M1.3）决定
   是否在空回答上加用户提示。
4. **Settings 实例化时机**：fail-fast 校验目前放 lifespan 里，
   `Settings()` 本身仍在 `config.py` 导入期执行。如果未来希望
   `Settings()` 失败本身（如 `.env` 格式错）也 fail-fast，
   需要把校验上移到 import 期 — 当前不做。
5. **测试环境对宿主 env 的依赖**：本轮 conftest 在默认模式下清空
   `DEEPSEEK_API_KEY` 与 `*_PROXY`，仅在 `RUN_LIVE_LLM=1` 时透传。
   依赖是：调用方必须显式声明 live 意图。若未来出现"既要 live 又要
   mocked 子集"的混合需求，需要把门控收窄到具体测试 marker 而不是
   全局 env。当前 trade-off 可接受。

## 10 参考

- DeepSeek API docs：<https://api-docs.deepseek.com/>
- openai-python SDK：<https://github.com/openai/openai-python>
- ADR-003（DeepSeek 选型）/ ADR-005（自研 Agent，禁止业务层 import openai）：
  [`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md)
- 父级路标：M1 拆分为 4 个 sub-iteration（M1.1 LLM / M1.2 RAG 索引 /
  M1.3 chat 接口 / M1.4 前端 UI）
