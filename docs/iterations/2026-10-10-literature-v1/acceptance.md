# 文献库 V1.0 研发与验收记录

日期：2026-10-10。依据本会话提供的 V1.0 PRD；提供内容止于 12.4，已按用户“全部内容”的指示执行。

## 交付范围

- 入口：`/evaluation/literature`、`/evaluation/literature-tags`，沿用现有后台身份。
- 单篇 PDF 上传、草稿、完成登记、编辑、PDF 预览及下载。
- 登记状态与使用状态独立；停用、恢复、逻辑删除及操作原因、变更记录。
- 文件 SHA-256 精确去重，DOI 规范化、重复确认、版本说明及关联文献。
- 登记字段搜索、组合筛选、父标签后代扩展、排序分页、全库概览。
- 标签维度与最多五级标签，单选/多选、必填、改名、移动、停用及删除约束。
- 独立 SQLite 元数据与 PDF 存储、临时上传清理；不触发模型索引或质量评估。

初始维度和标签保持为空，由业务人员根据实际论文样本建立。多选标签禁止同时保存祖先及后代。已停用的历史标签关联可保留和移除，但不能新建；必填的启用维度必须有启用标签才能完成登记或保存已登记文献。

## 本轮发现与修复

| 问题 | 修复与验证 |
| --- | --- |
| 编辑已有文献可绕过 DOI 重复确认 | 新增与编辑执行相同约束；已经确认的同 DOI 版本后续编辑无需重复确认 |
| 关联文献删除后无法继续编辑原文献 | 保留既有关联痕迹，新关联仍禁止选择已删除文献 |
| 草稿替换文件后数据库失败会覆盖原文件 | 文件按内容指纹不可变存储；事务只更新引用；失败保留原文件和上传重试能力 |
| 多人同时保存相同文件 | SQLite 写锁在重复检查前获取，冲突返回现有文献入口 |
| 未填写年份被显示和检索成“未知” | 区分草稿缺失值与明确标记未知 |
| 取消编辑会丢失输入或残留未保存内容 | 先确认，再丢弃；拒绝确认时完整保留输入 |
| 首次列表响应覆盖新输入筛选条件 | 初次加载完成后开放列表；忽略过期响应，并保留返回列表的筛选状态 |
| 关联文献依赖手写 ID | 改为搜索选择已有文献，可移除关联 |
| 已登记编辑仍出现保存草稿 | 改为保存修改，保持登记与原始文件约束 |
| 上传服务返回非 JSON 时界面异常 | 显示可重试错误，保留表单和上次成功上传 |
| Next.js 默认 10 MB 缓冲导致 12 MB PDF 被截断并超时 | 前端按 `LITERATURE_MAX_PDF_MB` 配置代理缓冲（默认 101 MB）；后端提前拒绝声明超限的请求，并继续流式检查真实大小 |

## 自动化验证

后端：18 项通过。

- `tests/test_literature.py`：4 项领域规则测试。
- `tests/test_literature_http.py`：10 项真实 FastAPI HTTP 测试，覆盖鉴权、全角色访问、状态流转、原文件字节、PDF/加密/大小校验、上传所有权、DOI 编辑约束、删除关联、事务失败、并发保存、标签布尔组合、统计口径及临时文件清理。
- `tests/test_documents.py`：4 项原有文档接口回归。

浏览器与代理验收：生产构建下 3 项全部通过（29.7 秒）。使用真实文献 API、合成 PDF 和临时数据库，不使用成功响应替身。覆盖：

1. 上传 → 草稿 → 必填校验 → 完成登记 → 取消编辑/保存修改 → 预览入口/下载 → 停用/恢复 → 删除。
2. 创建维度和父子标签、搜索选择关联文献、重复文件提示、返回列表保留筛选条件及窄屏访问。
3. 大于 10 MB 的 PDF 通过 Next.js 代理传输后，长度和 SHA-256 完整一致。

构建校验均通过：Next.js 生产构建、TypeScript、变更文件 ESLint、`git diff --check`、`uv lock --check --offline`。

本机浏览器截图位于 `/tmp/nitrogen-browser-results/literature-live-PDF-draft--4f42b-ation-preview-and-lifecycle/registered-paper.png` 和 `/tmp/nitrogen-browser-results/literature-live-taxonomy-t-af8fe-stence-and-duplicate-upload/mobile-library.png`。再次运行 Playwright 会覆盖该临时证据目录。

## 复现方法

在 `backend` 下运行后端回归：

```bash
.venv/bin/python -m pytest tests/test_literature.py tests/test_literature_http.py tests/test_documents.py -q
```

浏览器测试使用三个终端。仅使用下列隔离测试应用，不要对正式数据库运行测试。

终端一，在 `backend` 下：

```bash
LITERATURE_TEST_ROOT=/tmp/nitrogen-literature-acceptance \
  .venv/bin/python -m uvicorn tests.literature_fixture:create_app --factory \
  --host 127.0.0.1 --port 8107
```

终端二，在 `frontend` 下依次构建、启动：

```bash
NITROGEN_NEXT_DIST_DIR=.next-candidate BACKEND_INTERNAL_URL=http://127.0.0.1:8107 \
  ./node_modules/.bin/next build
NITROGEN_NEXT_DIST_DIR=.next-candidate BACKEND_INTERNAL_URL=http://127.0.0.1:8107 \
  ./node_modules/.bin/next start --hostname 127.0.0.1 --port 3107
```

终端三，在 `frontend` 下：

```bash
LITERATURE_LIVE_TEST=1 UI_BASE_URL=http://127.0.0.1:3107 \
  PLAYWRIGHT_BROWSERS_PATH=/tmp/nitrogen-playwright \
  ./node_modules/.bin/playwright test tests/literature-live.spec.ts
```

测试浏览器路径按环境调整。未设置 `LITERATURE_LIVE_TEST=1` 时，这组测试自动跳过；测试密钥仅由隔离 fixture 提供。测试数据库及文件位于 `/tmp`，失败的测试数据也可保留供复查。

## 发布前业务验收

- 由实际维护人员使用真实论文样本核对字段、作者署名顺序、未知信息及来源填写规则。
- 确定首批标签维度、定义边界和必填项，再在标签管理中初始化。
- 在目标浏览器上打开普通与扫描 PDF，确认页内容、中文字体和下载体验。自动化已验证文件字节和预览入口，未将 headless 浏览器视为 PDF 页内容验收；当前测试容器也缺少中文字体，截图中文字显示为方框。
- 在实际部署入口验证配置的 100 MB 边界、网络中断/取消重试和外部网关超时；本轮代理完整性测试使用 12 MB PDF，大小拒绝与临时文件清理在 HTTP 测试中使用可配置上限验证。
- 为 SQLite 和 PDF 目录配置持久存储及同一时点备份，使用真实后台凭据完成部署联调。发布需重新以目标后端地址构建，不能复用指向验收端口的构建。
- 更改 `LITERATURE_MAX_PDF_MB` 时，后端运行环境和前端构建环境使用同一个值；外部反向代理也需允许相应请求大小。

第一轮交付为工作区代码、测试与验收文档；当时尚未执行真实论文样本验收。第二轮补充结果如下，正式服务发布仍待确定目标环境。

## 第二轮：真实文件、恢复与边界验收

在前述验收基础上继续执行，详见 [发布与恢复说明](release.md)。

| 项目 | 结果与边界 |
| --- | --- |
| 中文论文 | 仓库 `001_liang_2014_whcns_model_construction.pdf`，13 页；手工核对首页标题、4 位作者、年份、载体和 DOI；完成登记后下载字节及首尾页渲染一致 |
| 英文论文 | 仓库 `051_jiang_2021_is_rice_field_nitrogen_source_sink_environment.pdf`，12 页；保留 11 位作者顺序，完成登记、DOI 查询、预览与下载字节一致 |
| 扫描 PDF | 用中文样本首页生成仅含图片的测试夹具；无可提取正文，仍可保存草稿、下载与渲染。不是完整论文的正式登记 |
| 备份与恢复 | 隔离验收库实际备份及恢复各 9 条记录、9 个 PDF，包含逻辑删除记录；数据库完整性及 PDF SHA-256 校验通过 |
| 备份异常 | 缺原件时失败；恢复拒绝已有目录；文件被改动后拒绝恢复；不恢复未保存上传 |
| 未保存保护 | 新增浏览器历史导航提示；Chromium 下拒绝后退保留全部输入，确认后可离开 |
| 上传失败重试 | 模拟网关返回 HTML 502，输入保留，重试真实上传成功 |
| 100 MiB 边界 | 104,857,600 字节 PDF 上传成功且 SHA-256 一致；104,857,601 字节返回 413。修复后端提前拒绝被 Next 代理转换成 500 的问题 |

这轮样本验收由研发执行，用于核对存储、字段和交互，不替代业务人员确认标签边界。没有向正式文献库导入样本或预设标签。

最终回归：后端 23 项通过（8.30 秒）；生产构建下 4 项常规浏览器测试通过（13.4 秒），单独开启的 100 MiB 边界用例通过（5.0 秒），合计 5 项。生产构建与 TypeScript、变更文件 ESLint 均通过。

新增测试：

```bash
# backend
.venv/bin/python -m pytest tests/test_literature_archive.py tests/test_literature_samples.py -q
```

100 MiB 边界测试默认跳过，单独开启（在 `frontend`，服务仍使用隔离 fixture）：

```bash
LITERATURE_LIVE_TEST=1 UI_BASE_URL=http://127.0.0.1:3107 \
  PLAYWRIGHT_BROWSERS_PATH=/tmp/nitrogen-playwright LITERATURE_SIZE_BOUNDARY_TEST=1 \
  ./node_modules/.bin/playwright test tests/literature-live.spec.ts --grep '100 MB'
```

本机恢复演练目录：`/tmp/nitrogen-literature-release-backup-20261010`、`/tmp/nitrogen-literature-release-restore-20261010`。两者均为测试数据，未切换实际服务配置。

历史导航保护优先使用浏览器 Navigation API，在导航提交前确认；规范见 [HTML Standard：navigate event](https://html.spec.whatwg.org/multipage/nav-history-apis.html#the-navigate-event)。其他目标浏览器的历史导航行为仍需在实际部署环境验收。
