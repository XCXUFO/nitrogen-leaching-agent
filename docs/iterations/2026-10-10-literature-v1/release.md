# 文献库 V1.0 发布与恢复

## 已准备的交付物

- 文献管理、标签管理与独立持久化存储。
- 真实中英文论文及扫描 PDF 验收：`backend/tests/test_literature_samples.py`。
- 一致性备份、校验、恢复工具：`backend/scripts/literature_archive.py`。
- 备份恢复测试：`backend/tests/test_literature_archive.py`。
- 浏览器流程与上传边界测试：`frontend/tests/literature-live.spec.ts`。

2026-10-11 已完成当前工作区 90 份历史 PDF 迁移，并启动本机 3000 / 8000 服务，详见 [迁移记录](migration.md)。外部部署地址及常驻服务管理方式仍待确定。下列命令在指定工作目录执行；现有后台登录配置继续使用。

同日已增加 showcase 文献管理与标签管理示例，并将当前 3000 端口前端更新为 `.next-workbench` 构建，详见 [showcase 交付记录](showcase.md)。下文 `.next-candidate` 为构建示例目录；后续构建请避开正在运行的目录。

## 配置与启动

后端运行环境：

```dotenv
EVAL_ENABLED=true
EVAL_ACCESS_FILE=/absolute/path/to/access-keys.json
LITERATURE_DB=/absolute/path/to/literature/library.sqlite3
LITERATURE_FILES_DIR=/absolute/path/to/literature/files
LITERATURE_MAX_PDF_MB=100
```

`EVAL_ACCESS_FILE` 使用现有密钥摘要文件。文献库不按后台角色限制操作，不要使用测试 fixture 的固定密钥。

在 `frontend` 下，以目标后端地址重新构建，再启动。构建输出目录应与当前运行服务分开，下面使用 `.next-candidate`；示例端口仅供本机部署：

```bash
NITROGEN_NEXT_DIST_DIR=.next-candidate BACKEND_INTERNAL_URL=http://127.0.0.1:8000 LITERATURE_MAX_PDF_MB=100 \
  ./node_modules/.bin/next build
NITROGEN_NEXT_DIST_DIR=.next-candidate BACKEND_INTERNAL_URL=http://127.0.0.1:8000 LITERATURE_MAX_PDF_MB=100 \
  ./node_modules/.bin/next start --hostname 127.0.0.1 --port 3000
```

在 `backend` 下，通过现有服务管理器加载上述运行环境并启动应用：

```bash
.venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --workers 1
```

整个应用的聊天文件状态仍使用单 worker；文献接口的数据库并发锁不改变该限制。外部代理需允许至少 100 MiB 请求体，并为上传设置合适的超时。前后端大小变量必须一致；前端为代理额外预留 1 MiB 缓冲，并在转发前拒绝声明超限的上传；后端继续执行真实大小校验。

入口：`/evaluation/literature`、`/evaluation/literature-tags`。部署后使用实际后台账户上传一篇样本，完成登记，核对下载原件；重启服务后再次查看同一文献 ID，确认持久化目录正确。

## 一致性备份

建议在维护窗口执行。工具复制期间获取 SQLite 写锁，登记和修改会等待；读取保持可用。备份包含所有登记记录、标签、日志及逻辑删除记录的原文件，不包含尚未保存的上传。

在 `backend` 下，将路径替换为实际路径。每次使用新的备份目录：

```bash
.venv/bin/python scripts/literature_archive.py backup \
  --db /absolute/path/to/literature/library.sqlite3 \
  --files /absolute/path/to/literature/files \
  --output /absolute/path/to/backups/literature-20261010
.venv/bin/python scripts/literature_archive.py verify \
  /absolute/path/to/backups/literature-20261010
```

备份格式为 `library.sqlite3`、`files/` 和 `manifest.json`。工具检查 SQLite 完整性、外键、数据库与文件清单对应关系，以及每个 PDF 的 SHA-256。旧版按文献 ID 命名的文件会在备份中统一为内容指纹文件名。失败的操作返回非零状态；不能将未通过 `verify` 的目录作为可恢复备份。

备份不包含身份凭据、服务配置或其他业务数据库；这些沿用现有应用的部署与备份流程。

## 恢复与切换

先恢复到一个全新的目录；工具不会覆盖已有目录：

```bash
.venv/bin/python scripts/literature_archive.py restore \
  /absolute/path/to/backups/literature-20261010 \
  --output /absolute/path/to/restores/literature-20261010
```

恢复成功后：

1. 暂停文献写入并停止后端服务。
2. 将 `LITERATURE_DB` 指向恢复目录的 `library.sqlite3`，`LITERATURE_FILES_DIR` 指向其 `files` 子目录。
3. 重启后端，以实际账户核对文献数量、标签、操作记录和原文件下载。
4. 已删除记录应继续隐藏，原文件仍保留；未保存的临时上传需重新上传。

保留切换前的数据库和 PDF 目录；回退时恢复原来的两个配置路径并重启。备份文件应按既有留存策略复制到独立存储。恢复后产生新写入，原备份的 manifest 不再代表运行中数据库；后续校验应生成新的备份。

## 首批标签讨论稿

依据仓库现有农田氮素论文样本，以下仅作业务讨论，尚未写入正式标签库：

| 维度 | 示例标签 | 分类边界 |
| --- | --- | --- |
| 研究对象 | 冬小麦、夏玉米、水稻、设施蔬菜 | 论文实际研究的作物或种植系统 |
| 研究问题 | 氮素淋失、水氮利用效率、氮素收支 | 论文直接讨论的问题，可多选 |
| 研究方法 | 田间观测、模型模拟 | 按实际方法打标，同篇可同时选择 |

先从少量论文试标、明确边界，再决定哪些维度必填。年份、作者、DOI 和载体仍使用登记字段。系统不会从旧目录自动导入这些标签。
