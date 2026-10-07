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
可在同一个输入框附加 WHCNS 氮/水平衡输出表，再询问明确字段的极值及日序。
后端安装 `model-tools` extra 即可使用文件链路，文献问答仍需 RAG。
附件属于当前会话，所有有效文件随提问发送，由后端遍历并查找相关字段；支持一次分别查询多张表的极值。发送前可移除附件，发送后“收起文件”只隐藏卡片，仍可继续引用，也可展开。新对话清空文件与历史；刷新、过期或重启后需重新上传。
上传按内容 SHA-256 去重（包括改名副本），相同文件自动跳过并提示；同名不同内容保留摘要区分。平时不展示容量和有效期长说明，只在超限、失效时提示。
可带着附件直接问文献，也可问“硝态氮最大值是多少，为什么可能这么高？”；
组合链路部分失败时显示“部分完成”，保留已得到的结果。
回答支持 Markdown 表格、代码及复制；正文完整展开，文献和文件依据默认折叠。文献按篇去重，展示实际引用的文章标题、作者、年份及摘录，编号按正文首次出现顺序从 1 开始，未引用的检索候选不展示；点击正文引用可展开并定位到对应文献，再返回回答。原文支持弹窗预览和下载，缺失时明确提示；复制成功后按钮变为“已复制”，1 秒后恢复“复制回答”，失败时明确反馈。

文献展示元数据来自 `data/papers/catalog_m16.json` 和已有作者标签，缺失字段显示“暂缺”。后端 `/api/documents/{document_id}` 仅提供目录内的本地 PDF，`?download=true` 使用下载响应；PDF 不随代码入仓，部署时需要保留原文目录。
输入框支持拖放多个附件和上传进度；Enter 换行、Ctrl/Cmd + Enter 发送，兼容中文输入法。
等待时显示耗时，失败后可以重试原问题；“新对话”清空当前上下文。
健康检查使用开发工具访问 `${NEXT_PUBLIC_API_BASE_URL}/api/health`，普通界面不展示调试信息。

`/evaluation` 为独立评测工作台。测试者按版本化用例执行、提交评分，开发者查看 Trace
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
