# 2026-10-18 封版审查

审查范围为 `origin/main`（`873d189`）之后的本地提交及当前工作区增量，包括会话运行恢复、账户历史、共享人工审核、Prompt 迭代、Skill 配置、文献全文检索、案例与公开展示。

结论：本轮发现的问题已修复，以下验证范围内无已知未解决的发布阻断问题。

重点核对了服务端身份与会话隔离、重复提交防重、进程重启及取消、SQLite 并发写入、原回答与审核记录保留、资料变更后的检索资格和错误降级。源码检查与自动回归不能替代农业专业质量验收。

## 本轮发现与修复

- 文献解析完成后，React 尚未提交表单更新时，自动打标可能收到文件名标题而非解析标题。解析和打标现在共用字段合并规则，保留用户手工填写，并采用最新的解析结果。
- PDF 上传成功时只保护了解析字段，等待期间新填的内部备注等补充字段会被旧表单覆盖。合并改为基于当前表单，仅重置本次文件选择后未被编辑的 PDF 字段；新增浏览器回归已在修复前复现备注丢失。
- ESLint 未忽略新增 `.next-skills`、`.next-runs`、`.next-prd`、`.next-prompts`、`.next-prompts-md`、`.next-reviews` 构建目录，导致本地全量检查遍历生成代码。改为统一忽略 `.next-*` 构建输出，业务源码和测试仍按原规则检查。
- 本地交付启动器默认指向 10 月 12 日旧清单，无法用于本次版本的源码与产物校验。默认更新为 `delivery-source-manifest-2026-10-18-release.json`，本轮结束时生成并执行 `--check`。
- 根文档仍描述附件自动沿用、刷新不恢复历史及旧首页示例入口。已对齐当前的单条消息附件行为、账户历史恢复与首页入口。
- 标签父节点混选、会话审核标题及公开导航的旧浏览器断言尚未跟随已交付行为更新。对照现有分层筛选与轻量审核要求修正断言，保留筛选结果、混选状态和导航可达性校验。
- 忽略本地 `outputs/` 目录，保留简历与临时模型测速产物，不纳入发布源码。

## 验证

- 后端全量：756 通过，4 跳过，耗时 168.18 秒。跳过项要求外部服务或本地额外资产；Chroma 依赖产生 258 条 Pydantic 弃用警告，无测试失败。
- `pnpm lint`：通过。
- `NITROGEN_NEXT_DIST_DIR=.next-candidate pnpm build`：通过，含 TypeScript 检查和全部页面生产构建。
- 浏览器全量回归：116 通过，30 按隔离后端或真实资产开关跳过，耗时 3.7 分钟。上传自动打标、更换 PDF、保留人工输入、账号与会话恢复、审核、导航、标签筛选和移动布局均通过；修复后重新完成生产构建与 lint。
- 交付指纹相关回归：5 通过；启动器 `--check` 已通过，校验 350 份源码文件及对应生产产物。构建版本为 `delivery-20261018-ea89a55ef20c`。
- `git diff --check`：通过；拟提交源码和文档的常见凭据模式扫描未发现命中。

后端测试及生产构建在正常权限环境执行：沙箱内出现异步线程唤醒受阻和 Next 子进程输出读取异常。浏览器使用本机 Chromium、候选生产构建和独立端口；API 指向 `/tmp` 临时数据库后端，模型关闭，避免写入业务库或发起真实模型调用。未执行付费模型实测、外网域名验收或线上服务切换。

## 构建与交付

本机已验证的生产目录为 `frontend/.next-candidate`，API 转发绑定 `http://127.0.0.1:8000`。源码和产物指纹位于 [本次清单](../iterations/2026-09-29-agent-harness/delivery-source-manifest-2026-10-18-release.json)。在仓库根目录检查：

```bash
backend/.venv/bin/python backend/scripts/start_delivery.py --check
```

Git 不包含生产构建、私有数据库、论文 PDF、模型权重和检索索引。在服务器重新构建会产生新的构建指纹，必须生成新的服务器清单；不要覆盖当前服务正在使用的构建目录。安装锁定依赖、准备现有业务配置和私有资产后，可在独立构建目录构建并校验：

```bash
cd frontend
NITROGEN_NEXT_DIST_DIR=.next-candidate BACKEND_INTERNAL_URL=http://127.0.0.1:8000 pnpm build
cd ..
backend/.venv/bin/python backend/scripts/create_delivery_manifest.py --output delivery-source-manifest-2026-10-18-server.json --dist-dir .next-candidate
backend/.venv/bin/python backend/scripts/start_delivery.py --manifest delivery-source-manifest-2026-10-18-server.json --check
```

部署沿用单 worker；业务数据和文件应先备份。公网服务继续使用原有 HTTPS 和进程管理配置，本地启动器用于本地验证，不负责公网进程守护。
