# 案例与措施库 V1.0 实现说明

本期只实现录入案例与措施、AI 解释初稿、人工保存和两个 Skill 验证的闭环。标签、覆盖看板、缺口管理、独立措施对象、批量导入和审核不纳入。

## 使用入口与数据

工作台 → 资料与证据 → 案例与措施，路径 `/evaluation/case-library`。业务案例与原有评测用例库分开。复用现有工作台账号，三个现有角色均可操作。

标题和正文必填；解释、补充信息、来源选填；默认不开放。正文保留段落、编号、项目符号。支持标题关键词搜索、开放状态筛选、更新时间倒序、20 条分页、详情及逻辑删除。创建人、修改人及时间自动记录。

`CASE_LIBRARY_DB` 默认为 `backend/var/case-library/cases.sqlite3`。管理接口位于 `/api/case-library`，复用登录鉴权。所有修改、开放切换和删除都使用 revision 做并发检查；发生冲突保留输入，可查看最新内容，复制需要保留的修改，再确认加载最新版本。不会自动覆盖他人修改。

## AI 初稿

读取当前表单原文和补充信息，不要求先保存。新稿与解释编辑区分开；采用、人工修改、保存后才生效。已有解释的替换需人工确认。失败可手填保存，原文变更时提示核对解释。

原文最多保存 50000 字符；单次 AI 初稿的原文与补充信息合计上限 24000 字符。超长材料可以正常保存，由人工填写解释。

## Agent 与调用边界

复用 `/api/chat`、SkillRegistry、运行记录及回答展示，提供应用内 `case_reference`（参考）和 `case_explanation`（解释）。自然语言路由和工作台显式选择均可使用。API 可传 `case_skill=reference|explain`、`case_ids`；ID 校验后统一为大写，单次至多 30 个。

本期采用小样本有界直接读取：调用时只取得已保存、开放、未删除的案例，返回 ID、标题、正文、人工解释、补充信息和来源。最多 30 条、材料 JSON 不超过 24000 字符；超限明确提示，不静默截断、不无限塞入上下文。无需异步同步，保存事务完成后直接生效。

回答的 `case_references` 展示案例 ID、标题和实际保存的来源。模型引用的 ID 必须属于本次可用集合；无匹配结果明确说明，缺关键条件时保留模型的具体澄清问题。原文事实优先，人工解释作为重要参考；一般知识需与案例事实分开。

追问在有时限、容量受限的会话内保存案例 ID 和用户原文，不缓存库内事实。当前明确指定的案例优先；关闭或删除后的新请求重新检查状态，即使客户端省略历史也不能沿用旧案例。连续澄清保留用户补充条件；失败请求不切换当前案例。验证面板使用独立会话，避免与普通聊天互相影响。

直接文本解释不强制查库；输入、解释结果不自动成为案例。仍沿用既有聊天运行记录机制。本期不新增自动评测、统计或完整版本管理。案例读取代码纳入既有构建指纹，不为动态案例库建立版本平台。

## 验证与下一步

工程测试使用隔离数据库、合成材料和假 LLM，覆盖数据与调用规则，不等同于真实回答质量验收。实际工程结果见 [review.md](review.md)。

下一步由专业同事提供少量真实案例和典型问题，按 [manual-acceptance.md](manual-acceptance.md) 验证。真实模型联调需要当前环境配置可用 LLM；本次没有部署、导入正式材料或宣称完成专业验收。

复现命令（分别在 backend、frontend 目录执行）：

```sh
./.venv/bin/python -m pytest tests/test_case_library.py tests/test_agent_runtime.py tests/test_chat_route.py tests/test_chat_schema.py tests/test_file_chat.py tests/test_session_documents.py tests/test_versioning.py -q
```

```sh
pnpm exec tsc --noEmit
pnpm exec eslint src/components/case-library-workspace.tsx tests/case-library.spec.ts
# 先启动前端开发服务；测试使用 Chromium channel。
UI_BASE_URL=http://127.0.0.1:3217 pnpm exec playwright test tests/case-library.spec.ts
```

## 表格与真实材料优化

后续版本已支持富文本表格、正文与解释对照、材料口径约束及首批六条关闭案例。最新变更、回归和真实模型试跑边界见 [rich-text-review.md](rich-text-review.md)。
