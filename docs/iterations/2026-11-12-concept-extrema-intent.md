# 专业名词与通用淋失极值问题的意图修正

## 原问题

- Run `87a2e3c9-2593-40b7-bd97-1c85de9c150b`：仅输入 `WHCNS`。语义理解已经描述了概念解释需求，却将领域设为 `unknown` 并要求用户解释缩写，运行时提前返回了领域介绍。
- Run `12801343-680e-4051-b1e1-b0a6793f978f`（另一次为 `6aacae50-3242-496d-9c92-e261ad21bbc9`）：输入 `What is the maximum nitrate leaching?`。语义理解正确指出可以解释不存在统一最大值，但词法路由把“极值 + 硝态氮”当成文件计算，要求上传 WHCNS 表格。

## 调整

1. 独立、完整且可识别的专业名词默认请求概念与用途说明。对 WHCNS 及其他明确农业模型、氮素和植物生理术语，统一理解层纠正错误的功能咨询、案例搜索、未知领域及不必要澄清，保留原问题，不擅自补充参数率定等专业任务。审计记录同时保存模型原始判断和默认解释规则的来源。
2. 没有绑定文件、数据集、研究或观测记录的淋失极值问题先进入通用解释。支持中文、英文及包含作物、季节、理论范围的问法；不再把 `maximum` 和 `nitrate` 的组合直接当成 WHCNS 计算。
3. 概念回答先说明没有普遍适用极值的原因，再解释淋失及淋失量、通量、浓度和时段的区别，最后按需提出一个场景或统计口径问题。不编造统一上限，不把上传文件设为一般知识说明的前提。
4. 明确文件名、结果表、字段名或模型日序的请求继续使用原文件计算路径。有附件时，普通极值查询仍可计算；明确要求一般解释时遵守一般知识意图。确需补传表格时，提示只说要查询的结果表，不擅自指定模型。
5. 通用极值关键词不直接授予领域权限：保留语义领域判断，`nitrate`、`ammonium` 只请求领域复核。领域外请求仍拒答。仅使用指定材料的历史限制、已有专业问答复用和粘贴正文的依据要求仍保留。

## 验证

新增 `test_named_concepts.py` 和 `test_general_leaching_extrema.py`，覆盖原始错误判断、正确路由、改写虚构任务、已有问答复用、来源限制、不同附件状态、通用问法以及领域复核。

将语言测试中的无模型固定回复用例改为明确询问已上传表格；原通用英文问题改由概念回答测试验证。

回归命令（backend 目录）：

```bash
.venv/bin/pytest -q tests/test_named_concepts.py tests/test_general_leaching_extrema.py tests/test_plant_scope.py tests/test_domain_scope.py tests/test_agent_runtime.py tests/test_file_chat.py tests/test_factor_answers.py tests/test_answer_language.py tests/test_semantic_query.py tests/test_task_prompts.py
```

结果：348 项通过。沙箱内涉及线程唤醒和关闭的测试挂起，经批准在沙箱外执行上述测试集后通过。

测试使用隔离的模拟模型与本地测试表格，不写入原会话或审核记录，也不代表已经执行真实模型回答质量重放。
