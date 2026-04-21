# Git 提交规范

本项目采用 [Conventional Commits](https://www.conventionalcommits.org/) 规范。

## 提交格式

```
<type>(<scope>): <subject>

<body>  (可选)

<footer>  (可选)
```

## Type 类型

| Type | 含义 |
|---|---|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档变更 |
| `style` | 代码格式（不影响逻辑） |
| `refactor` | 重构（不增功能、不修 bug） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建系统、依赖变更 |
| `ci` | CI 配置 |
| `chore` | 杂项 |
| `revert` | 回滚提交 |

## Scope 范围（建议）

`agent` / `rag` / `llm` / `api` / `web` / `eval` / `simulator` / `infra` / `docs`

## 示例

```
feat(rag): add MMR retrieval strategy for diverse results
fix(agent): prevent infinite loop when tool returns error
docs(architecture): add ADR-007 for caching layer
refactor(llm): extract DeepSeek client into LLMClient abstraction
chore(deps): bump fastapi to 0.115.0
```

## 分支规范

- `main`：稳定可部署分支，受保护
- `dev`：日常开发基线
- `feature/<short-name>`：单个功能分支
- `fix/<issue-id>`：bug 修复分支

## 工作流程

1. 从 `dev` 拉 `feature/xxx` 分支开发
2. 完成后 PR 合并回 `dev`
3. 里程碑达成时 `dev` → `main`，打 tag（`v0.1.0`）

## Commit 频率

- 每完成一个独立小功能就 commit（不要攒大 commit）
- WIP 提交可用 `chore: wip` 但 push 前需 squash
