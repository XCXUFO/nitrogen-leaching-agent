# 审查文档 — Walking Skeleton

> Reviewer 请逐项勾选。带 `[ ]` 的项需亲自核验后改为 `[x]`，
> 不通过项请在条目下注明原因，并在 "审查结论" 处选择"驳回"。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代代号 | walking-skeleton |
| 日期 | 2026-04-21 |
| 起止 commit | `46c10d8` (排除) → `5ccb990` (HEAD) |
| 包含 commit 数 | 4 |
| 总变更 | 55 files, +8003 lines, -0 lines |
| 目标里程碑 | M0（基础设施就绪），先于 M1 |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 变更范围清单

- [x] **infra**：`.gitignore` / `LICENSE` / `.env.example` / GitHub 模板
- [x] **backend**：FastAPI 入口、health 接口、配置、模块占位、测试
- [x] **web**：Next.js + shadcn/ui 页面、按钮调后端 health
- [x] **docs**：`docs/development.md`
- [ ] 未触及：`agent/`、`rag/`、`llm/`、`storage/`、`simulator/` 内业务实现（按规范应保持空）— **审查者请抽查 backend/src/<module>/__init__.py 是否为空**

## 3 commit 规范清单

逐条核对 `git log --oneline 46c10d8..HEAD`：

- [x] `chore(infra): add gitignore, license, env template and github templates`
- [x] `feat(backend): scaffold FastAPI with health endpoint`
- [x] `feat(web): scaffold Next.js with shadcn/ui and backend health check`
- [x] `docs: add local development guide`
- [x] 全部符合 [`docs/COMMIT_CONVENTION.md`](../../COMMIT_CONVENTION.md) 的 `<type>(<scope>): <subject>` 格式
- [x] 单个 commit 只做一件事（无跨模块混提）
- [x] commit 信息描述了 "为什么"，不是仅 "做了什么"

## 4 验证证据清单

| 项 | 命令 / 操作 | 期望结果 | 实际结果 | 通过 |
|---|---|---|---|---|
| 后端依赖安装 | `cd backend && uv sync` | 退出码 0；下载 Python 3.11 + 29 包 | ✓ Installed 29 packages in 40ms | [x] |
| 后端单元测试 | `cd backend && uv run pytest` | 1 passed, 0 warnings | ✓ 1 passed in 0.49s | [x] |
| 后端 health 接口 | `curl --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health` | HTTP 200 + 指定 JSON | ✓ HTTP 200 `{"status":"ok","service":"nitrogen-leaching-agent-backend","version":"0.1.0"}` | [x] |
| 前端依赖安装 | `cd frontend && pnpm install` | 退出码 0 | ✓ Done in 4m 6.3s | [x] |
| 前端类型检查 | `pnpm exec tsc --noEmit` | 无输出 | ✓ 无输出 | [x] |
| 前端 lint | `pnpm lint` | 无错误 | ✓ 无错误 | [x] |
| 前端 dev server | `pnpm dev` | Ready in <5s，3000 端口监听 | ✓ Ready in 862ms | [x] |
| 前端 HTML 渲染 | `curl http://127.0.0.1:3000` | HTML 含 "氮淋失风险决策 Agent — Hello World" + "测试后端连接" | ✓ 含上述字符串 | [x] |
| 端到端按钮调用 | 浏览器打开 :3000 → 点按钮 | 页面显示后端返回的 JSON | ✓ 用户已亲测，返回符合预期 JSON | [x] |
| CORS 通畅 | 跨 :3000 → :8000 fetch | 无 CORS 阻断 | ✓ 实测通过 | [x] |

## 5 依赖变更清单

### Python（新增 5 个直接依赖）

- [x] `fastapi>=0.115.0` — Web 框架，主线选型
- [x] `uvicorn[standard]>=0.32.0` — ASGI 服务器
- [x] `pydantic-settings>=2.6.0` — 环境变量加载
- [x] `loguru>=0.7.2` — 结构化日志
- [x] `python-dotenv>=1.0.1` — `.env` 文件读取
- [x] dev: `pytest>=8.3.0`, `httpx>=0.27.0`
- [x] 依赖锁文件 `backend/uv.lock` 已提交
- [x] 无废弃 / 无安全告警包（人工抽查）

### Node（脚手架默认 + shadcn 引入）

- [x] `next 16.2.4`、`react 19.2.4`、`react-dom 19.2.4`
- [x] `tailwindcss 4`（PostCSS 插件 `@tailwindcss/postcss`）
- [x] `@base-ui/react`（shadcn nova preset 默认）
- [x] 锁文件 `frontend/pnpm-lock.yaml` 已提交
- [x] **审查者注意**：Next 16 / React 19 是 Claude 训练数据之后的版本，未来改前端代码请先查 `frontend/node_modules/next/dist/docs/`

## 6 兼容性 / 破坏性变更清单

- [x] 本次为初始化迭代，**无下游兼容义务**
- [x] 不存在公开 API 改动
- [x] 不存在数据库 schema 改动（尚未引入 SQLite）
- [x] 不存在已上线服务依赖此版本

## 7 安全清单

- [x] `.gitignore` 已覆盖 `.env`、`*.pem`、`*.key`、`*.db`、`*.sqlite*`、`models/`、`chroma_db/`
- [x] `git status --ignored` 抽查：`.env` 未被跟踪，`.env.example` / `.env.local.example` 已跟踪
- [x] 无任何真实 API Key / token / 密码出现在代码或提交历史中（`git log -p | grep -i "sk-"` 应无命中）
- [x] CORS 当前仅允许 `http://localhost:3000`，未开放通配符 `*`
- [x] 无未授权的网络外发（pyproject 与 package.json 均无可疑依赖）
- [x] 后端默认绑定来自 settings，不硬编码生产配置

## 8 文档清单

- [x] 根目录 `README.md` 已存在，描述项目愿景
- [x] `docs/ARCHITECTURE.md` 含 ADR-001 ~ ADR-006，本次未新增 ADR
- [x] `docs/COMMIT_CONVENTION.md` 已存在
- [x] `docs/development.md` 本次新增，覆盖前后端启动
- [x] `backend/README.md` 描述模块布局
- [x] `frontend/README.md` 描述前端栈与 shadcn 配置
- [x] 各占位模块均含 `README.md` 说明职责
- [x] 本审查文档与说明文档（`spec.md`）在同目录下

## 9 风险与回滚

- [x] **风险**：Next 16 / shadcn 新版 CLI 与训练数据出入 → 缓解：项目自带 `frontend/AGENTS.md` + 本次记忆文件提醒下次必查官方 docs
- [x] **风险**：本机代理（樱花猫 7897 端口）会拦 localhost → 缓解：`docs/development.md` 与说明文档均已记录绕行方法
- [x] **回滚方案**：`git reset --hard 46c10d8`（推送前可丢弃）；推送后 `git revert dd7d4ad..5ccb990`

## 10 待办（不阻塞合并）

- [ ] 配 GitHub Actions CI（pytest + tsc + lint）— 排入 M1 之前
- [ ] 引入 ruff / mypy（后端）与 prettier（前端）的 pre-commit 钩子
- [ ] `frontend/.env.local.example` 是否需要在 `.env.example` 主清单里交叉引用

## 11 审查结论

- [ ] **通过**（reviewer 签名 + 日期：__________ / __________）
- [ ] **驳回**，原因：__________
- [ ] **有条件通过**，需在 push 后补做：__________

---

**机审字段**（供未来自动化解析；勿手改键名）：

```yaml
iteration: 2026-04-21-walking-skeleton
commits_from: 46c10d8
commits_to: 5ccb990
commit_count: 4
files_changed: 55
lines_added: 8003
lines_removed: 0
tests_passed: 1
tests_failed: 0
breaking: false
new_runtime_deps_python: 5
new_runtime_deps_node: 3
secrets_in_repo: false
```
