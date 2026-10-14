# 工作台分角色登录 V1.0

需求日期：2026-10-13。

当前已增加 [V1.1 前后台共享登录](shared-session-v1.1.md)，刷新后的登录行为和启动清单以 V1.1 为准；本文保留 V1.0 交付记录。

## 范围和账号

工作台 `/evaluation` 使用账号、密码登录，后端根据账号配置决定角色。前端不提交角色，不提供注册功能。访客仍可通过 `/showcase` 访问公开展示。

| 登录账号 | 角色 | 历史记录身份 |
| --- | --- | --- |
| cau_dev | 开发者 | local-developer |
| cau_expert1 | 领域审核人 | cau_expert1 |
| cau_expert2 | 领域审核人 | cau_expert2 |
| cau_tester1 | 测试者 | local-tester |
| cau_tester2 | 测试者 | cau_tester2 |
| cau_tester3 | 测试者 | cau_tester3 |

每个账号分配独立密码，由 CAU 相关英文前缀和六位随机数字组成。明文凭据仅保存在本机 `backend/var/eval/account-credentials.txt`（0600，已被 Git 忽略），按人员分发。服务端配置保存独立随机盐的 scrypt 哈希。代码、文档和交付清单不包含实际密码。

开发者和首位测试者沿用原 tester_id，因此原执行、评分、任务和文献记录的归属不变。领域审核与普通试评的权限、记录模型沿用现有实现。

## 初始化与迁移

```bash
backend/.venv/bin/python backend/scripts/create_eval_accounts.py
```

脚本生成 1 个开发者、2 个审核者、3 个测试者。已有默认身份配置会先备份到同目录 `access-keys.pre-accounts-时间戳.json`，再原子替换配置。遇到其他身份配置或已存在账号凭据则拒绝执行，避免丢失身份或意外重置密码。自定义目录可传 `--directory`，并将 `EVAL_ACCESS_FILE` 指向对应配置。

新配置需重启后端生效。迁移后的六个账号均不保留旧 token_sha256，旧密钥不能再访问接口。旧格式的读取兼容仅用于尚未迁移的部署与历史隔离测试；工作台页面不再提供密钥登录。

## 登录和会话行为

- `POST /api/eval/login` 接收 `username`、`password`，返回临时会话和服务端身份。
- `GET /api/eval/me` 验证会话；已有工作台和文献接口共用同一验证依赖。
- `POST /api/eval/logout` 撤销会话；已退出的会话不能继续读取或修改数据。
- 会话最长 8 小时，保存在后端进程内存，适用于目前单 worker 部署；后端重启后重新登录。扩为多 worker 前需迁移至共享会话存储。
- 前端会话只保存在内存；切换页面保留，刷新后重新登录并保留当前地址。过期接口返回 401 后回到登录表单。
- 错误账号、错误密码统一提示。每账号 5 分钟最多 10 次尝试，每来源地址最多 60 次；不信任转发头。Next 代理部署下来源地址额度由工作台用户共享。
- 角色仍由后端校验。测试者无审核、资产、运行记录与回归管理权限；审核者无开发者管理权限。

## 验证

自动测试覆盖六账号生成与登录、历史身份保持、旧密钥失效、错误密码、频率限制、会话过期与退出、密码变化与重启失效、角色越权、禁止前端指定身份和无注册接口。浏览器测试使用临时数据库，验证六账号角色导航、登录失败、刷新与移动端表单。

验证结果：后端认证、评测与文献 HTTP 回归 **51 passed**；补强旧密钥失效断言后的账号测试 **6 passed**。浏览器 **16 个不同场景通过**（账号登录 8 项，原导航/运行记录/文献编辑 8 项，分两轮完成）。前端生产构建、TypeScript、修改范围 ESLint 和 `git diff --check` 通过。

## 本机交付

- 工作台：http://localhost:3000/evaluation
- 版本：`delivery-20261013-3f83ae575e90`
- 前端构建：`.next-candidate`；已校验的源码与构建清单：[交付清单](../2026-09-29-agent-harness/delivery-source-manifest-2026-10-13-login-v1.json)。
- 正式库启动前备份：`backend/var/backups/accounts-v1-20261013T033743Z/`，SQLite integrity_check 通过。
- 账号配置迁移前备份保存在 `backend/var/eval/access-keys.pre-accounts-*.json`。
- 正式账号登录、退出、旧密钥拒绝及全部数据库表内容比对结果：[交付核验](delivery-verification.json)。

本版再次启动时使用以下显式清单（原默认清单属于旧版本）：

```bash
backend/.venv/bin/python backend/scripts/start_delivery.py --manifest delivery-source-manifest-2026-10-13-login-v1.json --check
backend/.venv/bin/python backend/scripts/start_delivery.py --manifest delivery-source-manifest-2026-10-13-login-v1.json
```

已运行时不要重复启动或覆盖 `.next-candidate` 构建。后续代码修改需生成新构建与新清单。
