# 说明文档 — M1.2.2 文档切分器（Chunker）

> 本文档是 **设计阶段** 产物（v1.0），落地后回填实际 commit、统计与偏离。
> 上承 M1.2.1（Embedder + ChromaStore），下接 M1.2.3（索引脚本 + retriever pipeline）。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代名 | m1-2-2-chunker |
| 日期 | 2026-05-05 |
| 涉及 commit | 待落地（push 前回填） |
| 文档版本 | v1.0（设计阶段） |
| 父里程碑 | M1（基础对话闭环） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 范围

### 2.1 在做

为 M1.2.3 indexer 提供一个 **模型无关的字符级文档切分器**，把"已抽取好的纯文本 + 元数据"切成 `list[Chunk]`：

1. **`Chunk` 数据结构**（`rag/chunker.py`）：`@dataclass(frozen=True, slots=True)`，含 `chunk_id` / `document_id` / `text` / `metadata` 四个字段
2. **`chunk_text(...)` 函数**：纯函数、无状态、无 I/O；按"段落优先 + 字符窗口兜底 + overlap"策略切分
3. **`rag/__init__.py` 公开导出**：`Chunk`、`chunk_text`

### 2.2 不在做（明确边界）

- ❌ PDF / Markdown / HTML 解析（上游 parser 后续模块负责，MVP 阶段也未必单独成模块）
- ❌ OCR / 双栏识别 / 表格还原 / 公式抽取
- ❌ 章节识别（不试图理解 "摘要 / 引言 / 方法 / 结论" 等学术结构）
- ❌ Embedding（M1.2.1 已落）
- ❌ 向量库写入（M1.2.3）
- ❌ 检索 / 重排 / 引用抽取（M1.2.3）
- ❌ Token-aware 切分（不引入 tokenizer 依赖；见 §3.4）
- ❌ Live API / 网络调用（无外部依赖，纯 CPU 字符串处理）
- ❌ 多语言切换策略（中英混排按统一字符级处理；不为英文单独建一条路径）

### 2.3 计划变更清单

| 项 | 文件 | 内容要点 |
|---|---|---|
| `Chunk` dataclass + `chunk_text` 函数 | `backend/src/rag/chunker.py` 新增 | `@dataclass(frozen=True, slots=True)` 定义 Chunk；`chunk_text(...)` 函数实现段落优先 + overlap 切分 |
| `rag/__init__.py` 公开导出 | `backend/src/rag/__init__.py` 修改 | `__all__ = ["Embedder", "BGEEmbedder", "Chunk", "chunk_text"]` |
| 单元测试 | `backend/tests/test_chunker.py` 新增 | ≥ 10 个用例，覆盖空文本 / 短文本 / 多段落 / 超长段落 / overlap / 区间单调性 / metadata 透传 / chunk_id 格式 / 保留字段保护 / 中文标点回退 |
| 无新增依赖 | — | 不动 `pyproject.toml`、不动 `uv.lock` |

## 3 关键判断

### 3.1 函数 而不是 类

`chunk_text(...)` 设计为纯函数，不是 `Chunker` 类 + `.chunk()` 方法。理由：

- MVP 只有"段落优先 + 字符窗口"一种策略，没有需要在实例间共享的状态
- 参数（target_size / max_size / overlap）在调用期通过 keyword-only 注入，零隐藏依赖
- 测试不需要构造 fixture；直接 `chunk_text(...)` 调用即可
- 未来若引入第二种策略（如 markdown-aware / token-aware），再升格为协议或类，**不破坏现有调用方**：
  M1.2.3 indexer 持有的是函数引用，迁移时改成 `chunker.chunk(...)` 是局部改动

反例：现在就上 `class Chunker(ABC)` + `class CharChunker(Chunker)` 是过度设计，
当前没有第二个实现作为 ABC 的存在理由。

### 3.2 Chunk 用 dataclass(frozen=True, slots=True) 而不是 pydantic

`Chunk` 是 RAG pipeline 内部数据载体，**不跨进程传输**、**不来自外部输入**。
和 M1.2.1 的 `dim` / `embed_documents` 返回 `list[list[float]]` 同思路：
内部数据结构无校验需求时不引入 pydantic。

- `frozen=True`：构造后不可变，避免 caller 误改 metadata 后影响已入库 chunk
- `slots=True`：内存占用降低 ~40%（万级 chunk 量时可见）；阻止意外加属性
- 校验由构造期在 `chunk_text` 内部完成（保留字段冲突 / metadata 类型 / id 唯一性）

如未来 M1.2.3 需要 API 边界校验，再用 pydantic 做 wrapper，不动核心类型。

### 3.3 chunk_id 用确定性格式 而不是 UUID

格式拍板：

```
chunk_id = f"{document_id}::{chunk_index:04d}"
```

理由：

- **可重跑**：同一份文档重新切分（如调参后重建索引），chunk_id 保持稳定，
  M1.2.3 的 indexer 可用 `add` / `upsert` 语义而不是先 `delete` 再 `add`
- **可 diff**：测试断言 / 日志检查时人眼可读
- **可追溯**：从 chunk_id 一眼看出归属哪份文档、是第几块
- **唯一性**：在单次 `chunk_text(...)` 调用内由 `chunk_index` 单调自增保证；
  跨调用唯一性由 caller 通过 `document_id` 全局唯一来保证（M1.2.3 的责任）

`:04d` 给单文档预留 1 万块上限，对论文场景（典型 50~200 块）远超够用。
若极端长文档触顶，spec 9 风险条目里登记。

### 3.4 字符级切分 而不是 token-aware

**问题**：BGE-large-zh-v1.5 上下文上限 512 token；理论上 chunk 应按 token 边界切。

**反对引入 tokenizer 的理由**：

- 引入 tokenizer 等于把 M1.2.2 跟 BGE 的 tokenizer 强耦合；
  未来换 embedder（OpenAI / E5）时切分结果会变，已索引的库要重建
- `transformers.AutoTokenizer` 的导入会拉 torch，违反 M1.2.1 §3.2 "rag 默认 import 不触 torch" 的设计意图
- 中文 tokenizer 的字符↔token 比例本身就在 1:1 ~ 1:1.5 之间波动，
  "精确按 token 切" 在中文场景的实际收益远低于英文

**方案**：

- M1.2.2 是 **模型无关的字符级 chunker**
- 提供保守默认值（见 §4.2）以**降低**被 BGEEmbedder 截断的概率
- **不做绝对保证**：spec 不写"≤ N 字符就一定不会被截断"这种伪精确承诺
- 截断由 BGEEmbedder 内部 `model.encode(...)` 默认行为兜底（sentence-transformers 默认会截到 max_seq_length）
- 如 M1.2.3 离线索引或 M1.4 评测观察到截断率显著（如 > 5% chunk 在 embed 时被截），再升级为 token-aware 切分；不预先优化

### 3.5 metadata 保留字段保护

`base_metadata` 由 caller（M1.2.3 indexer）传入，用于透传论文级元信息（如 `title`、`author`、`year`）。
切分器内部会向 metadata 写 5 个保留字段：

```
source, document_id, chunk_index, char_start, char_end
```

**反模式**：让 caller 的 `base_metadata` 静默覆盖保留字段。
**问题**：caller 笔误传入 `chunk_index` 会污染所有 chunk 的索引位置，
索引建好后查询时排序错乱，难定位。

**方案**：构造期检测冲突 → 立即 `ValueError`：

```python
RESERVED = {"source", "document_id", "chunk_index", "char_start", "char_end"}
if base_metadata and (RESERVED & base_metadata.keys()):
    raise ValueError(f"base_metadata cannot contain reserved keys: {RESERVED}")
```

caller 看到错误立刻改代码，比静默错误好诊断。

### 3.6 metadata 必须扁平且只接受标量

**约束来源**：chromadb 0.5 的 `metadata` 字段只支持 `str | int | float | bool` 标量值，
嵌套 dict / list 会在 `add(...)` 时抛 `ValueError`。

**M1.2.2 的责任**：在写出 Chunk 之前就校验 base_metadata，把错误关在切分阶段，
不让它一直传到 M1.2.3 indexer 才在向量库写入时炸。

**实现**：构造 Chunk 前对 base_metadata 的所有 value 跑类型检查；
非标量直接 `TypeError`，错误信息包含字段名。

### 3.7 段落优先 + 字符窗口兜底 + overlap

**统一切片口径**：所有 chunk.text 一律由 `original_text[char_start:char_end]` 切片生成，
不做任何 normalize / strip / 重排。这条契约钉死，是 §4.3 不变式的来源。

**段落识别 vs 切片来源**：

- 段落识别只是**找出段落起止 offset 与"是否为空白段"的标记**，**不剔除任何字符**
- 段落分隔符（双换行等空白）**归前一个非空白段**：前段的 `char_end` 推到该段后的连续空白尾部，
  让相邻段落合并 chunk 满足 `char_end[i] == char_start[i+1]`
- 文档**起始**处的空白字符（首个非空白段之前的所有空白）归**首块**的 `char_start` 之前：
  即首块 `char_start` 等于"首个非空白段在原文中的位置"，**不强行 == 0**
- 文档**末尾**处的空白字符归**末块**的 `char_end` 之后：
  即末块 `char_end` 等于"末个非空白段的结束位置"，**不强行 == len(text)**

**策略**：

1. 扫描原文，识别段落区间（按 `\n{2,}` 分隔），但保留每段在原文中的 offset
2. 顺序累加非空白段到 buffer，buffer 字符长度 ≥ `target_size` 即生成一个 chunk；
   chunk 的 `char_start` 取 buffer 首段的起始 offset，`char_end` 取 buffer 末段后**包含到下一段开始前所有连续空白**的位置（让相邻 chunk 边界对齐）
3. 单个段落本身就 > `max_size` 的情形：先 flush 当前 buffer，再对该段按字符窗口硬切，
   窗口大小 `max_size`，步长 `max_size - overlap`，offset 全部基于原文
4. 相邻 chunk 之间留 `overlap` 字符（**仅在硬切超长段落时发生**；段落合并产生的 chunk 之间无 overlap，
   `char_end == next.char_start`）

**为什么不强制段落合并产生的 chunk 之间也加 overlap**：
段落级边界本身已经是语义自然分界（作者写作意图分段），
硬塞 overlap 会让前后 chunk 同时持有同一段开头，反而增加冗余、稀释检索权重。

**为什么不做"小段合并到 target_size 后还要回头给前一个 chunk 加 overlap"**：
策略复杂度上升一档（需要前后查看），MVP 不做；如检索召回不足，
M1.4 评测结果会指明，那时再加。

### 3.8 中文标点边界回退

**问题**：硬切超长段落时，窗口边界可能落在英文单词中间或中文标点前后，
切出来的 chunk 头尾观感不佳（虽然不影响 embedding）。

**方案**：超长段落硬切时，**单向向前回退**——在 `[end - lookback, end]` 范围内
（`lookback = int(max_size * 0.1)`）寻找最近的边界字符；找到则把切点回退到该字符之后的位置，
找不到则保持原始 `end` 位置切（保证总是有进展，不死循环）。

**为什么单向**：

- 向后扩展会越过 `max_size` 上限，违反 chunk 长度约束
- 向前回退最多牺牲 `lookback` 字符的"理想填充率"，但保证 chunk 长度 ≤ `max_size`
- "回退"语义清晰，实现简单，测试好断言

边界字符集（写进代码常量 `_BOUNDARY_CHARS`）：

```
中文：。！？；
英文：. ! ? ; \n
空白：\t \r 空格
```

**不做的事**：不在段落合并产生的 chunk 上做边界回退（段落本身已经是好边界）。

## 4 实现细节

### 4.1 `Chunk` dataclass 草图

```python
# backend/src/rag/chunker.py
from dataclasses import dataclass

ChunkMetaValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class Chunk:
    """RAG pipeline 内部数据载体。

    - 字段全部不可变（frozen=True）
    - metadata 是扁平 dict，value 仅 str/int/float/bool
      （对齐 chromadb 0.5 的 metadata 限制）
    - chunk_id 由 chunk_text 按 ``f"{document_id}::{chunk_index:04d}"`` 生成
    """

    chunk_id: str
    document_id: str
    text: str
    metadata: dict[str, ChunkMetaValue]
```

### 4.2 `chunk_text` 函数签名 + 默认值

```python
def chunk_text(
    text: str,
    document_id: str,
    source: str,
    *,
    target_size: int = 300,
    max_size: int = 450,
    overlap: int = 60,
    base_metadata: dict[str, ChunkMetaValue] | None = None,
) -> list[Chunk]:
    """将纯文本切成 Chunk 列表。

    Args:
        text: 已抽取好的纯文本（不做 PDF / HTML 解析）。
        document_id: 文档级唯一 id；caller 保证全局唯一。
        source: 文档来源（文件路径 / 论文标识等），写入每个 chunk 的 metadata.source。
        target_size: 段落合并目标字符数；buffer ≥ 此值即出 chunk。默认 300。
        max_size: 单 chunk 上限；超出此值的段落按字符窗口硬切。默认 450。
        overlap: 硬切时相邻 chunk 的字符重叠数。默认 60。
        base_metadata: 透传到每个 chunk 的额外元数据；不允许包含保留字段
            (source / document_id / chunk_index / char_start / char_end)；
            value 仅允许 str / int / float / bool。

    Returns:
        list[Chunk]，按文档顺序排列；空文本返回空 list。

    Raises:
        ValueError: base_metadata 包含保留字段；或参数不满足
            ``0 < target_size <= max_size`` / ``0 <= overlap < max_size``。
        TypeError: base_metadata 含非标量 value。
    """
```

**默认值的解释**（spec 必读，避免未来 review 反复争论）：

- `target_size=300`：段落合并目标字符数；中文论文典型段落 100~500 字符，
  300 是经验中位数，兼顾"不过碎"与"不会一段塞太多"
- `max_size=450`：单 chunk 字符上限；MVP 阶段保守值，目的是降低被 BGE-large-zh-v1.5
  截断的概率（512 token 上限，中文字符↔token 经验比 1:1~1:1.5，450 字符大致对应 450~675 token，
  数字 / 英文 / 公式混入时偏高，仍可能被截断 — 这不是绝对保证）
- `overlap=60`：硬切时的字符重叠，约 13% 的 max_size，
  让跨段落语义不在硬切边界丢失；过大会增加索引体积与检索冗余

**关键非承诺**：spec 不声明"使用默认值就一定不会被 BGE 截断"。
若 M1.2.3 / M1.4 观察到截断率高，调参或升级为 token-aware；不预先优化。

### 4.3 算法伪代码

```
def chunk_text(text, document_id, source, *, target_size, max_size, overlap, base_metadata):
    # 1. 参数与 base_metadata 校验
    validate_params(target_size, max_size, overlap)
    validate_base_metadata(base_metadata)  # 保留字段冲突 + 标量类型

    # 2. 空文本短路
    if not text.strip():
        return []

    # 3. 段落切分
    paragraphs = split_paragraphs(text)  # re.split(r"\n{2,}", ...)，过滤空白

    # 4. 段落合并 / 硬切，产出 (chunk_text, char_start, char_end) 三元组列表
    spans = []
    buffer = []
    buffer_start = None
    for para, para_start, para_end in paragraphs_with_offsets(text):
        if len(para) > max_size:
            # 先把当前 buffer 出成 chunk
            flush_buffer(buffer, buffer_start, spans)
            buffer, buffer_start = [], None
            # 长段按窗口硬切，带 overlap 与边界回退
            spans.extend(hard_split(para, para_start, max_size, overlap))
        else:
            if buffer_start is None:
                buffer_start = para_start
            buffer.append(para)
            if total_len(buffer) >= target_size:
                flush_buffer(buffer, buffer_start, spans, end=para_end)
                buffer, buffer_start = [], None
    flush_buffer(buffer, buffer_start, spans)

    # 5. 包装成 Chunk
    chunks = []
    for idx, (chunk_str, start, end) in enumerate(spans):
        meta = {**(base_metadata or {})}
        meta["source"] = source
        meta["document_id"] = document_id
        meta["chunk_index"] = idx
        meta["char_start"] = start
        meta["char_end"] = end
        chunks.append(Chunk(
            chunk_id=f"{document_id}::{idx:04d}",
            document_id=document_id,
            text=chunk_str,
            metadata=meta,
        ))
    return chunks
```

**`hard_split` 的核心逻辑**：

```
def hard_split(para, para_start, max_size, overlap):
    step = max_size - overlap
    spans = []
    pos = 0
    while pos < len(para):
        end = min(pos + max_size, len(para))
        # 单向向前回退：仅在 [end - lookback, end] 内查找最近的边界字符
        if end < len(para):
            end = backtrack_to_boundary(para, end, lookback=int(max_size * 0.1))
        spans.append((
            para[pos:end],
            para_start + pos,
            para_start + end,
        ))
        if end >= len(para):
            break
        pos = end - overlap
    return spans
```

**`backtrack_to_boundary` 字符集**（写进代码常量）：

```python
_BOUNDARY_CHARS = "。！？；.!?;\n\r\t "
```

**不变式**（实现必须满足，测试会断；非空文本场景）：

- **切片来源**：`chunk.text == original_text[char_start:char_end]`，对每个 chunk 严格成立
- **首块起点**：`chunks[0].metadata["char_start"]` == 原文首个非空白字符的索引
  （**不一定 == 0**；首段前的空白被丢弃在首块之外）
- **末块终点**：`chunks[-1].metadata["char_end"]` == 原文末个非空白字符的索引 + 1
  （**不一定 == len(text)**；末段后的空白被丢弃在末块之外）
- **段落合并相邻**：若 `chunks[i]` 与 `chunks[i+1]` 都来自段落合并路径，则
  `chunks[i].metadata["char_end"] == chunks[i+1].metadata["char_start"]`（分隔符归前块）
- **硬切相邻**：若 `chunks[i]` 与 `chunks[i+1]` 来自同一段落的硬切，则
  `chunks[i+1].metadata["char_start"] == chunks[i].metadata["char_end"] - overlap`（重叠 `overlap` 字符）
- **chunk_index 密集单调**：`chunks[i].metadata["chunk_index"] == i`
- **区间单调**：`char_start[i] < char_start[i+1]`、`char_end[i] <= char_end[i+1]`

### 4.4 `rag/__init__.py` 修改

```python
from src.rag.base import Embedder
from src.rag.bge import BGEEmbedder
from src.rag.chunker import Chunk, chunk_text

__all__ = ["Embedder", "BGEEmbedder", "Chunk", "chunk_text"]
```

## 5 测试策略

`backend/tests/test_chunker.py`（mock-free，纯文本驱动，全部默认跑）。

### 5.1 必测用例（≥ 10 条）

| # | 名称 | 断言要点 |
|---|---|---|
| 1 | `test_empty_text_returns_empty_list` | `chunk_text("", ...)` / `chunk_text("   \n\n  ", ...)` 都返回 `[]` |
| 2 | `test_short_text_returns_single_chunk` | text 远小于 target_size，结果长度 1，覆盖整个原文 |
| 3 | `test_paragraphs_merged_until_target_size` | 多个小段被合并；合并后的 chunk 长度 ≥ target_size 且 ≤ max_size |
| 4 | `test_long_paragraph_hard_split_with_overlap` | 单段 > max_size 时按窗口硬切；相邻 chunk 末尾/开头存在 overlap 字符重叠 |
| 5 | `test_chunk_index_is_monotonic_and_dense` | `[c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))` |
| 6 | `test_char_offsets_form_valid_intervals` | 对每个 chunk 断 `chunk.text == text[char_start:char_end]`；首块 `char_start` 等于原文首个非空白字符索引；末块 `char_end` 等于原文末个非空白字符索引 + 1；区间单调；段落合并相邻满足 `char_end == next.char_start`；硬切相邻满足 `next.char_start == char_end - overlap` |
| 7 | `test_chunk_id_format` | 形如 `"{document_id}::0000"`、`::0001`...；前缀始终等于 document_id |
| 8 | `test_base_metadata_passes_through` | `base_metadata={"title": "X", "year": 2024}` 在每个 chunk 的 metadata 里都能拿到 |
| 9 | `test_base_metadata_with_reserved_key_raises` | `base_metadata={"chunk_index": 99}` 等 → `ValueError`；错误信息含 `chunk_index` 字段名 |
| 10 | `test_base_metadata_with_non_scalar_value_raises` | `base_metadata={"tags": ["a", "b"]}` → `TypeError`；`{"nested": {"k": 1}}` → `TypeError` |
| 11 | `test_chinese_punctuation_boundary_backtrack` | 长段在标点附近时，硬切位置回退到最近的 `。！？` 等而不是切在词中 |
| 12 | `test_invalid_params_raise` | `target_size=0` / `target_size > max_size` / `overlap >= max_size` / `overlap < 0` 全部 `ValueError` |

### 5.2 不测的事

- 不测 embedding（M1.2.1 已覆盖）
- 不测 chromadb 写入（M1.2.1 已覆盖；M1.2.3 集成层再补）
- 不测真实论文 PDF 切分质量（M1.4 评测做）
- 不引入 live 测（无外部依赖）
- 不测性能（万级 chunk 量纯字符串处理 < 1s 够用，M1.2.3 索引脚本若卡再回头测）

### 5.3 验证命令

```bash
cd backend

# 单元测试（应在 < 2s 内通过；不下载任何模型）
uv run pytest tests/test_chunker.py -v

# 全套测试无回归
uv run pytest

# 手工 smoke
uv run python -c "
from src.rag import chunk_text
text = '''
摘要：本文研究了不同施肥管理模式下的氮素淋失情况。

引言段落，约 200 字省略...

' + '材料与方法。' * 100 + '

结果讨论。
'''
chunks = chunk_text(text, document_id='paper-001', source='/tmp/paper.pdf')
for c in chunks:
    print(c.chunk_id, c.metadata['char_start'], '-', c.metadata['char_end'], '|', c.text[:30].replace(chr(10), ' '))
"
```

## 6 与 M1.2.3 / M1.3 的衔接

| 后续 sub-iteration 需要的能力 | M1.2.2 提供的挂载点 |
|---|---|
| 索引脚本（M1.2.3） | `chunks = chunk_text(text, doc_id, src)` → `vectors = BGEEmbedder().embed_documents([c.text for c in chunks])` → `ChromaStore(...).add(ids=[c.chunk_id for c in chunks], documents=[c.text for c in chunks], embeddings=vectors, metadatas=[c.metadata for c in chunks])` |
| Retriever pipeline（M1.2.3） | 不直接依赖 chunker；但消费的 metadata 字段命名（source / document_id / chunk_index / char_start / char_end）由本 spec 钉死，retriever 据此做引用展示与上下文展开 |
| chat 路由（M1.3） | 不直接依赖 chunker；通过 retriever 间接消费 metadata 字段 |
| 引用抽取（M1.2.3 / M1.3） | 用 chunk metadata 中的 `source` + `char_start` / `char_end` 反查原文片段；本 spec 保证 `text == original[char_start:char_end]` 的不变式让追溯无歧义 |

**握手契约一句话**：
M1.2.2 保证每个 Chunk 有非空 `text`、确定性 `chunk_id`、扁平 `metadata` 含 5 个保留字段；
M1.2.3 直接 `embed_documents([c.text for c in chunks])` 后喂 ChromaStore，零中间转换。

## 7 度量基线

| 指标 | 计划值 | 实际值 |
|---|---|---|
| 后端代码新增行数（非测试） | ≤ 150 | 待回填 |
| 新增单测数 | ≥ 12 | 待回填 |
| 新增依赖 | 0（标准库 dataclasses + re） | 待回填 |
| pytest 全套耗时 | < 3s（默认不装 `rag` extra） | 待回填 |
| 万字符文本切分耗时（参考） | < 100ms | 待回填 |

## 8 风险

1. **默认参数对 BGE 截断率未知**：300 / 450 / 60 是字符级保守值，
   实际 BGE-large-zh-v1.5 的 token 截断率要等 M1.2.3 跑真实论文索引才知道。
   缓解：M1.2.3 索引脚本里加 token 长度统计 / 截断率打点；
   超过阈值（拍 5%）时升级为 token-aware 切分或调小 max_size。
2. **段落分隔依赖 `\n{2,}`，对 PDF 抽取文本不鲁棒**：
   PDF parser 输出的换行不一定是双换行；
   段落识别失败时 chunker 会把整篇当一段然后硬切，质量下降但不出错。
   缓解：上游 PDF parser 的归一化（双换行规整）是 parser 的责任，本模块不补；
   M1.2.3 的 indexer 在调 chunker 前自行规整。
3. **chunk_id 的 4 位宽并非硬上限**：`f"{idx:04d}"` 是"最少 4 位"，
   `idx >= 10000` 时 Python 会自动扩展到 5 位输出，**不会截断也不会出错**。
   4 位宽的取舍仅为人眼可读 / diff 友好，对常见论文规模（50~200 块）足够。
   缺点：`idx == 9999` 与 `idx == 10000` 的字典序排序会错乱
   （`"9999"` > `"10000"`）。
   缓解：单篇文档触发 5 位时把格式调到 `:06d` 并重建索引；
   M1.2.2 不预先扩位宽。
4. **中文边界回退在公式 / 表格残文中无效**：`backtrack_to_boundary` 找不到
   `。！？；.!?;` 时退回原始窗口位置；切出来的 chunk 头尾观感差但不影响 embedding。
   缓解：上游 PDF parser 的清洗是更合适的层；本模块不补。
5. **base_metadata 标量校验只查一层**：caller 传 `{"k": [1, 2]}` 会被拒，
   但 `{"k": 1}` 之外的复杂类型（如 datetime）会以 TypeError 被拒。
   策略：明确只允许 str / int / float / bool 四种，其他类型 caller 自行序列化（如 ISO 字符串）。
6. **frozen dataclass + 可变 dict metadata**：
   `Chunk.metadata` 是 dict，技术上可被 caller 修改。Python 不强约束。
   缓解：约定 caller 不改 `Chunk.metadata`；如未来真出问题，
   切换 `types.MappingProxyType` 包一层。MVP 不做。

## 9 参考

- 同形先例：M1.2.1 Embedder + ChromaStore（[`../2026-05-05-m1-2-1-embedder-chromastore/spec.md`](../2026-05-05-m1-2-1-embedder-chromastore/spec.md)）
- chromadb metadata 类型限制：<https://docs.trychroma.com/usage-guide#using-where-filters>
- BGE 模型卡片：<https://huggingface.co/BAAI/bge-large-zh-v1.5>
- 父级路标：M1.2 拆分为 3 个 sub-iteration（M1.2.1 骨架 / **M1.2.2 切分器** / M1.2.3 索引脚本 + retriever pipeline）
