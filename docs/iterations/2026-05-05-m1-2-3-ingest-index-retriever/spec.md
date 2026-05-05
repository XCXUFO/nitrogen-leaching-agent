# 说明文档 — M1.2.3 Ingest + 索引脚本 + Retriever

> 本文档是 **设计阶段** 产物（v1.0），落地后回填实际 commit、统计与偏离。
> 上承 M1.2.1（Embedder + ChromaStore）/ M1.2.2（chunker），完成 **M1.2 子链路**：
> `PDF/文本 → ingest → chunker → embedder → ChromaStore → retriever`。
> 下接 M1.3（chat 路由集成 RAG）。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代名 | m1-2-3-ingest-index-retriever |
| 日期 | 2026-05-05 |
| 涉及 commit | 待落地（push 前回填） |
| 文档版本 | v1.0（设计阶段） |
| 父里程碑 | M1（基础对话闭环） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 范围

### 2.1 在做

把 M1.2.1 / M1.2.2 已建好的两个原语（Embedder + ChromaStore + chunker）串成最小可跑闭环：

1. **`rag/ingest.py`**：本地 loader 边界
   - `load_text(path) -> str`：按文件后缀分发；输出 normalized 纯文本
   - `normalize_text(text) -> str`：去 BOM、行尾归一、双换行规整
   - `_load_pdf_text(path) -> str`：私有，PyMuPDF 实现，函数内 lazy import
2. **`backend/scripts/index_papers.py`**：离线索引脚本
   - CLI：`--paths` / `--persist-dir` / `--collection` / `--repo-root` / `--target-size` / `--max-size` / `--overlap`
   - 串 `ingest → chunker → BGEEmbedder.embed_documents → ChromaStore.upsert`
   - **使用 `upsert` 而非 `add` 以保证重跑幂等**（同 chunk_id 替换而非重复插入）
   - 输出索引摘要：文档数 / chunk 数 / chunks-per-doc / **平均 chunk 字符长度** / token 截断率打点估算
3. **`rag/retriever.py`**：在线检索器
   - `Retriever` 类持有 `Embedder` + `ChromaStore` 引用（构造期注入）
   - `retrieve(query, k) -> list[RetrievalResult]`：sync API；async 调用方走 `asyncio.to_thread(...)`
   - `RetrievalResult`：`@dataclass(frozen=True, slots=True)`，含 `chunk_id` / `text` / `score` / `metadata`

### 2.2 不在做（明确边界）

- ❌ 章节识别 / 双栏识别 / 表格还原 / OCR（M1.2.2 spec §2.2 已划走，本迭代不补）
- ❌ Markdown / HTML 结构化解析（`.md` 当纯文本读，不解析标题层级）
- ❌ 重排（reranker）→ M1.4 之后评估
- ❌ 引用抽取的高级形态（chunk → 原文片段反查）→ M1.3 chat 路由层做
- ❌ 接 chat 路由 → M1.3
- ❌ 嵌入向量缓存 / 增量索引（重跑全量重建即可，规模不大）
- ❌ 多向量库后端切换（只挂 ChromaStore）
- ❌ 异步 Retriever / 线程池配置 → M1.3 集成时按需

### 2.3 计划变更清单

| 项 | 文件 | 内容要点 |
|---|---|---|
| Ingest 模块 | `backend/src/rag/ingest.py` 新增 | `load_text` / `normalize_text` / `_load_pdf_text`；`PyMuPDF` 走函数内 lazy import |
| Retriever 模块 | `backend/src/rag/retriever.py` 新增 | `Retriever` 类 + `RetrievalResult` dataclass；构造期注入 Embedder + ChromaStore |
| `ChromaStore.upsert` | `backend/src/storage/chroma_store.py` 修改 | 新增 `upsert(...)` 方法（chromadb 0.5 原生支持），用于幂等重跑；`add(...)` 保留 |
| `rag/__init__.py` 公开导出 | `backend/src/rag/__init__.py` 修改 | 加 `load_text` / `normalize_text` / `Retriever` / `RetrievalResult` 到 `__all__` |
| 索引脚本 | `backend/scripts/index_papers.py` 新增 | CLI 入口；argparse；调用 ingest + chunker + embedder + `chroma_store.upsert` |
| `pyproject.toml` rag extra 增加 PyMuPDF | `backend/pyproject.toml` 修改 | `pymupdf>=1.24,<2.0` 加入 `rag` extra；`uv.lock` 同步更新 |
| 单元测试：ingest | `backend/tests/test_ingest.py` 新增 | normalize_text 行为 / 后缀分发 / .pdf lazy import / 不支持后缀报错 |
| 单元测试：retriever | `backend/tests/test_retriever.py` 新增 | 用 `FakeEmbedder` + 临时 ChromaStore；retrieve 结果排序 / 元数据透传 / 空集合返回 |
| 端到端 smoke | `backend/tests/test_index_pipeline.py` 新增 | 用 `data/papers/sample.txt`（仓库内）跑 ingest → chunker → ChromaStore → query；不实调 BGE，用 FakeEmbedder |
| Live 集成测 | `backend/tests/test_rag_live.py` 新增 | `RUN_LIVE_RAG=1` 守门；真实 BGE + Chroma；最小断言 |
| 语料目录 | `data/papers/sample.txt` 新增 + `data/papers/README.md` 新增 | 你提供一段中文论文摘要级文本；README 说明目录用途与 ignore 规则 |
| Git ignore | 仓库根 `.gitignore` 修改 | `data/papers/*.pdf` 全 ignore；保留 sample.txt + README.md |

## 3 关键判断

### 3.1 ingest 与 chunker 分层：loader 不知道 chunk

`load_text` 只输出"已规整的纯文本字符串"，不返回 segment / page_number / metadata。

理由：

- M1.2.2 spec 已经把 chunker 的输入契约钉成 `text + document_id + source + base_metadata`
  四个标量参数，没有 segment 概念
- ingest 现在是"轻量边界"，不是"重型 PDF 理解"；保持薄就别引入新数据结构
- 未来真要保页码 / 章节，**升级路径明确**：让 `load_text` 改返回 `list[DocumentSegment]`，
  caller（索引脚本）按 segment 切分并合并 metadata；chunker 接口不动
- 现在硬上 `DocumentSegment` 等于在没人消费的接口里塞抽象，纯成本

### 3.2 PyMuPDF 走函数内 lazy import

跟 `BGEEmbedder._ensure_loaded` 同思路：

- `import src.rag` 不能拉 PyMuPDF（PyMuPDF 不在默认依赖里，未装 rag extra 时会 ImportError）
- 单测 `test_ingest.py` 不需要触 PyMuPDF：用 `.txt` 文件测分发即可
- `_load_pdf_text` 第一次被调用时才 `import pymupdf`，失败时抛 `RuntimeError` 提示装 rag extra

错误信息风格对齐 `BGEEmbedder` / `ChromaStore`：

```python
raise RuntimeError(
    "pymupdf is not installed. "
    "Run `uv sync --extra rag` in backend/ before loading PDF files."
)
```

### 3.3 normalize_text 只做三件事

明确三步：

1. 去 BOM（`text.lstrip("﻿")`）
2. 行尾归一：`\r\n` → `\n`，`\r` → `\n`
3. 双换行规整：`re.sub(r"\n{3,}", "\n\n", text)` —— 三连及以上换行压成两个

**不做**的事（重要，避免 normalize 越界变成"PDF 清洗器"）：

- ❌ 全角半角转换
- ❌ 空格压缩 / trim
- ❌ Unicode normalize (NFC/NFD)
- ❌ 去页眉页脚
- ❌ 去引用编号 `[1]`、`[2]`
- ❌ 公式 / 表格清理

理由：上述清洗是高风险且难以在 chunker 层逆推 offset 的；
PDF 抽出来啥样就喂 chunker 啥样，所有"语义清洗"留给未来真正的 PDF parser 模块。

### 3.4 后缀分发的支持范围

```python
SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}
```

`.md` 当纯文本读，**不**解析 Markdown 结构（标题、列表、代码块）。

- `.txt` / `.md` → `Path(p).read_text(encoding="utf-8")`
- `.pdf` → `_load_pdf_text(p)`
- 其他后缀 → `ValueError`，错误信息带 `SUPPORTED_SUFFIXES` 集合内容

不接受字节流 / `BytesIO` / URL；`load_text` 只吃 `Path | str` 本地路径。
未来要支持远程 / 流式时再加 overload。

### 3.5 PyMuPDF 抽文本的策略

```python
import pymupdf  # PyMuPDF >= 1.24 顶层包名为 pymupdf
doc = pymupdf.open(str(path))
texts = [page.get_text("text") for page in doc]
return "\n\n".join(texts)
```

- 用 `"text"` 模式（默认）抽纯文本，不抽 blocks / dict / xml
- 页与页之间硬塞 `\n\n` 让 chunker 的双换行段落识别能识别页边界
- 不保留页码 metadata（见 §3.1，未来升级 segment 时再补）
- 不开 OCR（PyMuPDF 默认不带 OCR；扫描版 PDF 抽出来是空，本迭代不处理）

### 3.6 索引脚本职责单一：拼装而非抽象

`backend/scripts/index_papers.py` 是**可执行脚本**，不是库模块。规则：

- 不放 `backend/src/`（那是可被 import 的库代码）
- 不导出函数给其他模块复用；逻辑内联在 `main()`
- 路径列表通过 CLI 参数传入；不 hardcode 默认路径
- 顺序处理（不并发）：MVP 数据量小（≤ 30 篇），并发收益不抵复杂度
- 失败处理：单文件 ingest 失败时打印警告 + 跳过该文件；不让单 PDF 解析失败拖垮整批
- **幂等写入**：调用 `ChromaStore.upsert(...)` 而不是 `add(...)`。`add` 在重复 id 上会抛错，
  `upsert` 是 insert-or-replace，配合 §3.6.1 的稳定 `chunk_id` 让"重跑同一批文件 / `--paths` 误传重复"
  都不会让整批中断。不在脚本里手工 delete + add。

#### 3.6.1 document_id 生成规则（钉死，不允许随机）

`document_id` 由 CLI 路径**确定性**生成：

```python
def derive_document_id(path: Path, repo_root: Path) -> str:
    rel = path.resolve().relative_to(repo_root.resolve())
    stem_path = rel.with_suffix("")
    raw = str(stem_path).replace("\\", "/")        # Windows 安全
    return re.sub(r"[^A-Za-z0-9一-鿿/_-]", "_", raw)
```

- 默认 `repo_root` 取脚本启动时的 `Path.cwd()`；CLI 提供 `--repo-root` 覆盖
- 路径必须在 repo_root 之内，否则 `ValueError`（避免 `..` 路径污染 id）
- 规范化字符集：保留中英文字母 / 数字 / 中文 / `/_-`，其他字符替换为 `_`
- 规则示例：`data/papers/sample.txt` → `data/papers/sample`；`data/papers/2024_WHCNS.pdf` → `data/papers/2024_WHCNS`

理由：

- **重跑稳定**：同一 repo 同一路径每次跑出相同 id，`ChromaStore.add` 用 `chunk_id` 唯一性保证幂等
- **不用随机 / 时间戳**：随机会让重建索引漂位，时间戳让相同语料 diff 失败
- **不用文件 hash**：内容微改（如更新一个错字）会让 chunk_id 全变，反而失去稳定性意义；
  内容变更时主动调用方决定是否清空 collection 重建，比静默失效好控制
- **保留路径结构**：未来按目录前缀过滤（如 `data/papers/cn/` vs `data/papers/en/`）成本为零

CLI 形态：

```bash
uv run python backend/scripts/index_papers.py \
  --paths data/papers/sample.txt data/papers/paper001.pdf \
  --persist-dir backend/var/chroma \
  --collection papers \
  --target-size 300 --max-size 450 --overlap 60
```

### 3.7 Retriever 构造期注入 Embedder + ChromaStore

```python
class Retriever:
    def __init__(self, embedder: Embedder, store: ChromaStore) -> None: ...
    def retrieve(self, query: str, k: int = 5) -> list[RetrievalResult]: ...
```

理由：

- caller（M1.3 chat 路由）在 lifespan 期构造一次 Embedder + ChromaStore 复用，
  Retriever 只是组合层，不该自己持有"如何构造依赖"的知识
- 测试时注入 `FakeEmbedder` + 临时 ChromaStore，零网络 / 零模型加载
- 替换底层（如换 OpenAI Embedder / Qdrant）时 Retriever 代码不动

**反模式**：`Retriever(persist_dir=..., model_id=...)` 自己 new 出来。
拒绝理由同 ChromaStore 不持有 Embedder（M1.2.1 spec §3.5）：耦合 + 难测。

### 3.8 RetrievalResult 字段最小集（钉死，避免 M1.3 改接口）

```python
@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunk_id: str
    document: str             # ↔ chromadb 的 documents；即 Chunk.text
    score: float              # 越大越相关
    metadata: dict[str, str | int | float | bool]
```

字段命名拍板：用 `document` 而不是 `text`，对齐 chromadb 原生字段名（`documents`），
让 caller 一眼看出与底层数据形状的对应关系；同时 M1.3 chat 路由做引用展示时
直接消费 `result.document` / `result.metadata["source"]`，无需改接口。

- `score` 由 ChromaStore 返回的 `distances` 转换而来：
  BGE 输出已 L2-normalize，Chroma 默认 L2 距离；
  `score = 1.0 - distance / 2.0` 把 [0, 2] 区间的 L2 平方距离映射到 [0, 1] 的近似相似度
  （L2-normalized 向量下 `‖a-b‖² = 2 - 2·cos(a,b)`，因此 `1 - L2² / 2 = cos(a,b)`）
- 不返回 chromadb 原生 dict（让 caller 不依赖 chromadb 数据形状）
- metadata 字段透传 chunker 写入的 5 个保留字段 + base_metadata

### 3.9 Retriever sync API + asyncio.to_thread 约束

`retrieve(...)` 是同步函数。理由：

- BGEEmbedder.embed_query 是 sync（M1.2.1 §3.2）
- ChromaStore.query 也是 sync（chromadb 0.5 没有 async API）
- 在 sync 链路里包一层 async wrapper 没意义；统一让 async caller（M1.3 路由）走 `asyncio.to_thread(retriever.retrieve, query, k)`

把这条契约写进 retriever.py docstring 与本 spec，避免 M1.3 实现时再来一遍讨论。

### 3.10 token 截断率打点是估算，不引入 tokenizer

索引脚本输出"截断率估算"时，**不**引入 BGE tokenizer：

- 用粗略字符长度门槛打点：`chunk_chars > 350` 视为"可能被截断的 chunk"
- 输出 `(可能截断 / 总 chunk 数)` 比例
- M1.4 评测做精确截断率时再引 tokenizer

理由对齐 M1.2.2 spec §3.4：MVP 不让索引脚本拉 transformers / torch tokenizer。

### 3.11 端到端 smoke 不实调 BGE

`tests/test_index_pipeline.py` 测的是 ingest → chunker → ChromaStore 串联是否能跑通，
embedder 用 `FakeEmbedder`（按字符 hash 生成确定向量）：

- 不下载模型权重，CI / 默认 pytest 都能跑
- 真实 BGE 链路由 `tests/test_rag_live.py` 在 `RUN_LIVE_RAG=1` 下守门测
- 这条规则与 M1.2.1 spec §4.4 的 "live 守门" 设计同形

## 4 实现细节

### 4.1 `rag/ingest.py` 草图

```python
from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_SUFFIXES = frozenset({".txt", ".md", ".pdf"})

_BOM = "﻿"
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Apply minimal normalization: BOM, line endings, paragraph collapse.

    Does NOT do: unicode NFC/NFD, full-width/half-width conversion, whitespace
    compression, header/footer removal, citation cleanup. Those belong to a
    future PDF cleaning module, not this loader.
    """
    if text.startswith(_BOM):
        text = text[len(_BOM):]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text


def load_text(path: str | Path) -> str:
    """Read a local file and return normalized plain text.

    Dispatches by suffix:
      - .txt / .md → utf-8 read_text
      - .pdf       → PyMuPDF (lazy-imported)
      - other      → ValueError

    Raises:
        FileNotFoundError: path does not exist
        ValueError: unsupported suffix
        RuntimeError: pymupdf not installed (when path is .pdf)
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {p}")

    suffix = p.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"unsupported file suffix: {suffix!r}; "
            f"supported = {sorted(SUPPORTED_SUFFIXES)}"
        )

    if suffix in {".txt", ".md"}:
        raw = p.read_text(encoding="utf-8")
    else:  # .pdf
        raw = _load_pdf_text(p)

    return normalize_text(raw)


def _load_pdf_text(path: Path) -> str:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "pymupdf is not installed. "
            "Run `uv sync --extra rag` in backend/ before loading PDF files."
        ) from exc

    doc = pymupdf.open(str(path))
    try:
        pages = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return "\n\n".join(pages)
```

### 4.2 `rag/retriever.py` 草图

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.rag.base import Embedder
from src.storage.chroma_store import ChromaStore

ChunkMetaValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunk_id: str
    document: str                                   # ↔ chromadb documents
    score: float                                    # higher == more similar
    metadata: dict[str, ChunkMetaValue]


class Retriever:
    """Compose Embedder + ChromaStore into a query-time retrieval pipeline.

    Sync API. Async callers (e.g. FastAPI routes) must dispatch via
    ``asyncio.to_thread(retriever.retrieve, query, k)``.
    """

    def __init__(self, embedder: Embedder, store: ChromaStore) -> None:
        self._embedder = embedder
        self._store = store

    def retrieve(self, query: str, k: int = 5) -> list[RetrievalResult]:
        if not query.strip():
            return []
        if k <= 0:
            raise ValueError(f"k must be positive, got {k}")

        vector = self._embedder.embed_query(query)
        raw = self._store.query(vector, k=k)

        ids = raw.get("ids", [[]])[0]
        docs = raw.get("documents", [[]])[0]
        dists = raw.get("distances", [[]])[0]
        metas = raw.get("metadatas", [[]])[0] or [{}] * len(ids)

        results: list[RetrievalResult] = []
        for cid, doc, dist, meta in zip(ids, docs, dists, metas):
            score = 1.0 - float(dist) / 2.0   # see spec §3.8
            results.append(RetrievalResult(
                chunk_id=cid,
                document=doc,
                score=score,
                metadata=dict(meta) if meta else {},
            ))
        return results
```

### 4.3 `backend/scripts/index_papers.py` 草图

```python
"""Offline indexer: ingest → chunk → embed → ChromaStore.add.

Usage:
    uv run python backend/scripts/index_papers.py \
        --paths data/papers/sample.txt \
        --persist-dir backend/var/chroma \
        --collection papers
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.rag import BGEEmbedder, chunk_text, load_text
from src.storage import ChromaStore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline paper indexer")
    p.add_argument("--paths", nargs="+", required=True, type=Path)
    p.add_argument("--persist-dir", required=True, type=Path)
    p.add_argument("--collection", default="papers")
    p.add_argument("--repo-root", type=Path, default=Path.cwd(),
                   help="document_id 生成时用于计算相对路径的根；默认 cwd")
    p.add_argument("--target-size", type=int, default=300)
    p.add_argument("--max-size", type=int, default=450)
    p.add_argument("--overlap", type=int, default=60)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    embedder = BGEEmbedder()
    store = ChromaStore(args.persist_dir, args.collection)

    total_docs = 0
    total_chunks = 0
    truncation_warn = 0

    for path in args.paths:
        try:
            text = load_text(path)
        except Exception as exc:
            print(f"[warn] skip {path}: {exc}", file=sys.stderr)
            continue

        document_id = derive_document_id(path, args.repo_root)  # see spec §3.6.1
        chunks = chunk_text(
            text,
            document_id=document_id,
            source=str(path),
            target_size=args.target_size,
            max_size=args.max_size,
            overlap=args.overlap,
        )
        if not chunks:
            print(f"[warn] empty chunks for {path}, skip", file=sys.stderr)
            continue

        vectors = embedder.embed_documents([c.text for c in chunks])
        store.add(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=vectors,
            metadatas=[c.metadata for c in chunks],
        )

        total_docs += 1
        total_chunks += len(chunks)
        truncation_warn += sum(1 for c in chunks if len(c.text) > 350)

        print(f"[ok] {path}: {len(chunks)} chunks")

    avg = (total_chunks / total_docs) if total_docs else 0
    truncation_rate = (truncation_warn / total_chunks) if total_chunks else 0
    print(f"\nsummary: {total_docs} docs, {total_chunks} chunks, "
          f"avg {avg:.1f} chunks/doc, "
          f"~{truncation_rate:.1%} chunks > 350 chars (possibly truncated by BGE)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 4.4 `rag/__init__.py` 修改

```python
from src.rag.base import Embedder
from src.rag.bge import BGEEmbedder
from src.rag.chunker import Chunk, chunk_text
from src.rag.ingest import load_text, normalize_text, SUPPORTED_SUFFIXES
from src.rag.retriever import Retriever, RetrievalResult

__all__ = [
    "Embedder", "BGEEmbedder",
    "Chunk", "chunk_text",
    "load_text", "normalize_text", "SUPPORTED_SUFFIXES",
    "Retriever", "RetrievalResult",
]
```

### 4.5 `pyproject.toml` 改动

```toml
[project.optional-dependencies]
rag = [
    "sentence-transformers>=3.0,<4.0",
    "chromadb>=0.5,<0.6",
    "pymupdf>=1.24,<2.0",
]
```

`uv.lock` 由 `uv sync --extra rag` 生成；新增间接依赖估 5~10 个，不影响默认安装路径。

### 4.6 `data/papers/` + `.gitignore`

仓库根新增：

- `data/papers/sample.txt`：你提供的一段中文论文摘要级文本（约 1~2 KB），用于 smoke 测
- `data/papers/README.md`：说明用途 / 版权约束 / 命名约定（`{author}_{year}_{topic_short}.pdf`）

仓库根 `.gitignore` 增量：

```gitignore
# 论文语料（版权敏感，不入库）
data/papers/*.pdf
!data/papers/sample.txt
!data/papers/README.md

# 索引脚本生成的本地 chroma 持久化产物（不入库）
backend/var/
```

## 5 测试策略

### 5.1 `tests/test_ingest.py`（mock-free，全部默认跑）

| # | 名称 | 断言要点 |
|---|---|---|
| 1 | `test_normalize_text_strips_bom` | BOM 在首位时被剥掉；非首位的 `﻿` 不动 |
| 2 | `test_normalize_text_unifies_line_endings` | `\r\n` / `\r` 都变 `\n` |
| 3 | `test_normalize_text_collapses_3plus_newlines` | `\n\n\n\n` → `\n\n`；两个换行原样 |
| 4 | `test_normalize_text_does_not_strip_whitespace` | 段内空格、行首缩进保留（避开越界清洗） |
| 5 | `test_normalize_text_is_idempotent` | `normalize_text(normalize_text(t)) == normalize_text(t)`，覆盖含 BOM / `\r\n` / 多重换行的混合输入 |
| 6 | `test_load_text_reads_txt` | 写临时 `.txt` 文件，回读后内容等于 normalize 后的内容 |
| 7 | `test_load_text_reads_md_as_plain_text` | `.md` 走 utf-8 读取，不解析 Markdown 结构 |
| 8 | `test_load_text_unsupported_suffix_raises` | `.docx` / `.html` 等抛 `ValueError`，错误消息含 supported 集合 |
| 9 | `test_load_text_missing_file_raises` | `FileNotFoundError` |
| 10 | `test_pdf_path_lazy_imports_pymupdf` | 用 `monkeypatch` 把 pymupdf 屏蔽掉，调 `_load_pdf_text` 抛 RuntimeError 含 `uv sync --extra rag` |

### 5.2 `tests/test_retriever.py`（mock-free，临时 ChromaStore）

用 `FakeEmbedder`（确定性向量，按字符 hash 或简单线性变换）+ `tmp_path` 临时 ChromaStore：

| # | 名称 | 断言要点 |
|---|---|---|
| 1 | `test_retrieve_empty_query_returns_empty_list` | `retrieve("", 5) == []`、`retrieve("   ", 5) == []` |
| 2 | `test_retrieve_invalid_k_raises` | `k=0` / `k=-1` 抛 `ValueError` |
| 3 | `test_retrieve_returns_results_in_score_order` | 塞 3 条文档；query 与第 2 条最近；返回首位 chunk_id 等于第 2 条的 |
| 4 | `test_retrieve_passes_through_metadata` | 写入时 metadata 含 `source` / `chunk_index` 等；返回的 `RetrievalResult.metadata` 一致 |
| 5 | `test_retrieve_score_in_zero_one_range` | 对已 L2-normalize 的向量，score ∈ [0, 1]（允许浮点小裕度） |
| 6 | `test_retrieve_on_empty_collection_returns_empty_list` | 空集合 query 不抛、返回 `[]` |

### 5.3 `tests/test_index_pipeline.py`（端到端 smoke，不实调 BGE）

| # | 名称 | 断言要点 |
|---|---|---|
| 1 | `test_pipeline_ingest_chunk_store_query` | 用 `data/papers/sample.txt` + FakeEmbedder + `tmp_path` ChromaStore；跑完后 `store.count() > 0`；用 sample 内一句话 query，能召回到含该句的 chunk |
| 2 | `test_pipeline_is_idempotent_on_repeat` | 同一批 `upsert` 跑两次后 `store.count()` 不增；防回归到 `add` |
| 3 | `test_pipeline_chunk_metadata_lands_in_store` | 入库 chunk 的 `metadata.source` / `chunk_index` / `char_start` / `char_end` 在 query 返回时完整 |

### 5.4 `tests/test_rag_live.py`（live 守门，默认跳过）

```python
import os, pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_RAG"),
    reason="set RUN_LIVE_RAG=1 to run BGE + Chroma end-to-end",
)
```

| # | 名称 | 断言要点 |
|---|---|---|
| 1 | `test_live_index_and_retrieve_sample` | 用 `data/papers/sample.txt` + 真实 `BGEEmbedder` + 临时 ChromaStore；index 后 retrieve("氮素淋失") 返回非空，且首位 chunk text 含相关词 |

### 5.5 验证命令

```bash
cd backend

# 1. 单元测试（默认）
uv run pytest tests/test_ingest.py tests/test_retriever.py tests/test_index_pipeline.py -v

# 2. 全套回归（应在 < 5s 内通过）
uv run pytest

# 3. 装 rag extra（首次需要，含 PyMuPDF + sentence-transformers + chromadb）
uv sync --extra rag

# 4. 离线索引脚本（用 sample）
uv run python backend/scripts/index_papers.py \
    --paths data/papers/sample.txt \
    --persist-dir backend/var/chroma \
    --collection papers

# 5. live RAG smoke
RUN_LIVE_RAG=1 uv run pytest tests/test_rag_live.py -v
```

## 6 与 M1.3 的衔接

| M1.3 chat 路由需要 | 本迭代提供 |
|---|---|
| RAG retrieval 入口 | `Retriever(embedder, store).retrieve(query, k)` |
| async 路由内调用 | `await asyncio.to_thread(retriever.retrieve, query, k)` |
| 索引数据来源 | M1.3 不重新索引；离线跑过 `index_papers.py` 后 chat 路由直接打开同一 `persist_dir` |
| Embedder / ChromaStore 生命周期 | M1.3 在 `app.lifespan` 期构造一次复用；不在请求路径上 new |

**契约一句话**：
M1.3 在 lifespan 期 `embedder = BGEEmbedder()` + `store = ChromaStore(persist_dir, collection)`，
路由处理函数里 `await asyncio.to_thread(Retriever(embedder, store).retrieve, query, k)`。
不允许路由内重新构造 Embedder。

## 7 度量基线

| 指标 | 计划值 | 实际值 |
|---|---|---|
| 后端代码新增行数（非测试 + 不含脚本） | ≤ 200 | 待回填 |
| 索引脚本行数 | ≤ 100 | 待回填 |
| 新增单测数 | ≥ 25（ingest 10 + retriever 7 + pipeline 3 + chroma_store 增量 2 + index_papers 6） | 待回填 |
| Live 测数 | ≥ 1 | 待回填 |
| 新增依赖（rag extra） | 1（pymupdf） | 待回填 |
| pytest 默认全套耗时 | < 5s | 待回填 |
| sample.txt 索引耗时（FakeEmbedder） | < 1s | 待回填 |

## 8 风险

1. **PyMuPDF 抽出文本质量参差不齐**：双栏 / 表格 / 公式 PDF 抽出来会乱序或粘连。
   缓解：MVP 阶段你手工筛选"单栏 + 偏纯文字"的论文做 sample；
   质量差的留给未来 PDF parser 模块；本迭代不补结构化解析。
2. **`page.get_text("text")` 不保留页码**：未来要做"按页引用"时无法回查。
   缓解：升级路径明确 — `_load_pdf_text` 改返回 `list[(page_no, text)]`，
   chunker 输入升级成 segment list；本迭代不预先做。
3. **chromadb persist_dir 进程锁**：M1.3 chat 路由跑时不能再跑 `index_papers.py`，
   否则会读锁冲突。
   缓解：spec / README 写清"索引脚本要在服务停机时跑"；
   uvicorn 单 worker 模式（已由 walking-skeleton 钉死）减少冲突面。
4. **truncation 估算用字符数门槛而非 tokenizer**：`> 350` 是粗估，
   英文 / 公式比例高时会偏；中文密集时会过保守。
   缓解：M1.4 评测做精确截断率统计；本迭代不引入 tokenizer。
5. **sample.txt 内容选取不当**：你提供的样本太短或主题太偏，
   pipeline smoke 通过但不代表真实论文索引能跑。
   缓解：sample 至少含 200 字、覆盖"氮素淋失"等核心关键词，让 retrieve 测能命中。
6. **score 转换公式假设 BGE L2-normalize**：换 embedder 后该公式可能错。
   缓解：score 转换只在 Retriever 里做；换 embedder 时 review 这一行。
   spec / docstring 注明"假设 embedder 输出已 L2-normalize"。
7. **PyMuPDF 1.x → 2.x breaking**：API 改动历史频繁。
   缓解：锁 `>=1.24,<2.0`；升 2.x 时跑 ingest 测兜底。

## 9 参考

- M1.2.1 spec：[`../2026-05-05-m1-2-1-embedder-chromastore/spec.md`](../2026-05-05-m1-2-1-embedder-chromastore/spec.md)
- M1.2.2 spec：[`../2026-05-05-m1-2-2-chunker/spec.md`](../2026-05-05-m1-2-2-chunker/spec.md)
- PyMuPDF 文档：<https://pymupdf.readthedocs.io/>
- chromadb 文档：<https://docs.trychroma.com/>
- ADR-004（Chroma 选型）：[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)
- 父级路标：M1.2 的最后一个 sub-iteration（M1.2.1 骨架 / M1.2.2 切分器 / **M1.2.3 串联闭环**）
