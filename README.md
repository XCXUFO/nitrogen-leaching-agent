# 农田氮淋失风险决策 AI Agent

> An LLM-based AI Agent for farmland nitrogen leaching risk decision support.
> 中国农业大学 资源与环境专业 硕士毕业设计

## 项目简介

本项目是一个基于大语言模型的智能决策支持系统，面向农田氮素淋失风险管理场景。
系统融合 RAG（检索增强生成）架构与 WHCNS 农田水氮模型仿真能力，为科研人员、
农田管理者与政府决策者提供数据驱动的咨询服务。

## 核心能力

- **学术问答**：基于 90+ 篇中文农业领域论文的知识库检索
- **智能对话**：多轮上下文理解，支持追问与澄清
- **决策支持**：（规划中）调用 WHCNS 模型进行情景仿真
- **可信回答**：所有结论附带文献引用，支持答案验证

## 技术栈

| 层 | 技术 |
|---|---|
| LLM | DeepSeek API |
| Embedding | BGE-large-zh-v1.5 |
| 向量库 | Chroma |
| Agent 框架 | 自研（ReAct + Workflow 双模式） |
| 后端 | Python 3.11 + FastAPI + SQLite |
| 前端 | Next.js 14 + TypeScript + Tailwind + shadcn/ui |
| 部署 | Vercel（前端）+ Railway（后端） |

## 项目结构

```
.
├── backend/        # Python 后端 (FastAPI + Agent + RAG)
├── frontend/       # Next.js 前端
├── eval/           # 评测体系
├── docs/           # 架构与 API 文档
└── .github/        # PR / Issue 模板
```

## 快速开始

详见 [docs/development.md](docs/development.md)（待补充）。

## 项目状态

🚧 **MVP 开发中** — 当前里程碑：M1（基础对话闭环）

## License

MIT
