# 说明文档 — Pre-M1 Prep

> **目标读者**：未来翻阅本仓库的研究者、毕设论文写作阶段。
> 本轮是 M1 启动前的轻量整理迭代，性质类似 `2026-04-22-review-corrections`，
> 不引入新能力、不升里程碑、文档主动从简。

| 元信息 | 值 |
|---|---|
| 迭代名 | pre-m1-prep |
| 日期 | 2026-05-04 |
| 涉及 commit | `f03aefb` `237db93` `26d8813` |
| 文档版本 | v1.0 |
| 父里程碑 | M0（延续，非新里程碑） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

---

## 1 本轮的目标与起因

M1 即将开始前对 M0 留下的三类小问题做集中清理：

1. **`__version__` 出口的健壮性**（M0 遗留 #1）：原 `src/__init__.py`
   在 import 期同步打开 `pyproject.toml` 读 `version`，未来若包被
   `uv build` 打包后路径会失效。
2. **`Settings` 路径解析的语义边界**：原配置只把相对路径相对当前
   工作目录解析；从 `backend/` 之外的目录启动会得到错误的数据库
   位置。同时 `sqlite:///:memory:` 的特殊取值会被当成相对路径处理，
   产生类似 `sqlite:////root/.../:memory:` 的怪异结果。
3. **日志初始化无独立模块**：之前 `loguru` 配置散落在 `main.py` 顶部，
   未来 chat / RAG 等长链路要做模块化日志（带 trace_id 等）时，没有
   一个干净的挂载点。

三件事彼此独立，**不构成 M1 的硬前置**，但等到 M1 写代码时再插队
处理会让 M1.1 的叙事变钝（一个迭代同时修 3 类既有问题 + 加 LLM
客户端，不便于论文章节分述）。

故独立成 mini-iteration，先收完再开 M1.1。

## 2 改动清单

| 改动 | 触及文件 | 要点 |
|---|---|---|
| `__version__` 双层加载 | `backend/src/__init__.py` 新增 + `backend/src/api/health.py` + `backend/tests/test_health.py` + `backend/src/main.py` 一处 | 优先 `importlib.metadata.version("nitrogen-leaching-agent-backend")`，失败回落到 `pyproject.toml` 直读，二次失败返回 `"0.0.0"` |
| `Settings` 路径锚定 `BASE_DIR` + `:memory:` 处理 | `backend/src/config.py` + `backend/tests/test_config.py` 新增 | 引入 `BASE_DIR = Path(__file__).resolve().parent.parent`，相对路径解析以 `backend/` 为锚；`sqlite:///:memory:` 短路保留 |
| 日志初始化抽出 | `backend/src/utils/logging.py` 新增 + `backend/tests/test_logging.py` 新增 + `backend/src/main.py` 一处 | `configure_logging(level)` 在 `main.py` import 期调用一次 |

`.codex` 入 gitignore 是 *单独的 chore commit*（`c40da2e`），
不计入本迭代审查范围 — 见 §6 与 review.md §1。

## 3 关键判断

### 3.1 `__version__` 用 importlib.metadata + pyproject 兜底，而不是单一来源

`importlib.metadata.version` 在包被 `uv pip install -e .` 或 `uv build`
后是权威来源；但本项目目前 **没有走 build-system**（见 walking-skeleton
spec §3.1），dev 模式下 `metadata.version` 会抛 `PackageNotFoundError`。
此时 fallback 到读 `pyproject.toml` 是 dev 模式的正确路径。再 fallback
到 `"0.0.0"` 是为了让"以 zip 形式拷出 src/" 这种边缘场景不崩。

```python
def _load_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        pass
    try:
        with PYPROJECT_FILE.open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except FileNotFoundError:
        return "0.0.0"
```

**为什么不直接硬编码 `__version__ = "0.1.0"`**：硬编码会让 pyproject
的 `version` 字段与代码中的常量两边漂移；过了几次发布后铁定会出错。

### 3.2 `BASE_DIR` 锚定，不是相对工作目录

原代码用 `env_file=".env"` 让 pydantic-settings 自己处理；
`SettingsConfigDict` 的 `.env` 解析是相对当前工作目录的。从
`backend/` 启动一切正常，从 `nitrogen-leaching-agent/` 根目录启动
就会失败找不到 `.env`。

修正：

```python
BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
ENV_FILE = BASE_DIR / ".env"
```

同样的锚定也用在 `database_url` 和 `chroma_persist_dir` 的 validator
里。**一致性**：相对路径一律相对 `backend/`，不论谁从哪里启动。

### 3.3 `sqlite:///:memory:` 短路

原 validator 把 `database_url` 任何 `sqlite:///` 开头的相对部分都当
路径解析。`:memory:` 是 SQLite 的内存库特殊取值，必须原样透传。

```python
raw_path = value[len(sqlite_prefix):]
if raw_path == ":memory:":
    return value          # 短路
db_path = Path(raw_path)
if db_path.is_absolute():
    return value
return f"{sqlite_prefix}{(BASE_DIR / db_path).resolve()}"
```

这条改动在 M1.1 当下没有实际触发场景（项目用文件型 SQLite），但
**测试场景** 会用到 `:memory:` 跑隔离 fixture，未来不修就埋雷。

### 3.4 `configure_logging` 抽到 utils

```python
def configure_logging(log_level: str) -> None:
    normalized_level = log_level.upper()
    logger.remove()
    logger.add(sys.stderr, level=normalized_level)
```

签名设计：接收字符串 `log_level` 而不是 `Settings`，避免 `utils/`
依赖 `config.py`（保持目录无环依赖纪律，walking-skeleton spec §3.4）。

## 4 验证方法

```bash
cd backend
uv run pytest                 # 期望 7 passed（health 1 + config 3 + logging 1 + 既有 fastapi.TestClient 1 + 其余）
```

回归点：

- `tests/test_health.py` 改成 `assert body["version"] == __version__`，证明 `__version__` 出口生效
- `tests/test_config.py` 新增 3 测：相对路径 / `:memory:` / 绝对+非 sqlite
- `tests/test_logging.py` 新增 1 测：mock `loguru.logger.{remove,add}` 验证调用

## 5 与 M1.1 的关系

- **本轮是 M1.1 的前置整理**，不是 M1.1 的一部分。
- M1.1 spec.md 的 §8 "偏离与遗留" 表中，"M0 遗留 #1（`__init__.py`
  读 pyproject）" 一项的处理状态由 "不收" 改为 "在 pre-m1-prep 中收掉"。
- M1.1 自身不再触及 `src/__init__.py` / `src/config.py` / `src/utils/`，
  以保持 M1.1 主题纯净。

## 6 偏离与遗留

| M0 遗留项 | 处理 |
|---|---|
| #1 `__init__.py` 读 pyproject | **本轮收掉** — §3.1 |
| #2 Python 版本三处冗余 | 不收，跨基础设施改动放 M2 之后 |
| #3 PR 模板 `pnpm test` 缺脚本 | 不收，等 M1.4 引入前端测试再处理 |
| #4 前端 fetch 抽 lib/api.ts | 不收，等 M1.4 |
| #5 DeepSeek key 启动期校验 | 不收，**M1.1 收**（属本能力的最小责任） |
| #6 api/__init__.py 空文件 | 不收，**M1.3 写 chat 路由时自然解决** |

## 7 度量基线（push 前回填）

| 指标 | 计划 | 实际 |
|---|---|---|
| 后端代码新增（非测试） | ~50 行 | 74 行（`__init__` 23 + `config` +35 + `utils/logging` 9 + `main` +7） |
| 新增单测数 | 4 | 4（test_config 3 + test_logging 1，test_health 改写 1 不计新增） |
| 新增依赖 | 0 | 0 |
| pytest 全套耗时 | < 2s | ~0.8s（5 tests，M1.1 前状态） |
