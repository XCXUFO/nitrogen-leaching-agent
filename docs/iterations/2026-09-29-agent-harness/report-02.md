# Harness 第二批：分阶段上传与组合回答

日期：2026-09-29。工作目录：`/root/projects/nitrogen-leaching-agent`。
本报告记录第二个可运行增量；第一批报告和旧人工验收标准保持原样。

## 已实现

- 上传只检查格式、可读性和资源限制，返回 pending。首次分析才校验业务字段、单位、
  数值和日序，返回 ready 或带具体诊断的 invalid；普通文献问题不触发附件业务检查。
- 原件在内存暂存，最多 32 份、总量 64 MiB、单件 10 MiB、30 分钟有效期；
  访问时清理过期项。验证后释放原件，缓存摘要或业务错误。同附件并发只验证一次，
  等待/计算期间过期不能恢复有效状态；线程未结束时不提前归还解析槽位。
- 有限语法 COMPOSED 支持“硝态氮最大值是多少，为什么可能这么高？”等问题。
  文件数值沿用确定性工具；一般机理使用一次检索和一次生成。额外时间窗、多指标、
  浓度换算或不支持的要求仍追问，不删去要求后只回答整表极值。
- 文件观察、文献机理和局限分别组织，每条机理关联真实引用与 Evidence ID。
  机理生成不接收文件原件、数值或文件 token。某一步失败时保留成功部分，
  outcome 标明 partial/clarification，Trace 保留失败工具和原因；不能把 HTTP 200 计为全部成功。
- 机理生成必须返回实际片段编号及可匹配摘录。兼容中文 PDF 断行空格，展示摘录取自
  原片段；不容许改字、改数字、删除否定词。参考文献目录增加过滤，不能用题名推断结果。
  作物匹配和目录识别仍是启发式规则，摘录匹配不能替代专业审核。
- 前端显示附件待检查/可分析/需修正、组合任务部分完成，并可展开完整引用摘录。
- `harness_cases.v3.json` 新增 6 条独立目标标准，覆盖 F02/B02/B03 迁移、组合、降级和
  额外要求保护；v1 的 22 条原标准与第一批 v2 保留。没有虚构 Review 或人工通过率。

## 自动验证

| 检查 | 结果 |
|---|---|
| 完整后端回归 | **286 passed / 4 skipped**，227 条既有 Chroma/Pydantic 警告 |
| 前端 ESLint | `pnpm lint` 通过 |
| 前端构建与 TypeScript | `pnpm build` 通过 |
| 差异空白检查 | `git diff --check` 通过 |
| 独立真实表核验，RAG 关闭 | 通过；组合返回 partial，极值/追问/引导/Trace 断言通过 |

重点覆盖延迟验证、原件释放、并发与过期、旧附件隔离、错误单位/非数值/公式/Excel 错误、
组合输入边界、证据关联、作物筛选、文献不可用/引用不实/非法 JSON、中文断行兼容、
禁止改变数值与否定词、文献目录不生成机理。
默认自动测试使用模拟知识服务和内存 Trace，不计入真实服务成功率。

命令（backend 目录）：

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python scripts/run_harness_smoke.py
```

## 真实 RAG/LLM 核验

模型 `deepseek-v4-flash`，本地 `chroma_m16/papers`，重排序关闭，与原核验条件一致。
独立 TestClient 实例加载当前代码；没有重启占用 8000/3000 端口的原服务。
本机直连模型超时，显式使用现有代理后连通；仅覆盖核验进程的配置，没有改 `.env`。

```bash
env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  DEEPSEEK_PROXY=http://127.0.0.1:7890 \
  .venv/bin/python scripts/run_harness_smoke.py --live
```

最终联调记录：
[report.json](../../../backend/var/eval/harness-20260929-091313/report.json)，
同目录 `runs.sqlite3` 保存 4 轮 Trace。
后端源码标识 `harness-smoke-c185fc516b1b9bbc`。

1. 上传真实 `Nbal_out.xls` 得到 pending。
2. 带附件设置“只讨论玉米”并问氮淋失影响因素：KNOWLEDGE 完成。
3. “硝态氮最大值是多少，为什么可能这么高？”：COMPOSED 完成，无 warning。
   文件值 **3.659263849258423 kg N ha-1**，日序 **283**，`Nbal_out!C284/A284`；
   返回 3 条一般机理、2 个引用片段，工具检查/分析/检索均成功。
4. “那最小值呢？”：继承 leak_NO3，值 **0**，首次日序 **2**，**191** 条并列。
5. “1”：DIRECT 完成，没有引用。

脚本用 xlrd 独立读取原表核对数值；原表 SHA-256 未变。
另行读取 SQLite 核对 outcome、作物状态、工具执行和证据关联，全部一致。
使用 PyMuPDF 重新读取原 PDF，3 段摘录均在
`005_liang_2016_catch_maize_greenhouse_n_leaching.pdf` 的 PDF 第 **1、11、11** 页匹配，
结果保存在同目录 `source-check.json`。这只验证来源文字存在，不是专业正确性评分。
本次机理来自同一篇甜玉米填闲研究，不能视为多篇文献交叉验证或本次极值的因果证明。

失败过程也保留，没有从记录中删掉：

- `harness-20260929-090133`：直连模型失败；组合保留数值、标记 partial。
- `harness-20260929-090717`：代理可达，但摘录因中文断行空格未匹配；保守降级。
  定位后增加排版兼容及目录过滤，并重跑完整回归及真实联调。
- `harness-20260929-091432`：关闭 RAG 的独立降级核验通过。

上述记录是开发核验，不能汇总成正式测试集通过率。没有进行同门专业评审或浏览器人工验收。

专业人工复核入口：[10 项清单](professional-review-checklist.md)、
[冻结回答](professional-review-snapshot.md)、[审核记录表](professional-review-results.csv)。

## 下一批与限制

下一批接开发者 Trace 页面、Tester 用例执行与独立 Review 保存，随后完善统计和回归比较。
当前仍没有身份权限、协作评测后台、共享/持久会话、模型语义分类回退、WHCNS 执行、
完整 Markdown/聊天布局和引用浮层。规则只支持明确的组合句式，不能声称任意复杂请求均可完成。

源码已更新，原 8000 端口后端仍需在切换演示版本时重启；本次真实联调使用的是独立新实例。
未修改原论文或真实表，未提交或推送 Git。
