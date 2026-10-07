# 简历公开 Demo

本轮目标：陌生访客无需账号即可真实体验 C 端、浏览评测过程；公开浏览不能修改评测数据，也不能读取其他访客的对话。公开域名可以保持不变，后续发布替换其背后的构建。

## 入口与权限

| 入口 | 行为 |
| --- | --- |
| `/` | 文献问答、上传、示例表一键加载并实际计算、连续追问 |
| `/showcase` | 免登录只读后台，含用例、任务流程、运行、评分边界、问题与回归、材料 |
| `/evaluation` | 保留原管理入口和三种身份权限，需要私有密钥 |
| `/api/demo/catalog` | 仅返回公开快照，不查询运行数据库 |
| `/api/demo/examples/nitrogen` | 只提供指定的氮平衡示例文件 |

访客不是 developer/tester 账号。公开 API 没有写入接口，原 `/api/eval` 继续强制认证。展示页面只请求 `/api/demo`，不能通过修改 URL 获取正式记录。公开快照变更由代码发布完成，不提供网页发布接口。

## 数据与真实性

`data/demo/catalog.json` 由 `backend/scripts/build_demo_catalog.py` 从两个明确选定的历史证据文件投影生成。脚本不读取正式数据库，只选择展示需要的字段，不输出访问身份、运行配置、内部绝对路径、会话及附件令牌。

- 4 个能力案例来源于保存的真实工程运行；未新增人工评分或专家结论。
- 1 个问题闭环来自隔离浏览器流程测试，fail/pass 明确标注合成评分，不能用于准确率或修复效果宣传。
- 文献回答保留题名与短摘录，标注 AI 辅助整理、专业审核待完成。
- `data/demo/Nbal_out.xls` 与原示例指纹一致；前台下载后走现有上传、解析和分析接口，不返回预写答案。
- `data/demo/waterbal_out.xls` 是可复现生成的合成水表，仅供自动测试；它不是收到的原始模型输出，也不进入公开示例下载接口。生成脚本为 `backend/scripts/build_synthetic_water_fixture.py`。
- 历史示例与实时回答区分。正式访客聊天继续进入私有 Run 库，但不会进入公开快照。

更新快照：先在维护环境恢复选定的历史证据文件，再在仓库根执行 `python3 backend/scripts/build_demo_catalog.py`，检查生成内容、来源和指纹后随新构建发布。历史证据文件不随公开源码分发。不要把正式库全量导出到公开目录。

## 公开部署配置

后端需启用：

```dotenv
PUBLIC_DEMO_ENABLED=true
PUBLIC_COOKIE_SECURE=true
CORS_ORIGINS=https://你的域名
PUBLIC_REQUESTS_PER_MINUTE=12
PUBLIC_DAILY_CHAT_LIMIT=300
PUBLIC_MAX_CONCURRENT=5
PUBLIC_MAX_OUTPUT_TOKENS=2048
PUBLIC_BUDGET_DB=var/demo/budget.sqlite3
```

使用 HTTPS、单个后端 worker。限额是每个来源 IP 每分钟的聊天/上传合计、全站每日聊天请求数和当前并发数。每日额度按 UTC 换日，失败请求也计入；SQLite 持久化日额度与访客签名密钥，重启不清零。额度是用量限制，不等于供应商的精确金额预算；一次组合回答和供应商重试可能产生多次调用。

公开模式用签名 HttpOnly Cookie 标识访客，忽略请求正文中的访客身份，将会话 ID 按访客隔离，并将上传附件绑定到该访客。重启后临时附件仍需重新上传。生产环境应保持同源；仅本机 HTTP 测试设 `PUBLIC_COOKIE_SECURE=false`。

前端：

```dotenv
NEXT_PUBLIC_API_BASE_URL=
BACKEND_INTERNAL_URL=http://127.0.0.1:8000
```

空的公开 API 地址表示同源，避免浏览器访问面试官电脑的 localhost。Next 提供内部 API 转发供本地/简单部署使用。生产反向代理宜将 `/api/` 直接转发后端，并仅信任该代理注入的客户端地址；应用本身忽略任意 `X-Forwarded-For`。若全部请求经 Next 转发且未配置可信代理，限频会合并为代理 IP，限制更保守而非失效。不要将 Uvicorn 的代理信任范围设为所有公网来源。

前端生产构建可使用独立目录，避免覆盖现有服务：

```bash
cd frontend
NITROGEN_NEXT_DIST_DIR=.next-demo pnpm build
NITROGEN_NEXT_DIST_DIR=.next-demo pnpm start
```

构建时的后端转发地址应与实际部署一致。本轮验证构建指向临时 8006 端口，部署正式服务时需按目标地址重新构建。

## 对外上线前的交付检查

1. 配置正式域名、HTTPS、进程守护和重启恢复；从外网及手机访问。`backend/scripts/start_delivery.py` 是本机脚本，绑定 `127.0.0.1` 并覆盖代理、重排与评测设置，不能直接当作公网启动配置。
2. 配置可用的模型服务、RAG 索引和本地模型。后端启动后请求 `GET /api/health` 检查进程，再请求 `GET /api/ready`；公开模式下后者在知识服务初始化失败时返回 503。随后执行一次真实文献问答并核对引用，因为就绪接口不能验证外部模型 API 与回答质量。本轮隔离浏览器服务不调用外部模型，不证明线上模型连通性。
3. 保留私有评测数据及密钥，启用公开保护，检查管理接口拒绝匿名写入、Cookie 为 Secure。
4. 备份私有数据库、公开预算库和原始资产；发布前冻结源码与构建，失败时恢复上一构建。`backend/scripts/create_delivery_manifest.py` 可为工作区代码、锁文件、公开示例与展示数据生成 SHA-256 清单。模型权重、Chroma 索引和论文 PDF 不在 Git 或该清单内，需单独核对并传输。
   历史人工验收中的原始水表及其他私有原件也不随 Git 分发；要重放这些历史用例，需单独恢复原件并核对冻结指纹。
5. 公开后台核对所有合成评分与专业待审核标识；简历描述不把工程重放称为专家准确率。

暂未建设：完整注册系统、多进程共享的分钟/并发限流、自动从案例学习、专业审核自动通过。公网部署参数仍取决于实际服务器与域名，本轮不假定已有公网环境。
