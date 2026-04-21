# api/

HTTP 路由层。职责：

- 定义 FastAPI 路由、请求 / 响应模型（Pydantic）
- 做参数校验 + 错误处理，不含业务逻辑
- 业务处理委托给 `agent/` / `rag/` / `storage/` 等模块

当前占位端点：
- `GET /api/health` — 健康检查
