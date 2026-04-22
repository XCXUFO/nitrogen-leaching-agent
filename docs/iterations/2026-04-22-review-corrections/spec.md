# 说明文档 — Review Corrections

> **目标读者**：未来翻阅本仓库的研究者、本人在毕设论文写作阶段。
> 本轮不是新里程碑，而是对 walking-skeleton 迭代的纠正轮次；
> 本文档沉淀的是 **边界、判断、验证**，不重复已有背景。

| 元信息 | 值 |
|---|---|
| 迭代名 | review-corrections |
| 日期 | 2026-04-22 |
| 涉及 commit | `bf3a271` `e4f1149` |
| 文档版本 | v1.0 |

---

## 1 本轮的目标与起因

walking-skeleton 迭代 push 前的审查过程中，外部评审指出若干问题。
经逐项复核后，确认两类实际缺陷值得立即修复：

1. **文档失真与措辞冲突**
   - `docs/development.md:71` 把 CORS 环境变量路径写成"根目录 .env"，
     与代码实际解析位置（`backend/.env`，由 CWD 决定）不一致
   - `docs/development.md:87` 的 `pnpm build` 速查未标注构建期对
     `fonts.googleapis.com` 的网络依赖
   - `review.md:12` 的 "(HEAD)" 措辞与 "冻结审查基线" 的实际语义冲突
   - `review.md:41-52` 的验证矩阵缺少 `pnpm build` 一项
2. **可复现的构建阻塞**：`next/font/google` 在 `pnpm build` 阶段
   请求 Google Fonts，国内 / CI / 受限代理环境会失败

**为什么独立成一个迭代目录，而不是补在 walking-skeleton 里**：

- 项目约定"每次 push 前必写两份文档"，按 push 触发，非按里程碑触发。
- walking-skeleton 的 `review.md` 和 `spec.md` 明确冻结在 `5ccb990`，
  把 bf3a271 / e4f1149 的内容追加进去会破坏"审查基线"的冻结语义
  （而这正是本轮 §3.1 要强调的原则）。
- 独立目录既满足 push 的成对文档约束，也保留原快照的完整性。

本轮不引入新能力，不升里程碑，仍归属 M0。

## 2 改动清单

| Commit | 类型 | 触及文件 | 要点 |
|---|---|---|---|
| `bf3a271` | `docs(iteration)` | `docs/development.md`、`docs/iterations/2026-04-21-walking-skeleton/review.md` | 4 处文档修正：CORS 路径、build 网络注记、"(HEAD)" → "(审查基线)"、补 `pnpm build` 验证位（未复核） |
| `e4f1149` | `fix(web)` | `frontend/package.json`、`frontend/pnpm-lock.yaml`、`frontend/src/app/layout.tsx`、`docs/iterations/2026-04-21-walking-skeleton/review.md` | 切 `next/font/google` → `geist` 包；回填 walking-skeleton 验证位为通过 |

合计 **5 files changed, +21 / -16**。

## 3 关键判断与理由

> **总原则**：验证矩阵是活的，快照内容是冻的。
> 以下三条判断都是这条总原则在不同维度上的具体化。

### 3.1 冻结边界：为什么 `review.md:49` 可回填、`review.md:73` 不可回填

walking-skeleton 的 `review.md` 在 `5ccb990` 后原则上冻结。但
`review.md` 不是纯描述文档，它带"验证矩阵"一节。**验证矩阵的
每一格承担"该项是否被验证过"的状态，是活的**；其余内容——依赖清单、
设计结论、原始统计（commit 数 / files / lines）——是冻的。元信息中的
审查语义措辞属于另一类允许跨快照的纠偏，见 §3.2。

- `review.md:49` 的 "前端生产构建" 行，原值是 `[ ] 本轮未复核`。
  本轮的 `fix(web)` 修复直接消除了该项不可验证的阻塞条件，并跑通
  `pnpm build`。**这一格的更新本身就是"该项被验证"这件事的发生**，
  不是对快照内容的追溯修改。
- `review.md:73` 的依赖清单列出 walking-skeleton 引入的 Node 依赖。
  `geist` 是本轮新增，不属于 walking-skeleton 的依赖面。
  把它回填进那张表会让人误以为 `5ccb990` 时就有 `geist`，破坏快照。

这条边界在毕设方法论中可作为"文档冻结与验证活性的分离"实例。

### 3.2 审查语义：为什么 `(审查基线)` 比 `(HEAD)` 准确

`review.md:12` 原写 "`5ccb990` (HEAD)"。**"HEAD" 在 git 里是"当前
指针"，随新 commit 移动**；而审查文档的目的恰恰是把某一范围钉死
便于复核，两种语义直接冲突。改成 `(审查基线)` 后，即便后续 HEAD
前进，文档仍自洽指向最初被审计的那个 SHA。

这条还能预防一类自动化失误：若机审字段按字面 "HEAD" 去跑
`git diff`，会随时间漂移；按固定 SHA（我们的 `commits_to` 机审字段）
去跑则稳定可复现。

### 3.3 字体方案取舍：为什么选 `geist` 包而不是其它三种

备选对比：

| 方案 | 离线构建 | 视觉一致 | 仓库整洁 | 维护成本 |
|---|---|---|---|---|
| `next/font/google`（原方案） | ✗ | ✓ | ✓ | 低 |
| `next/font/local`（本地 woff2） | ✓ | ✓ | ✗（字体文件入仓） | 中 |
| 系统字体 `system-ui` | ✓ | ✗ | ✓ | 低 |
| **`geist` npm 包** | ✓ | ✓ | ✓ | 低 |

`geist` 由 Vercel 官方发布，内含 Geist Sans / Mono 的 woff2，通过
npm 依赖引入；构建期和运行期都不联网，也不把字体文件写入 git 仓库。
四个维度都占优。

对 Next 15 及以上版本无需额外 `transpilePackages` 配置；本项目
`next@16.2.4`，不存在版本阻塞。

## 4 验证方法

```bash
cd frontend
pnpm exec tsc --noEmit     # 类型检查
pnpm lint                  # ESLint
pnpm build                 # 生产构建：✓ Compiled successfully in 9.5s，无外联
```

后端回归（确认前端改动未误伤后端）：

```bash
cd backend && uv run pytest
# 1 passed in 0.75s
```

结构化证据矩阵见 [`review.md`](./review.md) §4。

## 5 与 walking-skeleton 的关系

- **本轮是纠正轮次**，不是新里程碑。仍归属 M0。
- **原则上不追溯修改已冻结内容**。允许跨快照回写的仅两类：
  审查语义纠偏（§3.2）与验证矩阵状态更新（§3.1）；
  依赖清单 / 设计结论 / 原始统计一律不回填。
- 将来若要回看 walking-skeleton 的设计决策、依赖面、度量基线，
  读 `docs/iterations/2026-04-21-walking-skeleton/`；
  若要回看"为什么切了字体 / 为什么改了这 4 处文档"，读本目录。

## 6 偏离与遗留

- `geist` 依赖不出现在 walking-skeleton 的依赖清单（`review.md:73`）中，
  **这是主动选择，不是疏漏**。依据见 §3.1。
- 本轮未新增测试。`fix(web)` 的正确性由 `pnpm build` 成功佐证。
  若未来需要更硬的回归防护，可把 `pnpm build` 作为 GitHub Actions
  的门槛之一（已列入 `review.md` §10 待办）。
