# 审查文档 — Review Corrections

> Reviewer 请逐项勾选。带 `[ ]` 的项需亲自核验后改为 `[x]`，
> 不通过项请在条目下注明原因，并在 "审查结论" 处选择"驳回"。

## 1 元信息

| 字段 | 值 |
|---|---|
| 迭代代号 | review-corrections |
| 日期 | 2026-04-22 |
| 起止 commit | `989aa05` (排除) → `e4f1149` (审查基线) |
| 包含 commit 数 | 2 |
| 总变更 | 5 files, +21 lines, -16 lines |
| 目标里程碑 | M0（延续 walking-skeleton，非新里程碑） |
| 责任 LLM | Claude Opus 4.7 (claude-opus-4-7) |
| 责任人 | XCXUFO |

## 2 变更范围清单

- [x] **docs**：`docs/development.md`（CORS env 路径修正、build 网络依赖注记）
- [x] **docs(iteration) — 跨快照修改**：`docs/iterations/2026-04-21-walking-skeleton/review.md`
      （限于两类：§1 审查基线措辞纠偏 + §4 验证矩阵状态更新；未动依赖清单 / 设计结论 / 原始统计（commit 数 / files / lines）。依据见 `spec.md` §3.1 与 §3.2）
- [x] **web**：`frontend/src/app/layout.tsx`（`next/font/google` → `geist/font/*`）
- [x] **web-deps**：`frontend/package.json`、`frontend/pnpm-lock.yaml`（新增 `geist ^1.7.0`）
- [x] 未触及：后端代码、walking-skeleton `spec.md`、其它前端页面

## 3 commit 规范清单

逐条核对 `git log --oneline 989aa05..e4f1149`：

- [x] `docs(iteration): correct review framing and dev guide env path`
- [x] `fix(web): replace Google font loader with packaged Geist fonts`
- [x] 全部符合 [`docs/COMMIT_CONVENTION.md`](../../COMMIT_CONVENTION.md) 的 `<type>(<scope>): <subject>` 格式
- [x] 单个 commit 只做一件事（文档修正 / 代码修复）
- [x] commit 信息描述了 "为什么"，不是仅 "做了什么"

## 4 验证证据清单

| 项 | 命令 / 操作 | 期望结果 | 实际结果 | 通过 |
|---|---|---|---|---|
| 前端类型检查 | `cd frontend && pnpm exec tsc --noEmit` | 无输出 | ✓ 无输出 | [x] |
| 前端 lint | `cd frontend && pnpm lint` | 无错误 | ✓ 无错误 | [x] |
| 前端生产构建 | `cd frontend && pnpm build` | 退出码 0，无外联 | ✓ Compiled successfully in 9.5s | [x] |
| 后端回归 | `cd backend && uv run pytest` | 1 passed | ✓ 1 passed in 0.75s | [x] |
| walking-skeleton 验证矩阵同步 | `docs/iterations/2026-04-21-walking-skeleton/review.md:49` | 标 `[x]`，结果格反映 geist 切换 | ✓ 已回填，未动该文件其它行 | [x] |
| 文档路径一致性 | `grep -rn "根目录.*\.env" docs/` | 无命中 | ✓ 无命中（仅剩"根目录 README.md"，语境不同） | [x] |

## 5 依赖变更清单

### Node（新增 1 个直接依赖）

- [x] `geist ^1.7.0` — Vercel 官方字体包，消除 `next/font/google` 构建期外联
- [x] 锁文件 `frontend/pnpm-lock.yaml` 已更新
- [x] 官方来源：<https://www.npmjs.com/package/geist>；Next 15+ 无需 `transpilePackages`

### Python

- [x] 无变更

## 6 兼容性 / 破坏性变更清单

- [x] 无公开 API 改动
- [x] 无数据库 schema 改动
- [x] 视觉表现：Geist Sans / Mono 字体与原方案相同，无 UI 回归（CSS 变量名未变）
- [x] walking-skeleton 既有验证点未因本轮退化（后端 pytest / 前端 tsc / lint 均复核通过）

## 7 安全清单

- [x] `geist` 包为 Vercel 官方发布，`package.json` 固定到 `^1.7.0`
- [x] **消除** 了对 `fonts.googleapis.com` 的构建期请求（负向变更）
- [x] 无新增外发请求
- [x] 无任何真实 API Key / token 出现在代码或提交历史中
- [x] CORS 配置未变

## 8 文档清单

- [x] 本审查文档 `review.md` 与说明文档 `spec.md` 在同目录下
- [x] `spec.md` 已沉淀本轮 3 项关键判断（冻结边界 / 审查语义 / 字体方案取舍）
- [x] walking-skeleton 目录未被追溯修改（仅 §1 审查基线措辞 + §4 验证矩阵第 49 行更新，已在 §2 声明）

## 9 风险与回滚

- [x] **风险**：`geist` 包未来升级可能改动 export 名 → 缓解：当前锁定 `^1.7.0`，升级时读 release notes
- [x] **回滚方案**：`git revert e4f1149 bf3a271`（按顺序）；两个 commit 互相独立，单独回滚也安全

## 10 待办（不阻塞合并）

- [ ] 配 GitHub Actions CI 时把 `cd frontend && pnpm build` 作为门槛 —
      本轮已证明 build 是有效的回归防线（静态检查和 dev server 都无法暴露 Google Fonts 网络依赖）

## 11 审查结论

- [ ] **通过**（reviewer 签名 + 日期：__________ / __________）
- [ ] **驳回**，原因：__________
- [ ] **有条件通过**，需在 push 后补做：__________

---

**机审字段**（供未来自动化解析；勿手改键名）：

```yaml
iteration: 2026-04-22-review-corrections
commits_from: 989aa05
commits_to: e4f1149
commit_count: 2
files_changed: 5
lines_added: 21
lines_removed: 16
tests_passed: 1
tests_failed: 0
breaking: false
new_runtime_deps_python: 0
new_runtime_deps_node: 1
secrets_in_repo: false
parent_iteration: 2026-04-21-walking-skeleton
```
