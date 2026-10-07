# agent/

`runtime.py` 是聊天的有界执行入口；`routing.py` 判断意图，`state.py` 保存当前任务，
`skills.py` 用输入/输出模型包装现有能力。`contracts.py` 定义运行、证据和后续评测契约。

文献问答继续复用 `ChatService`，文件统计继续复用 `file_chat` 与 `model_tools`。
`composition.py` 支持有限语法的“整表极值 + 可能机理”组合：文件数值由程序计算，
机理引用须指向实际提供的片段且原文摘录可核对；部分失败保留成功结果。
原文匹配不代表专业因果结论已经审核。当前没有 ReAct 无限循环或模型语义分类器。
路由、实际工具、结果/错误和耗时写入 SQLite Trace，不记录思维链。

参见 [实施规格](../../../docs/iterations/2026-09-29-agent-harness/spec.md)。
