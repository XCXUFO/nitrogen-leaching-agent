# 整体代码审查（2026-10-11）

## 结论与范围

确认 5 项可操作问题：2 项 P1、3 项 P2。以下是当前工作区审查结果，包含历史实现和本轮新增代码；初次审查时问题尚未修复。现已完成修复，验证与交付记录见 [fixes.md](fixes.md)。

审查覆盖文献与标签、公开 showcase、上传下载、结果表解析、聊天与 RAG、评测任务/执行/回归、存储备份和启动配置中的关键路径。重点是数据正确性和模块衔接，不宣称已穷尽所有问题。

所有问题复现在临时数据或拦截 API 的浏览器中完成；没有为验证这些问题修改正式文献记录、调用外部 LLM 或切换服务。

## 1. [P1] XLSX 声明范围过小时，计算会静默漏行

位置：`backend/src/model_tools/workbooks.py:83–103`，尤其 `sheet.iter_rows()`。

只读工作簿的迭代使用工作表 XML 中的 dimension 范围。代码检查声明的单元格数量，但没有核对声明之外是否还有实际数据；声明范围过小时，后续真实行不参与计算，结果仍被当作成功。

**已复现**：用已有 `make_nitrogen()` 合成工作簿，实际内容为标题和两行数据，硝态氮最大值 1.5。只将 `xl/worksheets/sheet1.xml` 的 dimension 从 `A1:I3` 改为 `A1:I2`，不改动任何数据单元格。`summarize_result()` 成功返回 1 行数据、最大值 **0.5**；原文件则返回 2 行、最大值 **1.5**。

影响：第三方工具导出的错误范围或经过编辑的 XLSX，可能让文件分析生成有单元格依据但数值错误的答案。

建议：不要把声明的 dimension 当作完整性依据。重置或独立核验实际范围，同时保留流式读取的实际行、列、单元格数量限制。覆盖「范围过小」「缺失范围」「异常大行号」回归，避免修复时引入资源上限绕过。

## 2. [P1] 文献保存缺少版本检查，会覆盖他人的修改

位置：`backend/src/api/literature.py:395–417`，全量替换 `data` 和标签关联。

事务锁能串行执行数据库写入，但不能判断客户端表单是否基于旧记录。请求没有 `expected_revision` 或等效前置条件。

**已复现**：两个账号同时读取标题 `Original`。A 修改为 `Corrected title` 并保存；B 使用旧表单仅修改内部备注后保存。两次均返回 HTTP 200，最终标题恢复为 **Original**，A 的修改被覆盖。

影响：用户计划逐篇补充信息和打标时，多人或多标签页协作会丢失字段或标签。操作日志虽保留痕迹，但不能阻止覆盖。

建议：增加单调递增 revision，保存时携带并原子校验，冲突返回 409；前端保留当前输入并提供重新核对入口。旧用例草稿 `CaseCatalog.update_draft()` 已有 expected_revision 模式，可以保持一致。

隔离 HTTP 复现脚本：`/tmp/nitrogen-review-literature.py`。

## 3. [P2] 慢上传完成后，文件名覆盖上传期间手填的标题

位置：`frontend/src/components/literature-workspace.tsx:180–190`。

`xhr.onload` 使用发起上传时闭包中的 `form.title`。若当时标题为空，上传过程中用户填写了标题，回调仍判断为空并写入文件名。

**已复现**：浏览器拦截上传响应，选择 `source.pdf` 后手填 `Manually entered title`，再放行响应。最终输入框变为 **source**。所有 API 均为拦截的虚构响应，未实际上传文件。

影响：用户不易察觉录入内容被替换，可能把临时文件名保存为正式论文标题。

建议：用函数式状态更新读取最新标题，仅在最新值仍为空时提供文件名建议；同时让响应关联到当前上传，避免过期回调更新表单。

浏览器复现脚本：`/tmp/nitrogen-review-upload.cjs`。

## 4. [P2] 文献日期筛选按 UTC 日期，列表却显示本地时间

位置：`backend/src/api/literature.py:443`；前端显示使用 `frontend/src/components/literature-workspace.tsx:23` 的 `toLocaleString()`。

创建和更新日期筛选直接比较 UTC ISO 字符串的前 10 位，前端日期框只提交 `YYYY-MM-DD`。用户按列表显示的本地日期检索时，午夜附近的记录可能被排除。

**已复现**：临时记录创建时间 `2026-10-10T18:30:00+00:00`，上海时区显示 **2026-10-11 02:30**。按创建日期 `2026-10-11` 至 `2026-10-11` 查询，结果为 **0 条**。

影响：按创建/更新时间接续处理、核对某日工作量时发生漏查。

建议：明确统一业务时区，或让前端将用户选定日期转换成带时区的时间边界，后端按 UTC 时间区间查询；不要用日期字符串切片代替时间区间。

隔离 HTTP 复现脚本同第 2 项。

## 5. [P2] 默认交付启动清单已过期，标准启动命令无法启动当前版本

位置：`backend/scripts/start_delivery.py:13–23`；默认清单 `delivery-source-manifest-2026-10-07.json`。

启动器会核对清单内全部文件。对当前工作区只读比对，确认 **11 个文件**与默认清单不一致，包括 backend main/config、frontend next.config、showcase 路由及工作台导航。照原默认命令启动会在启动子进程前退出 `Source changed after manifest`。

当前服务通过单独的 uvicorn/next 命令运行，故在线页面正常不能证明默认交付入口可复用。下次重启或交接仍会遇到问题。

建议：为当前验收版本生成新的交付清单，纳入新增文献/showcase 文件，绑定实际构建目录与后端地址，并更新默认启动入口。保留指纹校验，不应通过绕过校验来解决。

比对发现的文件：`.env.example`、`backend/pyproject.toml`、`backend/src/config.py`、`backend/src/main.py`、`backend/uv.lock`、`frontend/next.config.ts`、`frontend/src/app/evaluation/[...path]/page.tsx`、`frontend/src/app/showcase/[[...path]]/page.tsx`、`frontend/src/components/demo-workspace.tsx`、`frontend/src/components/evaluation-shell.tsx`、`frontend/src/lib/evaluation-navigation.ts`。

## 已执行验证

- 后端：`.venv/bin/python -m pytest -m 'not live' -q` → **417 passed, 3 skipped, 1 deselected**，134.58 秒。
- 227 条警告均为当前测试输出中的 Chroma/Pydantic 弃用提示；不是本轮断言失败。
- 前端：`eslint src` → **41 个源文件、0 错误、0 警告**。
- `git diff --check` 通过。
- XLSX 范围错误、文献旧表单覆盖、日期漏查、上传标题覆盖均做了针对性复现；启动问题采用与启动器一致的只读指纹比对。
- 没有运行付费或联网模型效果评测，也没有把静态检查通过视为上述数据正确性问题不存在。

## 建议处理顺序

1. 修复 XLSX 漏行及文献版本冲突，补充针对性回归。
2. 修复上传标题覆盖和日期边界。
3. 在上述修复验证后更新交付清单并验证统一启动流程。
