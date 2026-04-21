# agent/

Agent 编排层。职责：

- ReAct 循环（思考 → 选工具 → 观察 → 再思考）
- Workflow 模式（确定性多步流程）
- 工具注册表、工具调用解析
- 与 `llm/` 对接生成决策，与 `rag/`、`simulator/` 对接作为工具

依据 ADR-005：不使用 LangChain，目标保持核心循环 < 200 行。
