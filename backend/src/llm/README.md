# llm/

LLM 客户端抽象层。职责：

- 统一的 `LLMClient` 接口（chat / stream / tool-calling）
- DeepSeek 实现（MVP 默认）
- 未来可替换为 OpenAI / Claude / 本地模型，上层不感知

依据 ADR-003：所有对 LLM 的调用必须经过这里，禁止在业务代码里直接 import openai。
