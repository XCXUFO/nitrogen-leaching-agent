# 审查文档 — M1.1 LLM 客户端骨架

> Reviewer 请逐项勾选。本轮是 M1 迭代序列的第 1 个 sub-iteration，
> 引入 LLM 抽象与 DeepSeek 实现，是 M1.2~M1.4 的依赖前置。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代代号 | m1-1-llm-client |
| 日期 | 2026-05-04 |
| 起止 commit | `3a61161` (排除) → `5da6a3d` (审查基线，含复审 fix) |
| 包含 commit 数 | 4（feat llm + feat backend + test infra + 复审 fix），docs 自身不计入 |
| 目标里程碑 | M1（基础对话闭环，第一步） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 变更范围清单

- [x] **llm**：`backend/src/llm/{base,deepseek,__init__}.py` 新增 — `LLMClient` ABC + `DeepSeekClient` 实现 + 公开导出
- [x] **backend**：`backend/src/main.py` lifespan 加 `DEEPSEEK_API_KEY` fail-fast 校验 + 启动日志加 `model` 字段
- [x] **tests**：`backend/tests/conftest.py` 注入测试哨兵 key + 清空代理环境变量
- [x] **tests**：`backend/tests/test_llm_base.py` 新增 — 契约测试（ABC + role 校验 + Fake 客户端）
- [x] **tests**：`backend/tests/test_llm_deepseek.py` 新增 — mock AsyncOpenAI 验证三类行为
- [x] **deps**：`backend/pyproject.toml` + `backend/uv.lock` — 加 `openai>=1.50,<2.0` + `pytest-asyncio>=0.24` + `asyncio_mode = "strict"`
- [x] **docs(iteration)**：本目录 `spec.md` + `review.md`
- [x] 未触及：前端、`agent/` / `rag/` / `storage/` / `simulator/` / `api/`

## 3 commit 规范清单

实际 commit（本迭代审查范围 `3a61161..5da6a3d`）：

- [x] `838f59b feat(llm): add LLMClient ABC with DeepSeek implementation`
- [x] `df61d29 feat(backend): fail-fast on missing DEEPSEEK_API_KEY at startup`
- [x] `6c9b2d5 test(llm): add conftest sentinel and proxy env cleanup`
- [x] `5da6a3d fix(test): preserve real env when RUN_LIVE_LLM is set` — 复审反馈触发的回归修复（详见 §11.1）

中间用 `23fa37d docs(iteration): add 2026-05-04 m1-1-llm-client spec and review` 落定首版文档，本次同 commit 的 docs 增量再封口一次（按既有惯例 docs 不计入审查范围）。

- [x] 全部符合 `<type>(<scope>): <subject>`
- [x] 单 commit 单意图：feat 与 test 拆开，避免主 feat commit 的 diff 被测试基础设施稀释；fix 与 docs 同样独立
- [x] **已知不可避免**：commit 838f59b 在 isolation 下 `pytest` 会失败（pytest-asyncio 尚未安装），但作为整体审查单元在 6c9b2d5 处恢复绿。本约束已记入本节备注

## 4 验证证据清单

| 项 | 命令 | 期望 | 实际 | 通过 |
|---|---|---|---|---|
| 依赖安装 | `cd backend && uv sync` | 退出码 0；新增 6 包（openai + 4 间接 + pytest-asyncio） | ✓ Resolved 38 packages | [x] |
| 后端单测 | `cd backend && uv run pytest` | 11 passed in < 2s | 11 passed in 1.30s | [x] |
| 启动校验：缺 key | `unset DEEPSEEK_API_KEY && uv run uvicorn src.main:app` | `RuntimeError: DEEPSEEK_API_KEY 未配置` | RuntimeError 命中 | [x] |
| 启动校验：有 key | `DEEPSEEK_API_KEY=test uv run uvicorn src.main:app` | 正常启动；日志含 `model=deepseek-chat` | 启动并日志格式正确 | [x] |
| LLMClient 抽象强制 | 实例化 `LLMClient()` 应抛 `TypeError` | `TypeError` | 命中 | [x] |
| `ChatMessage` role 校验 | 传非法 role 应抛 `ValidationError` | `ValueError` 子类 | 命中 | [x] |
| `chat()` 透传超参 | mock AsyncOpenAI，校验 `model/messages/temperature/max_tokens` | 全部正确传入 | 命中 | [x] |
| `content=None` 兜底 | DeepSeek 返回 `content=None` | `ChatResult.content == ""` | 命中 | [x] |
| `max_tokens=None` 不入参 | 不传 max_tokens 时 SDK kwargs 不含该键 | `'max_tokens' not in kwargs` | 命中 | [x] |
| 实调 DeepSeek（可选）| `RUN_LIVE_LLM=1 uv run pytest tests/test_llm_live.py` | 默认跳过 | N/A — 未引入 live test 文件 | [-] |
| `RUN_LIVE_LLM` 透传校验 | `RUN_LIVE_LLM=1 DEEPSEEK_API_KEY=real-key python -c "import tests.conftest, os; print(os.environ['DEEPSEEK_API_KEY'])"` | 输出 `real-key`（非哨兵） | 输出 `real-key` | [x] |

## 5 依赖变更清单

### Python（新增 2 个直接依赖 + 4 个间接）

- [x] `openai>=1.50,<2.0` — 当前解析到 `1.109.1`
- [x] `pytest-asyncio>=0.24`（dev）— 当前解析到 `1.3.0`
- [x] 间接：`distro 1.9.0` / `jiter 0.14.0` / `sniffio 1.3.1` / `tqdm 4.67.3`
- [x] 锁文件 `backend/uv.lock` 已更新
- [x] 无废弃 / 无安全告警包（人工抽查）

### Node

- [x] 无变更

## 6 兼容性 / 破坏性变更

- [x] 无公开 API 改动（`/api/health` 不变）
- [x] 无数据库 schema 改动
- [x] **运行行为变化**：未配 `DEEPSEEK_API_KEY` 时启动会 fail-fast — 这是预期改动；CI 与本地需在 `.env` 或环境变量配上才能起服
- [x] `tests/conftest.py` 注入哨兵 key — 测试中 settings 始终能拿到非空 key；保持既有测试不退化

## 7 安全清单

- [x] 哨兵 key `"test-key-not-real"` 仅出现在 `conftest.py`，明显非真实 key
- [x] `git log -p | grep -iE "sk-[a-zA-Z0-9]{20,}"` 应无命中
- [x] `openai` 包来自 OpenAI 官方发布，固定到主版本范围
- [x] CORS 配置未变
- [x] 无新增外发请求；测试默认不触网

## 8 文档清单

- [x] 本审查文档与说明文档（`spec.md`）在同目录下
- [x] `spec.md` 已沉淀关键设计决策（async-only / openai SDK / pydantic / 透传异常 / 启动期校验 / ABC 选型）
- [x] M0 遗留 #5 在本迭代收掉，并在 spec §8.2 标注

## 9 风险与回滚

- [x] **风险**：openai SDK 主版本升级会破坏；锁定 `>=1.50,<2.0`
- [x] **风险**：DeepSeek 内容审核拦截时返回空 content；当前 `or ""` 兜底，上层（M1.3）决定是否加用户提示
- [x] **风险**：测试期清空代理环境变量；若开发机依赖代理跑测试中的外部请求，需重新审视 — 当前测试不触网
- [x] **回滚**：4 个 commit 互相独立，可单独 revert；deps commit（feat llm）revert 后需手动 `uv sync` 清理 .venv

## 10 待办（不阻塞合并）

- [ ] M1.2 之前补 `RUN_LIVE_LLM=1` 守门的实调 smoke 测，确认对真实 DeepSeek 的请求形态正确
- ~~CI 加 `DEEPSEEK_API_KEY=ci-stub`~~ 已无需：`conftest.py` 在 import 期顶层注入哨兵 key，CI `uv run pytest` 直接通过 fail-fast 校验，无需 workflow 额外配置（详见 spec §4.4）

## 11 审查结论

### 11.1 复审反馈与处置

首版（commits_to=`6c9b2d5`）push 前的代码审查发现：

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| 1 | `backend/tests/conftest.py:5` | 无条件 `os.environ["DEEPSEEK_API_KEY"] = "test-key-not-real"` 会覆盖调用方传入的真实 key，堵死 spec §5 规划的 `RUN_LIVE_LLM=1` live smoke 路径（永远 401） | commit `5da6a3d`：用 `if not os.environ.get("RUN_LIVE_LLM"):` 包住覆盖逻辑；mocked 模式行为不变，live 模式真实 key 与代理透传 |
| 2 | `review.md` §10 第 2 条 TODO | 文案"CI 加 `DEEPSEEK_API_KEY=ci-stub`"在 conftest 顶层注哨兵后已无意义，会误导后续维护者以为 CI 还有未收尾配置 | 本次文档修订划掉该 TODO，改为说明 conftest 已覆盖（详见同节） |

11 passed 测试套件在修复前后均绿，本次修复不引入新行为，仅修正"过渡期 bug"。

### 11.2 结论

- [ ] **通过**（reviewer 签名 + 日期：__________ / __________）
- [ ] **驳回**，原因：__________
- [ ] **有条件通过**，需在 push 后补做：__________

---

**机审字段**：

```yaml
iteration: 2026-05-04-m1-1-llm-client
commits_from: 3a61161
commits_to: 5da6a3d
commit_count: 4
files_changed: 9
lines_added: 352
lines_removed: 1
tests_passed: 11
tests_failed: 0
breaking: false
new_runtime_deps_python: 1
new_runtime_deps_node: 0
new_dev_deps_python: 1
secrets_in_repo: false
parent_iteration: 2026-05-04-pre-m1-prep
```
