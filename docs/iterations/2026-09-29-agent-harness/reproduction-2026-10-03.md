# UI02／UI05／UI06 新复现与修复验证

时间：2026-10-03。环境：Linux 上的 Playwright Chromium Headless 153.0.8010.12，`localhost:3000` 聊天页，更新后的本地后端 `127.0.0.1:8002`。聊天页直连产生 Run Trace，**没有工作台 Execution ID**。构建标识：`p0-fixes-20261003:fa0ebc0a1b43a89e`；仓库基底提交 `399b130c5379`，本次修改尚未提交。真实原件 `Nbal_out.xls` SHA-256：`6bf778020c6ae752da6778bc5429d1b09bc59ea1f725462dfe20207cbef88276`。

本记录是 2026-10-03 的新操作，与归档 PDF 中未记录 ID 的历史验收分开。浏览器自动执行步骤见 [live-chat-repro.spec.ts](../../../frontend/tests/live-chat-repro.spec.ts)。
本次选定 Run 的完整 Trace 已另存为[运行证据快照](evidence-2026-10-03/selected-run-traces.json)，便于不依赖本机数据库复核。

| 项目 | 步骤与问题原句 | 实际结果及 Trace | 结论边界 |
|---|---|---|---|
| UI02 | 先发“你能做什么？”，点“新对话”，再发同一句。 | 首条新消息只发出一次，HTTP 200，旧消息及附件未随请求发送；新会话 Run `33a6771d-de74-4f1c-a380-f6622897b47e`，`DIRECT / capability_request / capability_guidance:ok`。实际回答介绍文献问答、WHCNS 表格极值与日序，并说明不执行模型。 | 本次**未复现** PDF 所述“新对话无法发送”；没有凭一次成功声称历史故障已定位。 |
| UI05 | 上传原件，问题“硝态氮最大值及日序”。请求带有效 `file_id`。 | Run `e660bdb3-a64e-4bf8-87e8-27e55262bd63`，`FILE_ANALYSIS / file_intent`；`file_inspector:ok → whcns_analyzer:ok`。实际回答 `3.65926384925842 kg N ha-1`、模型日序 `283`、已核查 `352` 条记录；文件证据 `Nbal_out!C284/A284`，值 `3.659263849258423`。 | 原句本次成功；历史“不稳定”仍需原失败请求定位。新增了其他自然问法的真实原件回归。 |
| UI06 有效追问 | 同会话、文件仍可引用时问“那最小值呢？”。 | Run `121c8706-8ef0-4f21-9bdf-a92ab30d4ae5`，`FILE_ANALYSIS / inherited_metric`；实际回答最小值 `0 kg N ha-1`、首次日序 `2`、`191` 条并列、`352` 条记录；证据 `Nbal_out!C3/A3`。输入框显示“本会话可引用”，不再把它标成待发送附件。[界面截图](evidence-2026-10-03/ui06-session-file.png)。 | 保留 F05 v2 的省略式追问。 |
| UI06 主动移除 | 点击“移除会话文件”后，再问“那最小值呢？”。 | 请求不带 `file_id`，也不带旧数值回答的 `history`；Run `157a6146-04d3-4b53-9370-bac19726ef06`，`CLARIFY / missing_attachment`，回答要求重新上传。 | 未复用旧数值。 |
| UI06 新对话 | 再点“新对话”，问“那最小值呢？”。 | 新会话请求无附件、无旧历史；Run `25131eb3-03d9-4824-a5f1-71cce18dcbc1`，`CLARIFY / missing_attachment`。 | 未复用旧会话指标。 |

附件规则：上传后、首次发送前为**输入框待发送附件**；发送成功后变为**本会话可引用文件**，文件问题与省略式追问仍显式提交其 `file_id`；主动移除、替换、新对话或文件过期后，不再提交旧 `file_id`，并截断向后端传递的旧文件问答历史。服务重启后临时文件令牌失效，后端返回 `file_not_found`，前端清除引用并要求重传。知识问题仍由后端意图路由决定，附件不会将文献问题强行变成文件计算。
