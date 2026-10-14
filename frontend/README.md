# Frontend — 农业模型助手

Next.js 16 (App Router) + TypeScript + Tailwind 4 + shadcn/ui。

## 本地启动

```bash
# 安装依赖
pnpm install

# 复制环境变量示例
cp .env.local.example .env.local

# 启动开发服务器（Turbopack）
pnpm dev
```

打开 <http://localhost:3000>，输入问题后查看带引用的回答。
可在同一个输入框附加 WHCNS 氮/水平衡输出表，查询字段极值和日序；也可上传
`.txt/.md/.pdf/.doc/.docx` 文档，在后续对话中引用其中的文字。单会话最多 10 份文件，
文件卡片横向滚动。结果表分析需要后端 `model-tools` extra，文档问答需要 LLM。
附件属于各自对话，所有有效文件随该对话的提问发送。发送前可移除附件，发送后“收起文件”只隐藏卡片，仍可继续引用；新建或切换对话保留原对话附件。对话超出历史上限被移除、离开聊天页面、刷新或关闭页面时释放文件。活动页面为全部保留对话的附件定时续期，失联文件由后端清理。
上传按内容 SHA-256 去重（包括改名副本），相同文件自动跳过并提示；平时只展示文件名与上传状态，失败时显示原因。
可带着附件直接问文献，也可问“硝态氮最大值是多少，为什么可能这么高？”；
组合链路部分失败时显示“部分完成”，保留已得到的结果。
回答支持 Markdown 表格、代码及复制；正文完整展开，文献和文件依据默认折叠。文献按篇去重，展示实际引用的文章标题、作者、年份及摘录，编号按正文首次出现顺序从 1 开始，未引用的检索候选不展示；点击正文引用可展开并定位到对应文献，再返回回答。原文支持弹窗预览和下载，缺失时明确提示；复制成功后按钮变为“已复制”，1 秒后恢复“复制回答”，失败时明确反馈。

文献展示元数据来自 `data/papers/catalog_m16.json` 和已有作者标签，缺失字段显示“暂缺”。后端 `/api/documents/{document_id}` 仅提供目录内的本地 PDF，`?download=true` 使用下载响应；PDF 不随代码入仓，部署时需要保留原文目录。
输入框支持拖放多个附件和上传进度；Enter 换行、Ctrl/Cmd + Enter 发送，兼容中文输入法。
等待时显示耗时，失败后可以重试原问题；“新对话”创建独立上下文，原对话可从历史列表切回并继续提问。
V2.1 在当前聊天页面内最多保留 10 个对话（含当前对话），按最近打开顺序排列。历史会话位于左侧栏：电脑端默认展开、可收起，手机端默认隐藏、点击左上角图标打开；手机端选择或新建后自动关闭，也支持点击遮罩或 Escape 关闭。
界面不常驻展示数量上限或存储范围说明，只有创建超限对话时才提示，并移除最早使用的对话；提示数字使用统一容量配置。输入框随内容和可用宽度自动调整高度。
消息、回答依据、附件及收起状态、输入草稿和失败重试状态随对话保留；未发送的草稿或附件也可保留，重复点击“新对话”不会创建多个空白记录。
发送、上传或准备示例期间暂不可切换对话。记录保存在页面内存，刷新、关闭、离开聊天页面或切换登录身份后清空；本期不提供跨页面、跨窗口或账号历史同步。
健康检查使用开发工具访问 `${NEXT_PUBLIC_API_BASE_URL}/api/health`，普通界面不展示调试信息。

`/evaluation` 为独立评测工作台，使用分配的账号和密码登录，后端自动识别角色，暂不开放注册。测试者按版本化用例执行、提交评分，开发者查看 Trace
及统计，也可冻结回归基线、自动重跑和逐轮比较；需后端启用 `EVAL_ENABLED` 并分配访问密钥。
密钥只保存在页面内存。
参见 [工作台说明](../docs/iterations/2026-09-29-agent-harness/evaluation-guide.md)。

## 启动 chat 完整闭环（M1.3 起）

前提：后端启用 RAG，并已建好向量索引。

```bash
# 1. 后端：装 rag extra
cd backend && uv sync --extra rag

# 2. 后端：建索引（首次或资料更新时跑）
uv run python scripts/index_papers.py \
    --paths ../data/papers/sample.txt \
    --persist-dir var/chroma --collection papers --repo-root ..

# 3. 后端：backend/.env 设
#    DEEPSEEK_API_KEY=sk-...
#    RAG_ENABLED=true
#    RAG_CHROMA_DIR=./var/chroma

# 4. 后端：启动
uv run uvicorn src.main:app --reload

# 5. 前端
cd ../frontend
cp .env.local.example .env.local
pnpm dev
```

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | 后端地址（末尾斜杠会自动剔除） | `http://localhost:8000` |

## 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 错误条 `请求未发出…`（code=`network`） | 后端未启动 / 端口不通 / VPN 拦了 localhost | 检查 `uvicorn` 是否在跑；樱花猫 VPN 把 `127.0.0.1` 加 ByPass |
| 503 + `rag_not_configured` | 后端 `.env` 没设 `RAG_ENABLED=true` | 改 `.env` 后重启后端 |
| 503 + `rag_query_failed` | chroma 索引目录不对或为空 | 重新跑 `scripts/index_papers.py`，确认 `RAG_CHROMA_DIR` 路径正确 |
| 502 + `llm_unreachable` | DeepSeek 不可达 / 代理设置 | 检查网络与 `DEEPSEEK_BASE_URL` |
| 422 + `输入校验失败` | query 为空白 / 超 1000 字 | 调整输入；前端字符计数变红时已禁用提交 |
| 首次回答等待较长 | BGE 嵌入模型冷加载或模型响应较慢 | 等待区显示已用时间及较长等待提示 |

## 验证

`pnpm lint`、`pnpm build` 检查静态代码及完整构建。
`pnpm test:browser` 使用 Playwright 检查聊天交互；需先启动前端并安装 Chromium。
工作台端到端用例只有设置 `EVAL_TEST_API` 才运行，必须指向独立测试数据库的后端。
完整复现命令见 [第四批实施记录](../docs/iterations/2026-09-29-agent-harness/report-04.md)。

## 目录结构

```
frontend/
├── src/
│   ├── app/                   # 路由（App Router）
│   ├── components/
│   │   ├── chat/              # 多轮聊天、附件、论文引用和文件证据
│   │   ├── debug/             # 开发侧 health 组件（普通页面不挂载）
│   │   └── ui/                # shadcn/ui 原语
│   └── lib/                   # types / api / error-messages / cn
├── public/
└── package.json
```

## shadcn/ui

- baseColor: `slate`
- icon library: `lucide`
- 添加新组件：`pnpm dlx shadcn@latest add <component>`

详细开发流程见仓库根目录的 [docs/development.md](../docs/development.md)。

### 工作台账号登录 V1.0

本机账号凭据：`backend/var/eval/account-credentials.txt`。当前标签页窗口内，前台与工作台共享登录，切换和刷新均会恢复身份；退出会撤销服务端会话。窗口定期续期，关闭后不跨独立窗口保留凭据。历史身份与角色权限保持不变。详见 [前后台共享登录 V1.1](../docs/iterations/2026-10-13-workbench-login/shared-session-v1.1.md)。

隔离工作台浏览器测试需设置 `EVAL_TEST_USERNAME`、`EVAL_TEST_PASSWORD`，测试不再读取正式密钥。新增 `evaluation-accounts.spec.ts` 使用 `ACCOUNTS_TEST_API` 指向 `tests.accounts_fixture`，所有写入均落在 `ACCOUNTS_TEST_ROOT` 临时目录。
