# 审查文档 — Pre-M1 Prep

> Reviewer 请逐项勾选。本轮是 M0 范畴的轻量纠正迭代，不引入新能力，
> 文档体量从简，与 `2026-04-22-review-corrections` 同级。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代代号 | pre-m1-prep |
| 日期 | 2026-05-04 |
| 起止 commit | `c40da2e` (排除) → `26d8813` (审查基线) |
| 包含 commit 数 | 3（3 refactor，chore .codex 独立于本迭代之外）|
| 目标里程碑 | M0（延续，非新里程碑） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 变更范围清单

- [x] **backend**：`src/__init__.py` 改造为 `_load_version()` 双层加载
- [x] **backend**：`src/config.py` 引入 `BASE_DIR` 锚定 + `:memory:` 短路
- [x] **backend**：`src/utils/logging.py` 抽 `configure_logging` 工具
- [x] **tests**：`tests/test_config.py` / `tests/test_logging.py` 新增；`tests/test_health.py` 改用 `__version__`
- [x] 未触及：前端、`agent/` / `rag/` / `llm/` / `storage/` / `simulator/`、CI、文档（除本目录）

## 3 commit 规范清单

实际 commit（本迭代审查范围 `c40da2e..26d8813`）：

- [x] `f03aefb refactor(backend): derive __version__ from importlib.metadata`
- [x] `237db93 refactor(backend): anchor Settings paths to BASE_DIR with memory url support`
- [x] `26d8813 refactor(backend): extract loguru configure_logging helper`

随后用 `docs(iteration): add 2026-05-04 pre-m1-prep spec and review` 落定本目录文档（按既有惯例不计入迭代审查范围）。

- [x] 全部符合 `<type>(<scope>): <subject>`，单 commit 单意图

## 4 验证证据清单

| 项 | 命令 | 期望 | 实际 | 通过 |
|---|---|---|---|---|
| 后端单测 | `cd backend && uv run pytest` | 5 passed（health 1 + config 3 + logging 1） | 5 passed in ~0.8s（M1.1 之前的状态）| [x] |
| 后端 import 健康 | `uv run python -c 'from src import __version__; print(__version__)'` | 输出 `0.1.0` | `0.1.0` | [x] |
| 健康端点版本号 | `curl --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health` | `version` 字段为 `0.1.0` | 字段为 `0.1.0` | [x] |

## 5 依赖变更

- [x] 无新增 Python 依赖
- [x] 无新增 Node 依赖
- [x] uv.lock 不变化

## 6 兼容性 / 破坏性

- [x] 公开 API（`/api/health` 响应）字段名未变；`version` 值仍为 `"0.1.0"`，由 `__version__` 动态出口
- [x] `Settings` 字段名与默认值未变；只是相对路径解析锚点更明确
- [x] 无数据库 schema 改动
- [x] 既有 walking-skeleton 验证矩阵未退化

## 7 安全清单

- [x] 无新增外发请求
- [x] 无密钥 / token 出现在改动中
- [x] CORS 配置未变

## 8 文档清单

- [x] 本审查文档与说明文档（`spec.md`）在同目录下
- [x] 本轮明确定位为 M0 纠正轮，不升里程碑
- [x] 与 walking-skeleton / review-corrections 的差异已在 spec §5 说明

## 9 风险与回滚

- [x] **风险**：`importlib.metadata.version` 在 dev 模式下抛 `PackageNotFoundError` 是预期行为，回退到 pyproject 直读 — 已被 `_load_version()` 内部消化
- [x] **回滚**：4 个 commit 互相独立，可单独 `git revert <sha>`

## 10 审查结论

- [ ] **通过**（reviewer 签名 + 日期：__________ / __________）
- [ ] **驳回**，原因：__________
- [ ] **有条件通过**，需在 push 后补做：__________

---

**机审字段**：

```yaml
iteration: 2026-05-04-pre-m1-prep
commits_from: c40da2e
commits_to: 26d8813
commit_count: 3
files_changed: 8
lines_added: 123
lines_removed: 4
tests_passed: 5
tests_failed: 0
breaking: false
new_runtime_deps_python: 0
new_runtime_deps_node: 0
secrets_in_repo: false
parent_iteration: 2026-04-22-review-corrections
```
