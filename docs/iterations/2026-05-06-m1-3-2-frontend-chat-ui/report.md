# M1.3.2 Frontend Chat UI Report

## 1. 元信息

| 字段 | 值 |
|---|---|
| 迭代 | M1.3.2 frontend chat UI |
| 日期 | 2026-05-06 |
| 目标 | 把前端从 health 探测页推进到最小单轮 Chat UI |
| 后端依赖 | M1.3.1 `POST /api/chat` |
| 评分状态 | 前端 smoke；不评价 RAG 答案质量 |

> 本迭代只验证前端最小单轮 Chat UI 是否可用，不评价 RAG 专业答案质量。答案质量评估从 M1.4-a mini eval 开始。

## 2. 范围

本轮完成：

- `frontend/src/app/page.tsx` 从 health 探测页改为单轮 chat 页面。
- 新增 `frontend/src/lib/api.ts`，封装 `postChat` / `getHealth` 和 `ApiError`。
- 新增 `frontend/src/lib/types.ts`，手写镜像后端 chat schema。
- 新增 `frontend/src/lib/error-messages.ts`，把后端错误码翻译为中文用户文案。
- 新增 `frontend/src/components/chat/`，包含输入框、消息、引用列表和错误条。
- 新增 `frontend/src/components/debug/health-probe.tsx`，把原 health 探测降级到底部折叠调试区。
- 更新 `frontend/README.md` 和 `.env.local.example`，记录 chat 闭环启动前置条件。

明确不做：

- 不做多轮历史。
- 不做 SSE / 流式输出。
- 不做 Markdown 渲染。
- 不做 citation 点击跳转原文。
- 不引入前端测试框架。
- 不改后端 API。

## 3. 实现说明

页面持有单轮状态：

- `userQuery`: 用户刚提交的问题。
- `assistant`: `loading` / `ok` / `error` 三态。
- 加载超过 3 秒时显示冷启动提示，解释首次响应可能较慢。

API 层集中处理错误：

- 网络错误统一为 `code=network`。
- 后端结构化错误读取 `detail.code`。
- FastAPI 422 校验错误单独翻译。

引用列表默认折叠，展开后显示：

- citation index
- source 文件名
- score，保留三位小数
- snippet 前 100 字

## 4. 验证

| 项 | 命令 / 方式 | 结果 |
|---|---|---|
| lint | `cd frontend && pnpm lint` | 通过 |
| build + TypeScript | `cd frontend && pnpm build` | 通过 |
| npm 依赖 | 查看 `package.json` | 未新增运行时依赖 |
| chat 成功路径 | 浏览器人工 smoke | 可提交问题并显示回答 |
| citation 展示 | 浏览器人工 smoke | 可展开查看引用 |
| health debug | 浏览器人工 smoke | 底部折叠区保留 `/api/health` 探测 |
| 错误态 | 后端错误码 smoke | 能显示中文错误条 |

最近一次本地验证结果：

```text
pnpm lint  passed
pnpm build passed
```

## 5. 已知限制

1. **单轮 UI**
   - 页面只保留当前一轮问答。
   - 多轮历史、会话 id 和本地持久化留到 M2。

2. **纯文本回答**
   - 回答使用 `whitespace-pre-wrap` 渲染。
   - Markdown 语法不会被格式化；`[N]` citation 标记不做可点击处理。

3. **前端 smoke 不等于答案质量**
   - 本轮只证明前端可以消费 `/api/chat`。
   - 专业答案是否准确、引用是否支撑答案，由 M1.4-a 的 mini eval 和 judged.yaml 评价。

4. **后端数据状态随后续迭代变化**
   - M1.3.2 开发时使用 sample 索引完成 smoke。
   - M1.4-a 后主线已切到 8 篇真实 PDF、1348 chunks；这属于后续评测迭代，不改变 M1.3.2 的前端结论。

## 6. 后续

- M1.4-a 已接管真实论文入库和 mini eval。
- M1.4-b 将继续改进 retrieval / reranker。
- M2 再考虑多轮历史、流式输出、Markdown 渲染、citation 点击跳转和前端自动化测试。

## 7. 结论

M1.3.2 可以关闭。前端已从 health 探测页升级为最小单轮 Chat UI，能够提交问题、展示回答、展示 citation、处理常见错误，并保留底部 health 调试入口。

本轮不对 RAG 答案质量作结论；质量基线已在 M1.4-a 另行评估。
