# 项目工具能力盘点归档

归档日期：2026-10-16。

## 记录范围与用途

本记录保存当前项目的工具、应用内 Skill、MCP 接入情况及配套工程能力，作为后续优化讨论和版本对比的基线。

- 依据：当前本地工作区源码，包括尚未提交和未跟踪的实现。
- 参考 HEAD：`873d1897ee9f7e75fc1e4cad1c13cc4fae0eb5fc`。该提交号不包含当前工作区的全部能力，不能单独用于复现本记录。
- 盘点方式：静态阅读注册表、运行时、API、底层工具、脚本及相关迭代文档；本次没有重跑功能测试、真实模型请求或线上验收。
- “已实现”仅表示源码存在并接入相应流程，不表示当前部署已更新、依赖已配置或专业效果已审核。
- 用户后续有优化意向；本次只归档，下面的优化候选尚未确定实施范围与顺序。

## 1. 总体结构

当前核心调用关系为：

```text
聊天请求 /api/chat
  → AgentRuntime：会话状态、规则路由、有界执行
  → SkillRegistry：输入输出校验、能力调用
  → 文献问答 / 案例问答 / 文件处理 / 澄清与引导
  → 回答、引用、文件证据、SQLite 运行轨迹
```

工作台中的资料维护、AI 解析、打标、批处理与评测主要通过各自 FastAPI 接口执行，并未全部注册为聊天 Skill。

## 2. 已注册的 7 个应用内 Skill

注册依据：[skills.py](../../../backend/src/agent/skills.py)、[contracts.py](../../../backend/src/agent/contracts.py)。

| Skill | 当前能力 | 依赖与边界 |
|---|---|---|
| `knowledge_search` | 本地文献检索、带引用问答；结合当前会话文档回答；提炼有原文支持的可能机理 | 当前注册入口要求可用的 ChatService，其初始化依赖 RAG 与 LLM；不提供联网搜索 |
| `case_reference` | 根据问题选择相关案例与措施，说明场景差异，返回结构化来源；无匹配时记录需求缺口 | 从已保存、已开放、未删除的案例读取材料，由 LLM 判断相关性；小规模材料整体提供给模型，未使用案例向量检索 |
| `case_explanation` | 通俗解释指定案例、措施或粘贴文本；比较多个案例并支持追问 | 依赖 LLM；直接解释粘贴文本不要求先保存到案例库 |
| `file_inspector` | 检查附件有效性，获取解析与业务校验后的报告 | 本地执行；业务校验在分析阶段进行 |
| `whcns_analyzer` | 查询 WHCNS 输出表单字段整表最大值、最小值及对应模型日序 | 返回单位、单元格、范围和文件指纹；不执行仿真 |
| `clarification` | 请求补充附件、明确指标或说明支持范围 | 程序生成追问，不依赖 LLM |
| `capability_guidance` | 能力介绍、提问示例及部分范围外请求处理 | 程序生成回答，不依赖 LLM |

这里的 Skill 是 Python 内部能力封装，包含名称、描述、输入模型、输出模型和处理函数。`SkillRegistry.describe()` 可导出能力描述与输入输出 JSON Schema。项目范围内未发现以 `SKILL.md` 组织的 Skill 包。

## 3. 编排、追问与证据

依据：[routing.py](../../../backend/src/agent/routing.py)、[runtime.py](../../../backend/src/agent/runtime.py)、[composition.py](../../../backend/src/agent/composition.py)、[case_skills.py](../../../backend/src/agent/case_skills.py)。

| 场景 | 已有执行方式 |
|---|---|
| 文件统计 | `file_inspector → whcns_analyzer` |
| 文件极值与可能机理 | 文件检查和计算后调用 `knowledge_search`；计算事实与文献推断分别呈现，部分失败保留成功结果 |
| 查找案例并解释 | `case_reference → case_explanation`；匹配成功且具备材料时执行后一步 |
| 文件追问 | 在有效会话与附件条件下继承上一轮成功查询的指标 |
| 案例追问 | 保留案例范围与部分场景信息；每轮重新检查案例是否仍开放 |
| 指定能力 | 通过 `case_skill=reference|explain` 和可选 `case_ids` 指定案例能力 |
| 运行追踪 | 记录路由、实际工具调用、状态、错误、耗时、证据和版本信息 |

当前采用规则路由和有界流程。尚未实现模型自主反复选择工具的通用 Agent 循环。计划中的 Skill 列表与实际调用记录是两个概念，核查执行应看 `tool_calls`。

机理回答会校验引用编号和连续原文摘录；部分玉米问题使用预先整理的证据片段。原文匹配与引用校验不等于专业因果判断已经审核。

## 4. 未注册为聊天 Skill 的配套能力

| 能力组 | 当前已有内容 | 实现入口 |
|---|---|---|
| 文献入库与检索 | 文本提取、规范化、分块、BGE 向量化、Chroma 检索、可选重排、参考文献过滤与数值检索增强 | [rag/](../../../backend/src/rag/README.md) |
| 会话文档 | TXT、Markdown、PDF、DOC、DOCX 提取；分块并按问题选择片段；不提供扫描件 OCR | [session_documents.py](../../../backend/src/api/session_documents.py)、[session_context.py](../../../backend/src/agent/session_context.py) |
| Excel 与 WHCNS | XLS/XLSX 读取、字段与单位校验、日序和数值检查、统计报告、单元格定位与 SHA-256 | [model_tools/](../../../backend/src/model_tools/README.md) |
| 文献管理 | PDF 上传、登记、题录与来源维护、预览下载、重复和版本检查、停用与恢复、逻辑删除 | [literature.py](../../../backend/src/api/literature.py) |
| 文献 AI 辅助 | 建议标题、作者、年份等字段，提取摘要与结论，根据现有启用标签提供分类建议 | [literature_extract.py](../../../backend/src/api/literature_extract.py)、[literature_tagging.py](../../../backend/src/api/literature_tagging.py) |
| 文献批处理 | 批量导入、重复检查、批量 AI 字段解析与打标、逐项状态查询和失败重试 | [literature_batch.py](../../../backend/src/api/literature_batch.py) |
| 共享标签 | 多级分类维度、单选与多选规则、启停、关联查询、层级筛选 | [literature.py](../../../backend/src/api/literature.py) |
| 案例管理与 AI 辅助 | 富文本和表格、AI 解释初稿、标签、批量 AI 打标、开放控制、批量开放或关闭、需求缺口与重复检查 | [case_library.py](../../../backend/src/api/case_library.py)、[case_tagging.py](../../../backend/src/api/case_tagging.py) |
| 星标问题 | 共享专业问题与人工答案的新增、查看、编辑 | [evaluation.py](../../../backend/src/api/evaluation.py) |
| 评测与审核 | 版本化用例、多轮执行、附件资产、人工评审、审核队列、问题跟踪、回归基线、回放及版本比较 | [evaluation/](../../../backend/src/evaluation)、[evaluation.py](../../../backend/src/api/evaluation.py) |
| 追踪与运维 | SQLite 运行记录、版本指纹、健康与就绪检查、登录与角色访问、公开演示目录及请求预算 | [main.py](../../../backend/src/main.py)、[run_store.py](../../../backend/src/storage/run_store.py)、[public_access.py](../../../backend/src/operations/public_access.py) |

### 资料流转边界

- 文献登记与 RAG 索引构建相互独立，登记不会自动重建检索索引。
- 案例保存并开放后供案例 Skill 直接读取；关闭或删除会影响后续请求，不改写历史回答。
- 星标问题不会自动向 Agent 提问，也不自动成为检索材料或评测执行。
- AI 字段建议、单篇标签建议和解释初稿需要通过相应保存流程采用；批量任务的保存行为应按各自接口和页面说明判断。
- 案例单次读取上限为 30 条、材料 JSON 24000 字符；案例问答还检查问题、背景与材料合计容量。

### 文件工具边界

- 当前 WHCNS 结果解析严格支持既定 `Nbal_out` 氮平衡和 `WtaBal_out` 水平衡结构，不是通用 Excel 分析器。
- 网页问答主要开放单字段整表极值；CLI 另有首末值、逐列算术和等统计。
- 逐列算术和不能直接解释为季节或年度总量；模型日序不能自动映射为日历日期。
- 当前源码附件参数为：单份 10 MiB、单会话最多 10 份、全局最多 256 份、缓存容量上限 128 MiB、有效期 24 小时；重启后的恢复能力应另行核查。
- 根 README 和模型工具旧说明仍存在“32 份／30 分钟”等旧参数，后续应与 [files.py](../../../backend/src/api/files.py) 统一。本文附件参数以归档时源码为准。

## 5. MCP 与模型客户端现状

| 项目 | 归档时状态 |
|---|---|
| 外部 MCP 客户端接入 | 在项目源码、依赖声明与已检查配置中未发现 |
| 内部能力作为 MCP 服务提供 | 未发现服务端实现与对应路由 |
| MCP 工具发现、连接配置与鉴权 | 未发现项目级实现 |
| 内部能力描述与校验 | 已有 `SkillRegistry.describe()` 及输入输出模型，可作为后续适配基础 |
| LLM 客户端 | DeepSeek 普通聊天与 JSON 对象输出；包含超时和重试等配置 |
| 模型原生工具调用与流式输出 | 当前客户端未实现，部分旧 README 的职责说明属于规划 |

依据：[pyproject.toml](../../../backend/pyproject.toml)、[main.py](../../../backend/src/main.py)、[base.py](../../../backend/src/llm/base.py)、[deepseek.py](../../../backend/src/llm/deepseek.py)。

本次开发会话给编码助手提供的 MCP、插件和 Skill 属于开发环境能力，不计入农业助手自身的集成能力。后续讨论“接入 MCP”时，应先明确是应用调用外部工具，还是将内部工具开放给其他客户端。

## 6. 开发与命令行工具

工具目录：[backend/scripts/](../../../backend/scripts)、[scripts/](../../../scripts)。

| 用途 | 代表脚本 |
|---|---|
| 模型准备与索引 | `download_models.sh`、`index_papers.py` |
| 检索与上下文诊断 | `retrieval_debug.py`、`context_debug.py` |
| WHCNS 材料与输出 | `read_whcns_results.py`、`inspect_whcns_materials.py`、`build_synthetic_water_fixture.py` |
| 评测 | `run_mini_eval.py`、`run_harness_smoke.py`、`run_eval_group.sh`、`run_eval_matrix.sh`、smoke 脚本 |
| 交付 | `delivery_checks.py`、`create_delivery_manifest.py`、`start_delivery.py`、`build_demo_catalog.py` |
| 维护 | 评测账号创建、验收用例导入、旧文献迁移、文献与评测归档脚本 |

现有工程验证包括后端 pytest、前端类型检查与 ESLint、Playwright 浏览器测试，以及 CI 中的后端测试和前端构建。具体通过情况应查看对应迭代记录，不能由工具存在推断全部验证已通过。

## 7. 已知能力边界

当前尚未提供真实 WHCNS 仿真执行、自动校准、自动施肥决策、通用任意表格计算、扫描件 OCR、联网文献搜索或通用自主工具规划。`simulator/` 为预留模块，其 README 中的 mock 和真实调用规划不能视为已有实现。

## 8. 后续优化候选（待讨论）

这些方向用于保留讨论上下文，不代表已经确定开发任务、优先级或交付承诺。

| 方向 | 后续需明确的问题 | 可考虑的验收依据 |
|---|---|---|
| 能力描述统一 | 如何把 Skill、工作台 AI 操作、底层工具及脚本的入口、依赖、版本、可用状态统一登记 | 能从统一清单查到实际入口与依赖；描述与注册表一致 |
| MCP 适配 | 是调用外部 MCP，还是对外提供本地解析、检索等能力；先覆盖哪个具体场景 | 选定客户端完成端到端调用，输入输出与错误行为可验证 |
| 路由与组合优化 | 规则误判集中在哪里；是否需要模型辅助分类；如何保留可追踪的执行边界 | 固定真实问题与多轮用例，对照路由、实际调用和回答结果 |
| 案例检索扩容 | 如何突破整体材料容量限制，增加候选召回、过滤与去重，同时保留开放状态校验 | 扩大案例集后召回相关材料，关闭案例不进入新回答，比较追问可追溯 |
| 文献登记与 RAG 衔接 | 如何管理入索引状态、版本、重建与失败重试 | 已登记、已索引、已停用状态可区分，引用能定位对应原件与版本 |
| AI 辅助与批处理治理 | 哪些操作只建议、哪些直接保存；如何统一状态、重试和并发修改处理 | 失败重试可追踪，旧任务不覆盖新编辑，保存结果清楚可核对 |
| 文件能力扩展 | 优先支持哪些统计、时间范围或格式；专业口径和数据规则如何确认 | 每项新计算有明确字段、单位、范围和原件证据 |
| 文档与运行状态同步 | 旧说明和当前源码参数不同；“已实现”与“当前可用”如何展示 | 文档参数与代码一致，依赖缺失有明确反馈 |
| 工具级回归 | 如何复用现有 Trace、评测和回放验证以上变化 | 每项优化有可复现的问题、预期结果与前后对比记录 |

后续启动优化时，先以本文与当时源码核对增量，再确定本轮目标、验证数据和验收范围。

## 关联资料

- [项目 README](../../../README.md)
- [工作台资料管理说明](../2026-09-29-agent-harness/workbench-materials-guide.md)
- [Agent Harness 规格](../2026-09-29-agent-harness/spec.md)
- [案例 Skill V1.1](../2026-10-16-case-skills-v11/README.md)
- [文献 V1.2 操作补丁](../2026-10-16-literature-v12-patch/README.md)
