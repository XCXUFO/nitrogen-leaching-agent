# 2026-10-14 上线前快速复查

结论：当前工作区能通过工程回归和生产编译，但暂不建议直接封版上线公网。昨天审查中的主要上线问题仍未关闭；本次没有修改业务代码、依赖版本或启动现有服务。

范围：当前工作区（含未提交、未跟踪的案例库等功能），重点检查启动交付、代理链路、健康检查、账号边界和新增案例库。不是完整安全审计，也不代表真实服务器验收。

## 封版前处理

1. **P1：API 代理超时早于模型处理期限。** `frontend/next.config.ts:7` 只设置请求体上限，没有设置 `proxyTimeout`；本机 Next 的 `proxy-request.js:33` 默认值仍为 30000 ms。`backend/src/config.py:30` 单次模型超时为 60 秒且允许两次重试。经 Next rewrite 的聊天、文献解析、案例 AI 解释超过 30 秒会先断开，即使后端稍后完成。本次核对当前源码和安装包；昨天真实 HTTP 实验记录为后端 32.02 秒返回 200、代理 30.04 秒返回 500，本次未重复该耗时实验。应统一应用总期限、Next 与服务器反向代理的超时预算，并验收超过 30 秒的请求。

2. **P1：生产 Next 版本仍命中安全公告。** `frontend/package.json:22` 锁定 `next=16.2.4`。本次重新联网执行 `pnpm audit --prod --json`，结果为 4 critical、45 high、51 moderate、8 low。它们是依赖版本命中数，不是本项目已证实可利用的漏洞数。已核验 [Next 官方 Server Components DoS 公告](https://github.com/vercel/next.js/security/advisories/GHSA-8h8q-6873-q5fj)，16.2.4 在受影响区间。审计还返回修复版本晚于 16.2.5 的其他公告，因此不能只升级至 16.2.5 就关闭此项。应升级兼容维护版本、同步 eslint-config-next、重新构建并回归；逐项核对适用条件。`shadcn` CLI 仍在生产 dependencies，也应检查是否需要移入开发依赖。未进行漏洞利用。

3. **P1：公开访问的按 IP 限频依赖未明确的可信代理边界。** `backend/src/operations/public_access.py:86` 使用 `request.client.host`；`backend/scripts/start_delivery.py:54` 未显式限制代理头策略；当前 Next proxy 只处理文献上传大小，没有清洗转发头。昨天实际 Next→Uvicorn 链路已证实更换 `X-Forwarded-For` 可绕过每 IP 限频，本次确认相关代码仍未修正，未重复网络实验。若服务器最外层已覆盖清洗转发头，可缓解该项，但当前没有服务器配置可验证。需要在真实入口明确可信代理并验证伪造头不会改变限频身份。全局日预算和并发上限不因此失效。

4. **P1：readiness 会把不可用的知识服务判为可用。** `backend/src/api/health.py:22` 仅判断 `chat_service` 是否存在；模型延迟加载和空索引不在检查范围。使用真实 lifespan、临时空索引和模拟缺失模型，本次再次得到 `/api/ready` 为 200、实际聊天为 503 / `rag_query_failed`。交付启动器还只探测 `/api/health`（`start_delivery.py:54`）。应在启用 RAG 时验证必要模型和非空索引，并让部署放量依据可信 readiness；不应以收费模型调用作为每次健康探测。

5. **P2（发布工序阻塞）：推荐交付清单与当前源码不一致。** 执行 README 推荐的 `start_delivery.py --check --manifest delivery-source-manifest-2026-10-13-shared-login-v1.1.json` 返回退出码 1：`Source changed or missing after manifest: .env.example`。这是校验正确拒绝过期清单，不是建议删除校验。修复、回归完成后，应冻结完整工作区文件，重新生成生产构建及新清单，并验证后再部署。仅推送已有 HEAD 不会包含大量尚未提交的新功能。

## 仍可复现的功能问题

本次重跑 `docs/iterations/2026-10-13-preseal-review/reproductions.py`，5 个缺陷断言全部成立，其中 readiness 已列为 P1。其余为 P2：

- `backend/src/main.py:86`：有 LLM、关闭全局 RAG 时，文档上传返回 ready，但文档问答仍返回 503 / `rag_not_configured`，并未调用 LLM。
- `backend/src/agent/runtime.py:411`：合法文件名 `trial A.xlsx` 被解析为 `A.xlsx`；泛问可计算，指定完整文件名却提示找不到文件。
- `backend/src/api/chat.py:72` 附近：公开 API 返回的是内部哈希会话 ID，客户端将其回传后再次哈希，续问失去原上下文。当前网页自持稳定 ID，因此不等同于所有网页续聊失效。
- `backend/src/agent/runtime.py:129`：先传 `file_ids`，后续省略附件字段时仍复用旧文件，与 README 中省略附件的语义不一致。当前网页显式传列表，主要影响混用 API 字段的调用方。

## 本次验证

| 检查 | 结果 |
| --- | --- |
| 后端 `pytest -q -m 'not live'` | 499 passed、3 skipped、1 deselected；52.09 秒 |
| 已知问题复现脚本 | 5 passed；表示缺陷仍存在，不是验收通过 |
| 前端 `pnpm lint` | 通过 |
| 前端 `pnpm exec tsc --noEmit --incremental false` | 通过 |
| 临时副本 `next build --webpack` | 通过，包含案例库当前源码；未覆盖仓库构建目录 |
| `git diff --check` | 通过 |
| 推荐交付清单 `--check` | 失败：源码已变化 |
| 生产依赖在线审计 | 存在上述安全公告命中 |

测试在沙箱内曾卡于 TestClient/AnyIO 线程通信；经批准在沙箱外重跑后完成，沙箱内残留测试已终止。不将环境卡顿计为业务缺陷。

本次未重新执行浏览器套件、默认 Turbopack 构建、真实付费 LLM 调用或服务器端 Nginx/HTTPS/备份恢复验收。昨天的浏览器验收失败项也不能因本次静态检查通过而视为已关闭。临时构建仅用于编译验证，不是已经封好的交付包。

临时证据：`/tmp/nitrogen-release-audit-20261014.json`、`/tmp/nitrogen-release-reproductions-20261014.txt`；审计统计同时保存在本目录 `audit-summary.json`。完整旧复现说明见 [昨天审查](../2026-10-13-preseal-review/review.md)。
