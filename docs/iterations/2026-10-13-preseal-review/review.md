# 2026-10-13 封版前系统审查

结论：**当前版本不建议直接封版部署公网。** 本轮记录 9 项待处理问题：4 项 P1（封版前处理）、5 项 P2（功能或验收缺口）。其中 7 项业务/部署问题有隔离复现，1 项为实际浏览器验收失败，1 项为依赖版本安全公告命中。未发现需要立即停止现有开发环境的 P0 证据。

审查对象为当前工作区，包含未提交和未跟踪的新功能，不仅是 HEAD。没有修改业务代码、升级依赖、覆盖交付构建或操作正式数据库。按可能公开访问的服务器部署场景评估；实际服务器的 Nginx、HTTPS、进程管理和网络边界未提供，因此不将本机结果视为服务器验收通过。

## 问题清单

| 编号 | 级别 | 问题 | 证据与影响范围 |
| --- | --- | --- | --- |
| R01 | P1 | Next 代理默认 30 秒超时早于后端处理期限 | 后端 32.02 秒返回 200，代理 30.04 秒返回 500 |
| R02 | P1 | 未清洗的转发头可绕过按 IP 限频 | 同一客户端更换 X-Forwarded-For 后由 429 恢复 200 |
| R03 | P1 | readiness 未验证模型和索引实际可用 | 空索引、模型加载失败条件下 ready=200，查询=503 |
| R04 | P1 | 生产依赖锁定已命中安全公告的 Next 版本 | Next 16.2.4；审计共 108 条版本命中，须分场景处置 |
| R05 | P2 | 仅配置 LLM 时上传文档问答仍依赖全局 RAG | 上传 ready 后问答返回 rag_not_configured |
| R06 | P2 | 带空格的 Excel 文件名不能被准确指定 | trial A.xlsx 被截成 A.xlsx，提示文件不存在 |
| R07 | P2 | 公开 API 返回的 conversation_id 不能用于续聊 | 回传后再次哈希，会话改变、指标上下文丢失 |
| R08 | P2 | 混用附件 API 时省略附件会静默复用旧文件 | 与现有 README 的省略语义不一致 |
| R09 | P2 | 浏览器验收与当前交互脱节，CI 未执行浏览器检查 | 通用套件 1 失败，独立文献套件 3 失败 |

### R01 — 统一整条代理链路的超时预算

位置：`frontend/next.config.ts:7–9`；`backend/src/config.py` 的 `deepseek_timeout_s`、`deepseek_max_retries`。

Next 通过 rewrite 转发 `/api`，但没有配置代理超时。本地安装版本的 `next/dist/server/lib/router-utils/proxy-request.js:33` 使用默认 30,000 ms，而 DeepSeek 默认单次超时为 60 秒且允许重试。真实检索、模型生成或 PDF 字段解析超过 30 秒时，后端即使最终成功，浏览器也收不到结果。

隔离 HTTP 实验：同一个等待 32 秒再返回的后端接口，直连为 `200 / 32.02s`，经过本次构建的 Next 为 `500 / 30.04s / Internal Server Error`。这验证的是实际 Next→Uvicorn 转发行为；没有调用收费模型。

建议：明确请求总体上限（含检索、模型重试），同步设置 Next 和外层反向代理期限，确保代理不会先于应用的受控错误响应断开。若生产由 Nginx 直接转发 `/api`，则在该链路验证相同条件。修复后至少覆盖超过 30 秒的正常响应、真正超时、重复点击及会话忙碌恢复。

### R02 — 在实际代理边界校验客户端 IP

位置：`backend/src/operations/public_access.py:86`；`backend/scripts/start_delivery.py:53–54`。

限频使用 `request.client.host`，但该值已经可能由 Uvicorn 的 ProxyHeadersMiddleware 改写。当前启动命令采用默认代理头行为，信任回环来源；Next 保留客户端传入的 `X-Forwarded-For`。因此，“应用没有手动读取转发头”不代表不能伪造 IP。

复现采用实际 Next→回环 Uvicorn 链路，将每分钟额度设为 1，同一真实客户端依次发送 IP-A、IP-A、IP-B，得到 `[200, 429, 200]`；后端观测到人为指定的 `198.51.100.99`。**只证实每 IP 限频可被绕过，全局日预算和并发上限仍然有效。** 若生产最外层代理已覆盖清洗转发头，影响可能被缓解，需要从公网入口验证。

建议：明确可信代理列表，在最外层覆盖不可信转发头，并使 Next/Uvicorn 的解析规则与拓扑一致。不能简单依赖客户端自报 IP，也不能不加区分地禁用代理解析、让所有用户共享一个回环 IP 额度。加入整条代理链路的防伪造回归用例。

### R03 — 将“对象已创建”与“服务可用”分开

位置：`backend/src/api/health.py:19–24`；`backend/src/main.py:84–117`；`backend/src/storage/chroma_store.py`；`backend/scripts/start_delivery.py:54`。

`/api/ready` 仅检查 `chat_service` 是否非空。模型采用延迟加载，Chroma 会为不存在的目录/集合创建空索引，因此构造成功不证明模型存在或索引正确。交付启动脚本进一步只等待 `/api/health`，该接口始终报告进程存活。

隔离复现使用真实应用 lifespan、新建空 Chroma 路径、缺失模型路径，并将模型实际加载替换为明确的 FileNotFoundError（避免下载或访问网络）。索引条目数为 0，`/api/ready` 返回 200，而知识查询返回 503。模型失败是受控注入；空索引创建和 readiness 行为为真实实现。

建议：启动阶段验证所选集合非空、embedding/reranker 资源可加载且能执行一条代表性检索，将验证结果纳入 readiness；发布启动等待 ready。liveness 保留独立。外部 LLM 连通性和回答质量另做受控验收，不必让每次健康探测调用收费模型。

### R04 — 更新受影响的运行时依赖并完成适用性核对

位置：`frontend/package.json:18` 及 `frontend/pnpm-lock.yaml`。

`pnpm audit --prod --json` 于本轮在线完成，返回 **4 critical、45 high、51 moderate、8 low**。这是依赖版本命中统计，**不是 108 个已证实可以攻击本项目的漏洞**。摘要见 `evidence/frontend-audit-summary.json`，完整原始结果保留在 `/tmp/nitrogen-preseal-review/frontend-audit.json`。

直接运行时依赖 `next=16.2.4` 命中多条官方公告。例如 [Server Components 拒绝服务公告](https://github.com/vercel/next.js/security/advisories/GHSA-8h8q-6873-q5fj) 列出 16.0.0 至 16.2.5 之前的受影响版本；[AVIF 图片优化公告](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4) 涉及图片优化中的底层库；[next/og 公告](https://github.com/vercel/next.js/security/advisories/GHSA-vcvr-r3jv-pc5j) 明确要求 Node ImageResponse 处理攻击者可控 SVG 值。

对本项目的限制判断：当前源码搜索没有发现 `next/og`、`next/image` 或显式 Server Actions 使用，运行环境为 Linux，因此不能宣称 Windows RCE 或 next/og RCE 已可利用。当前也没有配置 `images.remotePatterns`，按官方公告，后述图片优化 SSRF 不适用于这一配置。另一个 critical 的 `proxy-addr` 来自 `shadcn → MCP SDK → express`，不是上述 FastAPI 限频问题。`shadcn` 当前被列在生产 dependencies，扩大了审计范围。

建议：选择覆盖当前公告的兼容维护版本并锁定依赖，重新构建和执行浏览器回归；调整仅用于生成代码的 CLI 依赖归属。不能只升级到最早的 16.2.5 修复点后宣布所有公告已解决，本轮还命中了后续公告，例如 [图片优化 SSRF](https://github.com/vercel/next.js/security/advisories/GHSA-cjq9-62q9-8jv4)。逐项记录不适用条件或修复结果。此次只审计和核验公告，未进行漏洞利用或依赖升级。

### R05 — 上传文档问答不应被全局索引开关意外禁用

位置：`backend/src/main.py:81–84`；`backend/src/agent/skills.py:93–100`；说明契约见 `frontend/README.md:21`。

配置了 LLM 但 `RAG_ENABLED=false` 时，`app.state.llm` 存在，`chat_service` 仍为 None。上传 txt/md/pdf/doc/docx 可以成功，但知识技能在使用会话文档之前即拒绝执行。当前前端说明写的是“文档问答需要 LLM”，实际还强制需要全局 RAG。

真实 lifespan 加假 LLM 复现：txt 上传状态为 ready，随后对该文档提问返回 `503 / rag_not_configured`，LLM 从未被调用。建议为会话文档提供不依赖全局检索的调用路径；若产品明确要求全局 RAG，则至少让功能开关、上传后的可用性提示和部署说明保持一致。回归应覆盖真实 lifespan 的配置矩阵，不能只给测试 app 手动注入 ChatService。

### R06 — 使用完整已上传文件名匹配

位置：`backend/src/agent/runtime.py:351–356`，以及 `371` 附近的分句处理。

正则 `[\w-]+\.xlsx?\b` 仅接受一段不含空格的名称。上传合法的 `trial A.xlsx` 后，泛问“硝态氮最大值”返回 1.5；明确问“trial A.xlsx 硝态氮最大值”却变为“未找到可用的文件：A.xlsx”，没有数值证据。

建议优先从已上传文件列表匹配完整文件名，并在分句和组合问题路径采用相同规则，覆盖空格、括号、点号和名称包含关系。不能通过随意去掉文件限定来修复，否则会算错指定表。

### R07 — 返回客户端可继续使用的会话标识

位置：`backend/src/api/chat.py:69–73`；`backend/src/agent/runtime.py:145`；契约见 `backend/README.md:200–201`。

公开模式将 visitor 和客户端 session_id 哈希成内部 ID，响应又把内部 ID 作为 conversation_id 返回。客户端按照 README 把返回值用于下次 session_id 时，会再次哈希，落到另一个会话。

复现：首轮文件极值查询成功；携带响应 conversation_id 追问“那最小值呢？”后，上下文丢失并返回澄清，第二个 conversation_id 与第一个不同。绑定 session 上传的附件还可能因会话检查而被拒绝。当前网页自持稳定的客户端 ID，所以不是所有网页续聊都会失败，主要影响遵循公开 API 返回契约的调用方。

建议区分外部 ID 和内部隔离键，响应返回可继续使用的外部 ID；仍然在服务器内部绑定 visitor，不能根据客户端传入的某个前缀跳过归属校验。

### R08 — 明确省略附件字段的行为

位置：`backend/src/agent/runtime.py:123–131`；契约见 `backend/README.md:202`。

会话曾提交 `file_ids` 后，后续请求省略 file_ids 和 file_id 不会清空 `session_files_enabled` 或旧 ID。复现首轮显式提交附件查最大值，第二轮只发 session_id 和“那最小值呢？”，仍从旧文件得到 0.5。这与文档“省略 file_id 不会静默复用旧附件”不一致。

当前网页会显式提交完整 file_ids（清空时传 []），因此主要是混用新旧字段的 API 调用方受影响。未观察到跨访客读文件，不能把它描述为跨用户泄漏。建议统一旧字段、新字段与省略值语义，在入口规范化，并测试省略、null、[]、旧 file_id、换会话的组合。

### R09 — 恢复能覆盖当前交互的浏览器发布门禁

位置：`frontend/tests/public-demo.spec.ts:12`；`frontend/tests/literature-live.spec.ts:27,103,148`；`.github/workflows/ci.yml:57–61`。

通用浏览器套件在独立前端构建、无真实 LLM 的接口夹具下得到 **32 passed / 1 failed / 15 skipped**。失败用例仍寻找“移除会话文件”按钮，而当前已使用附件采用“收起文件”交互。测试后续对删除语义的预期也需与需求同步。

另外使用真实 `tests.literature_fixture:create_app` 和全新临时数据库运行文献套件，得到 **1 passed / 3 failed / 1 skipped**：

- 两个用例等待“文件已上传”的 status；自动 PDF 解析会立即清空该提示，合成 PDF 又进入“文字不足，请手动填写”的 alert，导致等待失败。上传文件已显示在页面，但用例未走完后续流程。
- 关联文献测试直接填写折叠区域中的输入框，没有先展开“来源与补充说明”，等待可见性超时。
- 12 MiB PDF 经 Next 代理完整上传成功；100 MB 边界用例未启用，不能记为通过。

已定位的失败主要是验收脚本与界面变化不一致，不能据此断言文献上传功能整体坏掉；同样也不能宣称被提前中断的登记、取消、生命周期流程已验收通过。CI 目前只 lint/build，不能拦截这些问题。

建议更新用例以断言稳定的业务结果并正确操作折叠区域，独立夹具接入 CI；覆盖公开附件和文献核心流程。测试不要为通过而强迫产品恢复旧交互。两个套件有跳过项重叠，不应简单相加成唯一用例总数。

## 已执行验证

| 验证 | 结果 | 范围与限制 |
| --- | --- | --- |
| 后端 `pytest -m 'not live' -q -o faulthandler_timeout=60` | 446 passed、3 skipped、1 deselected | 36.52 秒；未运行收费模型/真实检索 live 测试 |
| 前端 `eslint .` | 通过 | 全前端目录 |
| 前端 `tsc --noEmit --incremental false` | 通过 | 当前源码类型检查 |
| 隔离 `next build --webpack` | 通过 | 源码复制到 /tmp，未覆盖既有交付构建；未验证本轮 Turbopack 构建 |
| `uv pip check --python backend/.venv/bin/python` | 107 个包依赖兼容 | 这是兼容性检查，不是 Python CVE 审计 |
| `start_delivery.py --check` | 通过 | delivery-20261012-248e5dc8c18d，.next-workbench → 127.0.0.1:8000；仅指纹验证 |
| `git diff --check` | 通过 | 已跟踪修改的空白检查 |
| 5 个定向缺陷复现 | 5 passed | 断言“缺陷存在”，不是功能验收通过 |
| 通用 Playwright | 32 passed、1 failed、15 skipped | 无收费 LLM、隔离服务 |
| 独立文献 Playwright | 1 passed、3 failed、1 skipped | 真实文献路由/存储，临时数据 |
| 代理超时/IP 伪造 HTTP 实验 | 已复现 R01、R02 | Next 生产构建 + 回环 Uvicorn |
| `pnpm audit --prod --json` | 未通过 | 108 条版本命中；见 R04 |

初次 TestClient/本机端口和依赖审计在沙箱内受限，获授权后在允许的执行环境完成上述检查；没有将这些环境限制算成业务代码故障。后端测试的 227 条警告主要来自 Chroma/Pydantic 弃用提示，不是失败项。

审查覆盖 API/配置和生命周期、文件上传/归属/过期、会话路由和文件统计、知识检索调用、公开访问预算、评测与文献路由/存储/迁移归档、前端调用及浏览器用例、交付指纹和 CI。自动化通过仅证明现有断言覆盖的行为，不等于所有分支和专业答案均正确。

## 本周末的放行条件

1. 关闭 R01–R04：在实际入口验证慢请求、伪造转发头、冷启动缺资源，并完成运行时依赖修复或有证据的不适用判定。
2. 处理 R05–R08；如本次不提供相关配置/API 用法，明确限制并同步界面和接口文档，不留下与宣称能力相矛盾的行为。
3. 更新并重跑 R09 的完整核心流程。执行真实模型的小规模 smoke test：知识问答及引用、上传文档问答、表格数值、原文查看；由业务人员核验专业内容。100 MB 边界如果是此次对外承诺，也应启用验收。
4. 固化完整源码和依赖后再生成新构建、新 manifest，保留上一版可回滚产物。审查开始时已有 34 个跟踪文件修改，且文献、会话文档等关键源码仍为 untracked；若只部署 Git commit/archive，这些文件不会自动进入服务器。
5. 在服务器验证 HTTPS、Cookie/CORS、可信代理、非公网后台端口、服务重启与进程守护。当前启动脚本是本地交付工具，不代表服务器进程管理已经完成。内存会话与文件注册表要求保持当前单 worker 设计，扩容前另行处理共享状态。
6. 核对离线模型、Chroma 集合、PDF 原文、评测/文献数据库、身份和预算数据库的路径、权限、备份与恢复；私有资源不因代码 manifest 通过就自动具备。至少在临时目录实际恢复一次，保留回滚步骤。

另有上轮已记录的产品边界：会话文件为内存状态，闲置 TTL 为 24 小时，后端重启会失效；前端心跳不能保留跨重启的服务端文件。如果“窗口不关就一直可用”仍是验收要求，该要求尚未满足，需明确本次接受范围或实现恢复机制。

未完成且不能代替的检查：真实服务器配置和重启演练、生产规模压力测试、完整 Python 安全公告审计、收费 LLM/实际私有索引连通性及专业正确性。对这些不作“已通过”结论。

## 证据

- `reproductions.py`：5 个隔离 API 缺陷复现。可在仓库根目录执行 `backend/.venv/bin/python -m pytest docs/iterations/2026-10-13-preseal-review/reproductions.py -q -s`。使用临时资源和假 LLM；断言刻意验证当前缺陷，修复后应将其改为期望行为再纳入正式回归。
- `evidence/integration-results.json`：代理超时与 IP 实验结果。
- `evidence/browser.log`、`evidence/literature-browser.log`：现有浏览器用例实际结果。
- `evidence/frontend-audit-summary.json`：审计分级、命中版本、依赖路径、公告链接和修复范围；未存储公告长篇原文。
- `/tmp/nitrogen-preseal-review/`：隔离构建、HTTP 实验脚本、完整审计 JSON、浏览器 trace 和截图。临时目录可能被清理，关键结论以上述仓库内证据为准。
