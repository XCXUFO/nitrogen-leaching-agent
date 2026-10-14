# Harness 第四批：聊天体验与回归比较

日期：2026-09-29。范围来自用户要求：先完成聊天界面、引用和附件交互，再完成回归与版本比较，供 2026-09-30 验收。

## 交付结果

- 聊天页：固定输入区、独立消息滚动、回到最新、新对话、等待耗时、原请求重试，重试不重复用户消息或历史。
- Markdown：标题、列表、表格、代码块，回答/代码复制；正文已有引用编号可定位同一轮原文并返回回答。
  禁止原始 HTML、远程图片及非 HTTP(S) 外链；代码中的 `[1]` 和未知引用不会被错误转换。
- 附件：拖放/选择单文件、上传进度、待分析/可分析/需修正状态、移除与过期清理。
  单附件 10 MiB，Ctrl/Cmd + Enter 发送且尊重中文输入法组合状态。
- 回归：开发者冻结 1–20 轮执行为基线，保存当时用例、事件、Trace、已有评分。
  当前版本在新执行中按原顺序重放，最多同时两项；支持进度、取消、重启中断标记。
- 比较：左右展示每轮回答、路由、状态、工具、文件证据、引用、错误、耗时及配置版本，标注变化和缺失轮次。
  可打开新执行独立评分；自动重跑不生成专业评分，原记录不覆盖。

自动重跑仅还原提问、清空上下文、移除附件和有登记原件的成功上传。
附件需处于项目范围、指纹与基线一致，单份不超过 10 MiB、整次不超过 64 MiB。
无法复原的附件、人工步骤和上传失败明确受阻，不跳过关键步骤后宣称完成。

## 验证结果

| 检查 | 结果 |
|---|---|
| 后端完整回归 | **315 passed / 4 skipped**；227 条既有依赖警告 |
| 回归/比较新增测试 | **9 项**；多轮冻结、配置变化、原附件及指标继承、受阻、权限、错误保留、重启、输入边界、运行锁和取消 |
| 前端 lint、生产构建、TypeScript | 全部通过；`/`、`/evaluation` 构建成功 |
| 浏览器完整流程 | **5 passed**；聊天 4 项，独立真实后端工作台端到端 1 项 |
| 中文移动端视觉复核 | 390×844，引用定位、表格、代码、底部输入可用，无页面横向溢出；补充定向测试通过 |
| 本机服务 | 健康接口、聊天页、评测页均 200；第四批后端已生效 |
| 实际权限 | 匿名回归接口 401、测试者 403、开发者 200 |
| 实际评分库 | 执行 0、评分 0、回归基线 0，专业审核 pending；未写入虚构专业评分 |

工作台浏览器测试使用 `backend/var/eval/browser-test-20260929.sqlite3` 独立库和合成身份，
仅验证保存/重跑/评分流程；其中的合成评分不属于实际评测。
首次浏览器运行遇到依赖更新后的旧前端进程及测试选择器问题，修正并重启后完整 5 项通过。
截图最初缺少 Linux 中文字体，视觉复核时临时读取本机 Windows 字体；未将字体复制进项目。

浏览器截图在 `/tmp/nitrogen-browser-mobile.png`、`/tmp/nitrogen-browser-evaluation.png`；
前者已用中文字体复核，后者来自首轮无中文字体的流程检查。
它们是临时核验文件，重启后可能清理。

## 当前服务与版本

- 聊天：<http://localhost:3000>；工作台：<http://localhost:3000/evaluation>。
- 构建标识：`harness-04-a37ac54e1c708d73`。
  指纹按排序后的 `backend/src/**/*.py` 路径及字节依次输入 SHA-256，取前 16 位。
- 前端已重启适配更新的依赖；后端已重启，沿用现有数据库、代理与内存保护。
  原临时附件需要重新上传，历史持久化记录保留。
- 新表 `eval_regressions` 和 `eval_replays` 在已有数据库上追加创建，不重写 Case/Review。
- 源码清单见 `implementation-04-manifest.json`。未修改 `.env`，未提交/推送 Git。

## 复现自动检查

后端目录执行 `.venv/bin/python -m pytest`；前端目录执行 `pnpm lint`、`pnpm build`。
浏览器用例需要启动前端，并安装 Playwright Chromium：

```bash
# frontend/；本机浏览器已安装在以下目录
PLAYWRIGHT_BROWSERS_PATH=/tmp/nitrogen-playwright pnpm exec playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=/tmp/nitrogen-playwright pnpm test:browser
```

未设置 `EVAL_TEST_API` 时，工作台用例显式跳过；上面命令仅跑聊天自动用例。
完整 5 项需要独立测试后端。以下在 backend/ 创建仅用于测试的合成身份和临时数据库：

```bash
.venv/bin/python - <<'SETUP'
import hashlib, json, os
from pathlib import Path
p = Path('/tmp/nitrogen-browser-access.json')
token = 'browser-test-developer-token-0000000000000000'
p.write_text(json.dumps({'users': [{'tester_id': 'browser-test', 'role': 'developer',
    'token_sha256': hashlib.sha256(token.encode()).hexdigest()}]}))
os.chmod(p, 0o600)
SETUP
env EVAL_ENABLED=true EVAL_ACCESS_FILE=/tmp/nitrogen-browser-access.json \
  AGENT_TRACE_DB=/tmp/nitrogen-browser-test.sqlite3 AGENT_BUILD_VERSION=browser-test-only \
  RAG_ENABLED=false DEEPSEEK_API_KEY= .venv/bin/python -m uvicorn src.main:app \
  --host 127.0.0.1 --port 8002
```

保持独立测试后端运行，在 frontend/ 另一个终端执行：

```bash
PLAYWRIGHT_BROWSERS_PATH=/tmp/nitrogen-playwright EVAL_TEST_API=http://127.0.0.1:8002 \
  pnpm test:browser
```

不要将合成测试身份配置到实际服务，或把这个测试后端指向实际评分数据库。
聊天浏览器用例使用接口桩；工作台用例请求独立真实后端，覆盖两轮执行、保存基线、重跑、比较及独立评分。
此批未重新运行真实 DeepSeek/RAG 机理生成；第二批真实回答及专业审核快照继续保留。

## 明日验收与边界

按 [11 项体验清单](acceptance-04.md) 试用；原 [10 项专业审核](professional-review-checklist.md) 继续待办。
本批没有自动推定专业结论、PDF 在线预览、自动页码识别、任意附件永久保管或全历史版本部署管理。
版本比较针对冻结执行与当前运行版本；模型随机性、语料和模型文件变化需人工控制及记录。
原系统单 worker、内存附件/会话和有限规则路由边界仍适用。
