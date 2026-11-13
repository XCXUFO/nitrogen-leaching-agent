# 回答语言修复失败处理

问题：中文合成记录配英文提问，在后置语言修复阶段报 `answer_language_mismatch`。

原运行 `b0198067-575c-4027-92f8-3db34120584c` 已正确将实际提问识别为英文，资料问答能力调用成功；失败发生在翻译结果的校验阶段。原记录没有保留具体校验子原因，无法据此断定是哪一个字符、占位符或 JSON 格式触发失败。

修复内容：

- 翻译仍保留原数字、引用和标识符占位符，并显式告知模型每项所需的占位符。
- 首次翻译未满足语言、事实或结构校验时，携带具体原因重试一次；两次调用共享原有的 35 秒时限。重试以原始文本为依据，不把失败译文作为新事实。
- 兼容 Markdown 代码围栏中的合法 JSON；两次均不合格时继续拒绝返回，保留原答案。
- 校验纳入运行步骤的成功/失败判断；运行记录保存尝试次数和校验原因，避免只留下泛化错误码。
- 资料简答只提取用户所问字段，避免额外复述其他字段。

验证：

```sh
cd backend
.venv/bin/python -m pytest tests/test_answer_language.py tests/test_provided_text.py tests/test_agent_runtime.py tests/test_case_assistant.py tests/test_chat_runs.py tests/test_run_observability.py -q
```

155 项通过。新增回归覆盖原问题无附件作答、残留中文后的重试、占位符丢失后的重试、无效返回结构、代码围栏 JSON、持续新增数字时拒绝返回，以及失败原因写入运行记录。

真实模型验证：原问题、含中文作物括注的答案修复、完整中文答案修复均成功，作物为 winter wheat，灌溉量保持 80 mm。原问题的服务接口重放亦成功，无 `answer_language_mismatch`。

最终接口重放：`3a4a808b-f6a8-499a-b3ee-9152e5be62ad`，状态 `succeeded`，语言 `en`。验证摘要保存于 `backend/var/eval/answer-language-repair-20261112-service.json`。语言修复文件早于服务重载完成；重载后工作区还有其他文件更新，因此全局代码指纹与当前工作区不同。再次运行上述回归仍为 155 项通过。
