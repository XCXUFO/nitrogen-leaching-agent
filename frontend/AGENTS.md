<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## 管理工作台设计

修改 `/evaluation` 页面前阅读 [DESIGN.md](./DESIGN.md)，复用 `workbench.css` 中的共用组件与尺寸。每页只留一个主标题，不增加解释性副标题、装饰标签或重复小标题。保留操作必需的字段名、表头、记录名和状态。
