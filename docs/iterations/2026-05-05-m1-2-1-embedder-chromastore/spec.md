# 说明文档 — M1.2.1 Embedder 抽象 + ChromaStore 薄封装

> 本文档是 **设计阶段** 产物（v1.0），落地后回填实际 commit、统计与偏离。
> 后续接续 M1.2.2（切分器）/ M1.2.3（索引脚本 + retriever pipeline）。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代名 | m1-2-1-embedder-chromastore |
| 日期 | 2026-05-05 |
| 涉及 commit | 待落地（push 前回填） |
| 文档版本 | v1.0（设计阶段） |
| 父里程碑 | M1（基础对话闭环） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 范围

### 2.1 在做

为 M1.2.2~M1.2.3 的所有 "embed + 向量入库 / 检索" 路径建立 **两个抽象点**：

1. **`rag/base.py` + `rag/bge.py`**：`Embedder` ABC + `BGEEmbedder` 实现
   - 仅暴露最小契约：`embed_documents(texts) -> list[list[float]]`、
     `embed_query(text) -> list[float]`、`dim` 属性
   - 模型 lazy-load：构造期不下载、不加载；首次调用 `embed_*` 才真正
     初始化 `sentence_transformers.SentenceTransformer`
   - 不暴露 batch_size / device / normalize 之类调优参数到 ABC，
     全在实现类构造期决定
2. **`storage/chroma_store.py`**：`ChromaStore` 薄封装
   - 仅暴露最小契约：构造（指定 `persist_dir` + `collection_name`）、
     `add(ids, documents, embeddings, metadatas)`、`query(embedding, k)`、
     `count() -> int`、`persist_dir` 属性
   - 不直接依赖 `Embedder`；caller 负责先 embed 再 add（解耦层级）
   - 持久化模式（Chroma `PersistentClient`），不跑独立服务

### 2.2 不在做（明确边界）

- ❌ 文档切分器（中文论文专用切分） → M1.2.2
- ❌ 索引脚本（把 PDF / Markdown 灌进 ChromaStore） → M1.2.3
- ❌ Retriever pipeline（embed query + chroma query + rerank） → M1.2.3
- ❌ 引用抽取 → M1.2.3
- ❌ 接 chat 路由 → M1.3
- ❌ 重排模型（reranker）→ M1.4 之后再评估
- ❌ Embedder 多实现（OpenAI / HuggingFace API）→ 替换需要时再做

### 2.3 计划变更清单

| 项 | 文件 | 内容要点 |
|---|---|---|
| `Embedder` ABC | `backend/src/rag/base.py` 新增 | `class Embedder(ABC)` + 三个 `@abstractmethod`：`embed_documents` / `embed_query` / `dim` |
| `BGEEmbedder` 实现 | `backend/src/rag/bge.py` 新增 | 包 `sentence_transformers.SentenceTransformer("BAAI/bge-large-zh-v1.5")`；lazy-load；normalize_embeddings=True（cosine 友好） |
| `rag/__init__.py` 公开导出 | `backend/src/rag/__init__.py` | `__all__ = ["Embedder", "BGEEmbedder"]` |
| `ChromaStore` 薄封装 | `backend/src/storage/chroma_store.py` 新增 | 包 `chromadb.PersistentClient`；构造期 `get_or_create_collection`；四个公开方法 + 一个属性 |
| `storage/__init__.py` 公开导出 | `backend/src/storage/__init__.py` | `__all__ = ["ChromaStore"]` |
| 契约测：Embedder | `backend/tests/test_embedder.py` 新增 | ABC 不可实例化；FakeEmbedder 验证 dim 一致；BGEEmbedder lazy-load（构造不触发下载，mock SentenceTransformer 验证调用一次） |
| 契约测：ChromaStore | `backend/tests/test_chroma_store.py` 新增 | 临时目录跑端到端 add → query → count；持久化路径正确；空集合 query 不抛 |
| 可选 RAG 依赖 | `backend/pyproject.toml` + `uv.lock` | 新增 `rag` extra：`sentence-transformers>=3.0,<4.0` + `chromadb>=0.5,<0.6`；默认 `uv sync` 不安装 |

## 3 关键判断

### 3.1 Embedder 与 ChromaStore 分层放在 rag/ 与 storage/

**不是** `rag/store.py` 或 `rag/chroma.py`。理由：

- `storage/README.md` 已明确"Chroma：向量库的初始化与封装"是 storage/ 的职责
- `rag/` 只承担 retrieval-side 的策略（切分、embed、检索 / 重排 / 引用），
  存储原语属于下一层
- 现在不钉死，M1.2.3 写 retriever pipeline 时会自然把 chromadb 的 import
  漏到 `rag/`，分层就开始混

caller（M1.2.3 的 retriever 或 indexer）显式 `from src.rag import BGEEmbedder` +
`from src.storage import ChromaStore`，由调用方负责"先 embed 后 add / query"。
这种 *弱关联* 让两个模块各自独立可测。

### 3.2 模型 lazy-load 而不是构造期 load

**问题**：`sentence_transformers.SentenceTransformer("BAAI/bge-large-zh-v1.5")`
首次实例化会下载 ~1.3 GB 权重并加载到内存。如果在 `BGEEmbedder.__init__` 里
直接 load：

- 任何 `from src.rag import BGEEmbedder` 的测试都会触网 / 占内存
- pytest collection 期间就开始下载，整个测试体系崩
- M1.3 chat 路由 import 期挂个 `BGEEmbedder` 实例就会卡启动

**方案**：构造期只存模型 ID 与 device hint，第一次调 `embed_documents` /
`embed_query` 时才 `_ensure_loaded()`。代价：第一次调用慢 (~5s 加载)，
之后正常。trade-off 可接受 — 索引脚本是离线长任务，启动延迟无所谓。

### 3.3 ABC 而不是 Protocol（与 LLMClient 同选型）

理由跟 M1.1 LLMClient 一样：runtime `TypeError` 兜底 + 单继承点直观；
本项目不需要 duck-typed 适配第三方对象。

### 3.3.1 `rag/` 文件命名对齐 `llm/`：拆成 `base.py` + `bge.py`

不再把 ABC 和首个实现塞进单个 `rag/embedder.py`。

理由：

- `backend/src/llm/{base.py,deepseek.py}` 已经是现成先例；跨模块同形更利于接续
- 第二个实现（如 `OpenAIEmbedder` / `E5Embedder`）一进来就能按既有形状落位，
  不需要中途再做一次“拆文件”噪音重构
- `rag/__init__.py` 仍负责扁平导出，对调用方 import 体验无损

### 3.4 `embed_documents` / `embed_query` 拆两个方法

BGE 系列 query 端可以加 instruction prefix（"为这个句子生成表示用于检索相关
文章："）来提升检索质量。两个方法分开就是为这个差异留口子，即便 M1.2.1 的
首版实现里两边都不加 prefix（直接调底层 `model.encode`），契约里体现差异
后面无痛升级。

### 3.5 ChromaStore 不持有 Embedder 引用

**反模式**：`ChromaStore(embedder=BGEEmbedder())`，让 store 自己 embed。

**问题**：

- 索引脚本想批量 embed → 攒 batch → 一次 add，store 内部 embed 就攒不了 batch
- 测试要 mock 时，要么 mock embedder 要么 mock store，但二者已经耦合
- 替换 embedder 实现时 store 跟着动

**方案**：`ChromaStore.add(ids, documents, embeddings, metadatas)` 收的是
**已 embed 好的向量**。caller 决定怎么 batch、怎么并行。

### 3.6 chromadb 持久化模式而不是 ephemeral

`chromadb.PersistentClient(path=settings.chroma_persist_dir)`，
不是 `chromadb.Client()`（in-memory）。理由：

- ADR-004 已定 "文件持久化模式（不跑独立服务）"
- 索引一次（M1.2.3 离线脚本）→ 多次查询（M1.3 在线 chat），
  in-memory 模式每次启动都得重建索引，~分钟级开销不可接受
- 测试用临时目录 + `tmp_path` fixture，不污染开发数据

### 3.7 `dim` 属性放 ABC 而不是返回 ChatResult-like 包装对象

`embed_documents` 直接返回 `list[list[float]]`，不包 pydantic 模型。
理由：

- 向量本身没有元数据需要 carry（不像 ChatResult 有 model / usage）
- pydantic 校验 1000 个 1024 维 float 列表会显著拖慢，无收益
- caller 拿到 `list[list[float]]` 直接喂 ChromaStore.add，零转换

`dim` 单独放 property，让 caller 提前知道维度（建索引时可用于 sanity check）。
这里额外加一条契约约束：**`dim` 必须在不触发真实模型 load / 首次 embed 的前提下可用**。
也就是说，实现方要么给出常量，要么从静态配置解析；不能把“先 `embed_query("x")`
再看长度”当成 ABC 的满足方式。

## 4 实现细节

### 4.1 `rag/base.py` + `rag/bge.py` 草图

```python
# backend/src/rag/base.py
from abc import ABC, abstractmethod


class Embedder(ABC):
    @property
    @abstractmethod
    def dim(self) -> int:
        """Return embedding dimension without requiring model load or probe embed."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...
```

```python
# backend/src/rag/bge.py
from src.rag.base import Embedder


class BGEEmbedder(Embedder):
    _DIM = 1024  # bge-large-zh-v1.5 固定输出维度

    def __init__(
        self,
        model_id: str = "BAAI/bge-large-zh-v1.5",
        device: str = "cpu",
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._model = None  # lazy

    @property
    def dim(self) -> int:
        return self._DIM

    def _ensure_loaded(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_id, device=self._device)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_loaded()
        vectors = model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        model = self._ensure_loaded()
        vector = model.encode([text], normalize_embeddings=True)[0]
        return vector.tolist()
```

要点：
- `from sentence_transformers import ...` 在 `_ensure_loaded` 里做，
  让 `import src.rag` 不触发 sentence_transformers 的导入
  （后者会拉 torch，~秒级 import 开销）
- `normalize_embeddings=True` 让向量 L2-normalize，cosine 距离 ≡ 内积，
  Chroma 默认 distance function 是 L2，但 normalize 后 L2 与 cosine
  在排序上等价，简化 M1.2.3 的判断

### 4.2 `storage/chroma_store.py` 草图

```python
from pathlib import Path
from typing import Any

import chromadb


class ChromaStore:
    def __init__(self, persist_dir: str | Path, collection_name: str) -> None:
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
        )

    @property
    def persist_dir(self) -> Path:
        return self._persist_dir

    def add(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        self._collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(
        self,
        embedding: list[float],
        k: int = 5,
    ) -> dict[str, Any]:
        return self._collection.query(
            query_embeddings=[embedding],
            n_results=k,
        )

    def count(self) -> int:
        return self._collection.count()
```

要点：
- `mkdir(parents=True, exist_ok=True)` 让构造期容错；persist_dir 不存在
  时主动创建，避免 caller 先做这一步
- `get_or_create_collection` 而不是 `create_collection`，重启时复用
- `query` 返回 chromadb 原生 dict（`{"ids": [[...]], "distances": [[...]],
  "documents": [[...]], "metadatas": [[...]]}`），不二次包装；M1.2.3 的
  retriever 决定要不要包成 pydantic
- `metadatas` 可选，None 时不传给 chromadb

### 4.3 `__init__.py` 公开导出

```python
# backend/src/rag/__init__.py
from src.rag.base import Embedder
from src.rag.bge import BGEEmbedder

__all__ = ["Embedder", "BGEEmbedder"]
```

```python
# backend/src/storage/__init__.py
from src.storage.chroma_store import ChromaStore

__all__ = ["ChromaStore"]
```

### 4.4 测试策略

**`test_embedder.py`**（mocked，默认跑）：

1. `test_embedder_abc_cannot_be_instantiated` — `Embedder()` 抛 `TypeError`
2. `test_bge_embedder_constructor_does_not_load_model` — 构造完 `_model is None`
3. `test_bge_embedder_lazy_loads_on_first_embed`（用 `monkeypatch` 替
   `sentence_transformers.SentenceTransformer` 为 mock，验证调用一次）
4. `test_bge_embedder_dim_is_1024`
5. `test_fake_embedder_round_trip` — 自定义 `FakeEmbedder` 实现 ABC，
   embed 后维度匹配（验证契约可被任意实现满足）

**`test_chroma_store.py`**（用 `tmp_path` fixture，端到端跑真实 chromadb）：

1. `test_add_then_count_reflects_inserted_documents`
2. `test_query_returns_nearest_by_embedding`（手工塞 3 个 4 维向量，
   query 向量与第 2 个最近，验证返回顺序）
3. `test_query_on_empty_collection_returns_empty_lists`
4. `test_persist_dir_is_created_when_missing`
5. `test_count_zero_on_fresh_collection`

chromadb 本身轻量、纯 Python（除了 numpy），跑临时目录端到端测耗时
亚秒级，没必要 mock。

**`test_embedder_live.py`**（实调，默认跳过）：

- 使用 `@pytest.mark.skipif(not os.getenv("RUN_LIVE_EMBED"), ...)` 守门
- 最小断言只覆盖真实 `BGEEmbedder().embed_query(...)` 能返回 1024 维非空向量
- 不测排序质量，不测语义相似性；那是 M1.2.3 `test_rag_live.py` 的职责

**live smoke 命令**：

```bash
RUN_LIVE_EMBED=1 uv run python -c "
from src.rag import BGEEmbedder
e = BGEEmbedder()
v = e.embed_query('稻田氮素淋失')
print(f'dim={len(v)}, sample={v[:3]}')
"
```

首次跑会下载 ~1.3 GB 权重到 HuggingFace cache，需要梯子或镜像；
开发机 / CI 都不默认跑。

规则拍板：

- **每个带外部依赖的 sub-iteration，尽量自带一个贴身 live smoke**，用 env gate 默认跳过
- **父 milestone 收尾时再补集成 live 测**，覆盖跨组件真实链路

所以本轮就引入 `test_embedder_live.py`；M1.2.3 另补 `test_rag_live.py`
做 embedder + retriever 的集成实调。

## 5 验证方法

```bash
cd backend

# 1. 装新依赖
uv add 'sentence-transformers>=3.0,<4.0' 'chromadb>=0.5,<0.6'

# 2. 跑全套单测（应在 < 5s 内通过；不下载真实模型）
uv run pytest

# 3. 隔离验证 Embedder 构造不触发模型 load
uv run python -c "
from src.rag import BGEEmbedder
e = BGEEmbedder()
print('lazy ok' if e._model is None else 'EAGER LOAD BUG')
"

# 4.（可选）实调 BGE 的 smoke：默认跳过
RUN_LIVE_EMBED=1 uv run python -c "
from src.rag import BGEEmbedder
print(len(BGEEmbedder().embed_query('稻田氮素淋失')))
"

# 5.（可选）在临时目录实跑 ChromaStore 端到端
uv run python -c "
import tempfile
from src.storage import ChromaStore
with tempfile.TemporaryDirectory() as d:
    s = ChromaStore(d, 'smoke')
    s.add(['a'], ['hello'], [[0.1]*1024])
    print('count:', s.count())
"
```

结构化证据矩阵详见同目录 `review.md`（push 前定稿）。

## 6 与 M1.2.2 / M1.2.3 / M1.3 的衔接

| 后续 sub-iteration 需要的能力 | M1.2.1 提供的挂载点 |
|---|---|
| 切分器（M1.2.2） | 不依赖本迭代；输出 `list[Chunk]`，由 M1.2.3 的 indexer 拿去喂 Embedder + ChromaStore |
| 索引脚本（M1.2.3） | `BGEEmbedder().embed_documents(chunks)` → `ChromaStore(...).add(...)`；脚本拼接，零新抽象 |
| Retriever pipeline（M1.2.3） | `BGEEmbedder().embed_query(q)` → `ChromaStore(...).query(vec, k)` → 包成 retrieval result |
| chat 路由调用（M1.3）| 不直接依赖 ChromaStore / Embedder；只依赖 M1.2.3 的 Retriever；但 Retriever 若保持 sync API，则 async 路由内必须经 `asyncio.to_thread(...)` 调用 |
| 启动期初始化 Embedder（M2 之后）| 当 BGE load 时长无法接受时，可在 lifespan 里 `app.state.embedder = BGEEmbedder()` 提前 `_ensure_loaded()`；M1.2.1 不上 |

## 7 度量基线

| 指标 | 计划值 | 实际值 |
|---|---|---|
| 后端代码新增行数（非测试） | ≤ 130 | 待回填 |
| 新增单测数 | ≥ 8（embedder 5 + chroma 5） | 待回填 |
| 新增 Python 直接运行时依赖 | 0（默认安装路径） | 0 |
| 新增 Python 可选依赖 | 2（`rag` extra: sentence-transformers + chromadb） | 2 |
| 新增 Python 间接依赖 | TBD（torch / numpy / onnxruntime / etc.，估 30+） | 待回填 |
| pytest 全套耗时 | < 5s | 1.66s（默认不装 `rag` extra） |
| 装包冷启动后磁盘占用 | TBD（torch ~700MB）| 默认安装路径无新增大包；启用 `rag` extra 时仍可能增加 ~1.5GB |

## 8 风险

1. **chromadb 0.5 → 0.6 breaking**：锁 `>=0.5,<0.6`。chromadb API
   在 0.4 → 0.5 已经动过 `Settings` → `PersistentClient`，0.6 仍可能再动；
   升主版本时跑 `test_chroma_store.py` 兜底。
2. **sentence-transformers 与 torch 体量**：装包后虚拟环境会膨胀
   ~1.5 GB（torch CPU 版 ~700 MB）。CI 缓存命中率会显著影响构建时间，
   M1.2.3 之前不跑 `RUN_LIVE_EMBED=1`，CI 不下载模型权重。
3. **HuggingFace 下载需要梯子**：`BAAI/bge-large-zh-v1.5` 在 hf.co 上，
   国内访问需要镜像（`HF_ENDPOINT=https://hf-mirror.com`）。本迭代
   不在代码里写镜像 URL，由开发机 env 决定。
4. **PersistentClient 的进程独占**：chromadb 持久化模式下，同一 persist_dir
   被多个进程同时打开会读锁冲突。M1.3 chat 路由用 ChromaStore 时若 uvicorn
   多 worker，可能有问题；但 walking-skeleton spec 已经设定单 worker 模式，
   M1.3 之前不需要处理。
5. **Embedder lazy-load 隐藏首次延迟**：caller 首次调 `embed_query` 时
   ~5s 卡顿，对在线 chat 路由是可见延迟。M1.3 集成时通过 lifespan 期
   `app.state.embedder._ensure_loaded()` 兜底；本迭代不做。
6. **sync RAG API 进入 async 路由的阻塞风险**：M1.2.3 的 retriever 若维持
   sync 形状，M1.3 FastAPI 路由里直接调用会阻塞 event loop。约束写死：
   async 路由内统一经 `asyncio.to_thread(...)` 包装；是否整体 async 化再后评估。

## 9 参考

- BGE 模型卡片：<https://huggingface.co/BAAI/bge-large-zh-v1.5>
- chromadb 文档：<https://docs.trychroma.com/>
- sentence-transformers：<https://www.sbert.net/>
- ADR-004（Chroma 选型）：[`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md)
- 父级路标：M1.2 拆分为 3 个 sub-iteration（M1.2.1 骨架 / M1.2.2 切分器 /
  M1.2.3 索引脚本 + retriever pipeline）
- 同形先例：M1.1 LLMClient（[`../2026-05-04-m1-1-llm-client/spec.md`](../2026-05-04-m1-1-llm-client/spec.md)）
