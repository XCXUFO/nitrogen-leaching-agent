# 入门模型介绍的回答质量修复

用户仅输入 `WHCNS` 时，原回答直接复用了 SQ-026 的项目背景答复，正文包含选型理由、无关能力限制和拼接的内部资料定位。运行记录的 `decision.reason_code=starred_full_coverage`、`answer_assembly.mode=starred_only` 确认这次回答绕过了概念讲解与表达 Prompt。

调整：

- 通用入门概念及模型介绍进入 `concept_explanation`，不再以相关星标答复代替完整讲解。显式项目问答仍可复用维护内容，文件计算、案例任务及新检索要求沿用原有优先级。
- 模型介绍先说明定位与用途，再解释核心模块、典型输入输出和一个农业应用场景；按内容使用简短标题、关键词和模块表格。
- 不从参考资料推定用户的毕业设计或项目归属，不在基础介绍中堆叠无关的版本、地下水全剖面及平台运行限制。文献仍通过引用编号与引用信息关联，不将内部文档编号、页码、网址和 DOI 拼接进回答尾注。
- 沿用现有 Prompt 版本与来源限制；没有改写历史问答或切换已保存的任务 Prompt。

验证命令（在 `backend/` 执行）：

```bash
.venv/bin/python -m pytest tests/test_named_concepts.py tests/test_starred_upgrade.py tests/test_semantic_query.py tests/test_task_prompts.py tests/test_unified_pipeline.py -q
```

结果：132 通过，5 失败。新增回归覆盖语义理解开启/关闭时的三种模型介绍问法，以及本地检索结果经概念生成后保留真实引用。

5 个失败来自 `test_unified_pipeline.py`：4 个旧追问用例的 mock 返回英文 `fake answer`，不能通过现有中文回答修复契约；1 个用例预期星标服务异常状态为 `failed`，现有实现为 `unavailable`。在独立测试进程禁用本次新增的概念复用拦截分支后，5 个用例仍以相同原因失败。未修改这些既有行为或用例。

后续封版审查已将这些 mock 与状态断言对齐现行契约，并纳入全量回归；上面的 132/5 保留为当时检查记录。最终验证见[封版审查](../releases/2026-11-13-preseal-review.md)。

后端重启后，通过前端 `http://127.0.0.1:3000/api/chat` 实际提交 `WHCNS`，最终返回 HTTP 200、`outcome=complete`、`trace_saved=true`，耗时约 38.2 秒。运行 ID 为 `dfbaefcc-ecbd-495c-b6fd-01eba353125d`。Trace 确认 `introductory_concept → concept_explanation`，星标复用状态为 `not_applicable`。回答包含模型定位、核心模块表格、模块联系、典型输入输出和轮作灌溉场景；6 条文献引用通过引用字段返回，正文不再拼接原星标答复的资料编号与网址。

首轮真实检查曾把蔬菜专用扩展版本列入核心模块表格，已补充模块与版本层级的表达规则；最终检查中该版本与基础过程模块分开说明。此处验证了路径与表达改进，未将自动回归或单轮生成作为专业正确性的人工审核结论。
