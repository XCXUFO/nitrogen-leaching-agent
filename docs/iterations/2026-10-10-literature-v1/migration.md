# 历史文献迁移（2026-10-11）

## 处理口径

按用户要求，将历史论文纳入全局文献库，后续逐篇完善信息和打标。

- 所有后台用户均可查看和处理；创建人仅用于追溯，不构成归属或权限限制。
- 不打标也会出现在默认文献列表中。“全局”不创建为分类标签。
- 本次统一保存为 **草稿 / 正常 / 未打标**，不将历史文件直接标记为已完成登记。
- 标题和年份沿用旧目录，出处说明记录原文件名及旧编号，内部备注注明待核对。
- 不将文件元数据中的 `Administrator`、`CNKI` 或目录中的第一作者缩写当作完整作者列表；不自动应用旧机器标签。
- 保留旧 PDF、目录和问答索引。原始文件复制到新模块独立持久化目录。

## 执行结果

- 输入：`data/papers/catalog_m16.json` 及该目录中的 90 份 PDF。
- 校验：90 个不同的 SHA-256，所有目录指纹与文件一致，PDF 均可打开并加载页面。
- 原始文件总大小：316,542,004 字节。
- 首次迁移：新增 90 条，失败 0 条；数据库完整性检查 `ok`。
- 再次执行：复用已有 90 条，新增 0 条，失败 0 条；不覆盖人工编辑、打标或使用状态。
- 正式存储：`backend/var/literature/library.sqlite3`、`backend/var/literature/files/`。
- 首次报告：`backend/var/literature/migration-20261011.json`。
- 重跑报告：`backend/var/literature/migration-20261011-recheck.json`。
- 已校验备份：`backend/var/literature-backups/legacy-migration-20261011/`，含 90 条记录与 90 份 PDF。

报告逐项保留旧目录元数据、旧文件名、文件指纹及新文献 ID 的映射，放在忽略提交的持久化目录中。

## 复现与续跑

在 `backend` 目录执行：

```bash
# 预检不创建数据库，不写入文献。
.venv/bin/python -m scripts.migrate_legacy_literature

# 每次指定新的报告文件；按文件指纹复用未删除的现有记录。
.venv/bin/python -m scripts.migrate_legacy_literature \
  --apply --report var/literature/migration-NEW-RUN.json

.venv/bin/python -m pytest tests/test_literature_migration.py -q
```

若更换部署环境，应通过备份恢复迁移正式数据库和 PDF，而非再次从旧目录导入；这样才能保留后续人工修改。工具采用逐条事务，异常时报告保留已完成映射，可修复后续跑。已停用记录不会自动恢复；已删除文件按 PRD 允许生成新文献 ID。

## 访问与验收

当前工作区已启动实际应用：后端 `127.0.0.1:8000`，前端 `127.0.0.1:3000`，文献入口 `/evaluation/literature`。沿用已有后台登录凭证。前端 `.next-candidate` 生产构建连接该后端，后端启动参数启用 `EVAL_ENABLED=true`。这些是当前机器的本机地址，不是外部发布域名。

迁移回归测试验证：不同后台角色可见、原文件下载一致、后续人工编辑与打标、重跑不覆盖人工结果、输入指纹异常及遗漏文件阻止预检。

本次结果：迁移回归 **2 项通过**，生产构建及 TypeScript 检查通过；真实服务浏览器验收 **1 项通过（31 秒）**。已用现有账号核对全库可见性、90 条列表渲染、90 份下载指纹、详情、PDF 预览入口及编辑入口。验收未保存或修改正式文献。

只读浏览器验收命令（在 `frontend` 执行）：

```bash
LITERATURE_MIGRATION_CHECK=1 UI_BASE_URL=http://127.0.0.1:3000 \
PLAYWRIGHT_BROWSERS_PATH=/tmp/nitrogen-playwright \
  ./node_modules/.bin/playwright test tests/literature-migration.spec.ts \
  --output /tmp/nitrogen-literature-migration-results
```

此验收仅适用于迁移后、人工整理前的初始状态，使用本机已有凭证进行只读验证；关闭浏览器 trace/video，不记录登录凭证。人工整理开始后不应再要求全部文献仍为草稿或未打标。
