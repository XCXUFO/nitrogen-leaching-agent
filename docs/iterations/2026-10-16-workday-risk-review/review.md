# 2026-10-16 当日工作风险复核

更新（2026-10-17）：以下 4 项已修复。原发现保留作审查依据，修复说明与验收见文末；复现脚本现断言修复后的正确行为，核心场景已纳入常规回归。

范围：以 HEAD `873d189`（2026-10-15）为基线，检查当前未提交及未跟踪的业务代码。由于今天没有新增提交，不能仅靠提交日期精确区分 10 月 15 日与 16 日的改动；本次覆盖当前增量，并参考今天的迭代记录。今天较早 review 中已修复的四项问题不重复作为未解决问题报告。

结论：确认 4 项 P2 风险，尚未修改业务实现。本次范围内未确认 P0/P1 问题。优先处理共享内容覆盖和批处理回执一致性，再处理标签筛选显示。

## 1. P2：共享星标问题的旧页面保存会静默覆盖其他人的答案

位置：`backend/src/evaluation/store.py:75–82`；关联 `backend/src/api/evaluation.py:53–55`、`frontend/src/components/starred-questions.tsx:49–55`。

两个维护人员打开同一问题，甲先补录专业答案；乙仍持有旧内容，只修改问题措辞并保存。前端 PUT 同时发送 question 和 answer，后端 UPDATE 仅按 question_id 匹配，没有 revision 或 updated_at 前置条件，因此乙的旧答案覆盖甲的新答案，两次保存都会成功。数据库线程锁只能保证语句串行，不能识别陈旧编辑；当前表也没有答案历史用于恢复。

复现已确认：先保存 `Expert updated answer`，再用旧页面的问题修改保存，最终答案恢复为 `Original answer`。

建议：为记录增加 revision，更新必须带 expected_revision 并执行条件 UPDATE；冲突返回 409，前端保留输入并提示加载最新内容。共享人工答案宜保留变更记录及操作者。

## 2. P2：文献已保存但进程中断后，原批次无法通过重试恢复

位置：`backend/src/api/literature_batch.py:98–114`；`update_paper` 在 `backend/src/api/literature.py:534–556` 自行提交事务。

worker 先保存文献、增加 revision，然后在另一个事务中更新批次回执。进程若在两次提交之间退出，文献已经是 revision=2，而回执仍是 processing/revision=1。五分钟后界面允许重试，但 worker 的 revision 检查必然失败，异常分支仍把回执保存为 revision=1。以后重复点击重试仍失败；用户只能人工核对结果或重新创建批次，原回执无法确认已完成的处理。

复现已确认：在真实 `update_paper` 提交后模拟进程退出，随后连续两次经 retry_import 重新处理，均为 failed；实际文献 revision=2，回执始终 revision=1。

建议：把文献更新与对应条目回执放入同一个数据库事务，或增加可核验的操作 ID 与恢复机制。不要通过跳过 revision 校验恢复，以免覆盖人工修改。案例打标当前已将标签变更和回执放入同一事务，可参考其做法。

## 3. P2：文献超时旧 worker 能覆盖新 worker 的成功回执

位置：`backend/src/api/literature_batch.py:63–69`、`111–114`、`228–229`。

文献任务只在开始时认领 queued 状态，完成时无 attempt 校验，直接覆盖条目。若旧进程/worker 暂停超过五分钟，另一 worker 经重试先完成，再恢复旧 worker，旧调用的保存会被文献 revision 保护拒绝，但异常回执仍无条件写入：新任务 ready/revision=2 被改回 failed/revision=1。实际新结果还在，界面却显示失败，并进入上述无法恢复的重试状态。

复现已确认：模拟原 worker 超时，实际调用 retry_import 和第二次 process_batch 完成新结果，再让原 worker 返回；成功回执被旧调用覆盖。这里不要求普通模型请求超过 45 秒，进程暂停、跨进程恢复或 PDF 读取阻塞都可能越过重试阈值。

建议：每次认领生成 attempt/租约 ID，保存文献及写回执之前均检查仍持有当前 attempt，过期调用不得更新任何结果。案例打标已实现 attempt 隔离；文献流程需要补齐。

## 4. P2：所有子标签被勾选后，父标签显示全选但遗漏直接关联父标签的资料

位置：`frontend/src/components/literature-taxonomy.tsx:57–60`；共用于案例与文献筛选。

`checked(parent)` 在所有子标签选中时直接返回 true，但实际筛选数组仍只有子标签。后端的父标签筛选包含自身及后代，子标签筛选不会包含直接关联父标签的记录。于是“玉米、小麦”全选后，“粮食”显示已勾选，直接标为“粮食”的资料却缺失，用户容易把不完整结果理解为完整分类。再次点父标签走取消分支，无法在当前勾选状态直接补入父标签。

真实 Chromium + 拦截 API 的隔离页面复现已确认：父复选框 checked，提交的筛选仍为 `maize,wheat`，直接关联 parent 的案例不在列表。截图位于 `/tmp/nitrogen-workday-parent-filter.png`。

建议：区分“选中该节点”与“其子节点均选中”；父节点自身尚未包含时使用半选/部分覆盖状态，并允许点选父节点后把筛选归并为父 ID。不要直接把子标签数组归并为父标签而不说明，这也会改变直接关联父标签资料的筛选结果。

## 验证与范围限制

- 相关既有后端回归：130 passed，35.96 秒，覆盖案例库、共享标签、批量打标、文献批处理/解析/HTTP、星标问题、AgentRuntime 和上次 review 的修复复现。
- 新增风险复现：3 项 Python 场景通过，断言确认当前缺陷；1 项 Chromium 筛选复现通过。脚本分别为本目录 `reproductions.py` 和 `browser-reproduction.cjs`，修复后需要改为期望行为断言。
- TypeScript 检查、7 个相关前端文件 ESLint、`git diff --check` 通过。
- 沙箱内 TestClient 卡住、Chromium 启动被 socket 权限阻止；经获准在沙箱外完成相应验证。复现只使用临时数据库、模拟模型和拦截 API，无真实付费模型调用，无正式资料修改。
- 只读核对本机 8000 OpenAPI：已注册 case-library/batch-availability、tag-jobs、taxonomy、literature/imports、batch-ai、eval/starred-questions 的相应方法。接口存在不等于全部线上行为已验收。
- 未执行生产构建、完整浏览器回归、真实模型专业效果审核或生产部署。
- 交付注意：当前业务增量仍未提交，且 case_tagging.py、literature_batch.py 等核心模块仍未跟踪。发布前需要将必要新文件纳入同一交付版本，不能用当前 HEAD 单独复现今天的功能。

运行复现：

```bash
cd backend
.venv/bin/python -m pytest -q -s ../docs/iterations/2026-10-16-workday-risk-review/reproductions.py
```

浏览器脚本需要本机前端 3000 服务、已安装的 Chromium；脚本拦截全部 `/api/` 请求，不读取真实资料。脚本中的依赖和 Chromium 路径按本次工作区配置。

## 修复与验收（2026-10-17）

1. 星标问题增加 revision，旧表启动时自动迁移为 revision=1，重复初始化不重置版本。PUT 必须带 expected_revision，数据库条件 UPDATE 保护跨连接并发编辑；不存在返回 404，陈旧编辑返回 409。前端保留输入、说明冲突，用户复制需要保留的修改并显式载入最新版本后继续编辑。旧客户端不传版本会返回 422，不能绕过保护。当前未增加历史版本恢复能力。
2. 抽出由调用方管理事务的 update_paper_record。批任务在同一个事务内检查 attempt、更新文献、写变更事件和保存条目回执，任意持久化阶段中断一起回滚。普通单篇更新也在事务内读取返回快照。
3. 文献 worker 每次认领生成独立 attempt；重试使旧 attempt 失效。成功与异常回执都检查 attempt 和 processing 状态，旧 worker 即使恢复也不得修改文献或回执。原有 revision 检查、五分钟中断恢复和三条并发限制保留，AI 推理期间不持有写事务。
4. 标签父节点只有被直接选中或由已选祖先覆盖时才显示勾选；仅有后代选中时显示原生半选及“部分下级已选”，点击父节点后明确把筛选归并为父 ID。文献和案例复用同一组件，直接关联父标签的资料不会再被“全选”状态误导遗漏。

验证：

- 后端非 live 全量：555 passed、3 skipped、1 deselected，用时 86.51 秒；新覆盖旧库迁移、跨 SQLite 连接冲突、文献写入后/回执写入后中断回滚与恢复、重试后旧 worker 在新任务排队或完成时返回。Chroma 依赖产生 227 条既有 Pydantic 弃用警告。
- 归档复现场景改为期望正确行为，单独运行 5 passed；核心测试在 backend/tests 中，随常规测试收集。
- 浏览器 24 个不同场景最终全部通过：首轮 23 passed、1 项新增断言错误（文献筛选需点应用，误按即时请求断言），修正测试后该项单独重跑通过。新增星标冲突保留输入/载入最新版/带新版本保存，以及子标签半选/显式选父标签/包含直接关联父标签的记录均通过；回归案例编辑、表格、问答、批量开放和 AI 处理。
- TypeScript、修改文件 ESLint、git diff 空白检查通过。浏览器使用模拟 API，后端使用隔离数据库和模拟模型，未修改正式业务数据，未调用真实付费模型，未部署或重启业务服务。
- 独立 `.next-candidate` 目录生产构建通过（webpack、TypeScript、静态页面生成及构建追踪）。沙箱首跑无法解析 TypeScript 子进程的 --showConfig 输出，经获准在沙箱外重跑成功；未改动在线服务使用的构建目录。
- 同步资料使用指南和文献批处理说明。提交范围包含此前未提交的配套业务模块、测试及迭代文档，排除无关 outputs/resume 文件。
