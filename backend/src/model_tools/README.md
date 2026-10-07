# 模型文件工具

首个工具：WHCNS 氮/水平衡结果读取器。纯本地解析，不调用 LLM、不执行 WHCNS。
已通过 `/api/files` 上传和 `/api/chat` 附件字段接入同一个网页对话窗口。
网页支持整表单字段极值和对应日序；CLI 继续提供完整列统计。

## 依赖

新环境安装 `uv sync --extra model-tools`；需要原 RAG 能力时同时加 `--extra rag`。
资料清单脚本还需要 RAG extra 中已有的 PyMuPDF。
现有环境不必为了读取 Excel 同步大型 RAG 权重或计算依赖，可仅安装锁定的小型读取包：

```bash
cd backend
uv pip install --python .venv/bin/python xlrd==2.0.2 openpyxl==3.1.5 et-xmlfile==2.0.0
```

项目通过 `model-tools` extra 和 `uv.lock` 登记依赖；以下命令直接使用已准备的环境。

## 读取已接收结果

在 `backend/` 运行：

```bash
.venv/bin/python scripts/read_whcns_results.py \
  ../data/raw/whcns/received-2026-09-26/package/模型/Nbal_out.xls \
  --kind nitrogen

.venv/bin/python scripts/read_whcns_results.py \
  ../data/raw/whcns/received-2026-09-26/package/模型/waterbal_out.xls \
  --kind water
```

不带 `--out` 时输出 JSON；加 `--out var/model_tools/<新运行标识>/nitrogen.json`
保存报告，已有文件不覆盖。错误返回结构化 JSON 到 stderr，退出码 2。

输出包括文件 SHA-256、工具/字段规则版本、检测格式、工作表、日序范围、
各列单位、首末值、最小/最大值及单元格、数值列求和与对应范围。
`raw_column_sum` 只是逐行算术和；日值/累计值含义及时间范围未经确认，
不能直接称为季节或年度总量。不对某列净变化为负自行判错。

当前严格支持本次收到的 `Nbal_out` 与 `WtaBal_out` 字段结构。
其他版本的工作表名、新增字段或单位变化需先审核并扩展规则；不静默丢列或转换单位。
缺值、重复列、缺单位、非数值、断裂/重复日序和 Excel 错误均返回具体问题。
按文件内容区分 XLS/XLSX，兼容本包中扩展名不符的 rosetta 文件的结构读取。
XLS 使用保存的值（包括可能的公式缓存），不会重算公式；XLSX 结果表中的公式不当数值接受。

## 资料清单与手册逐页文本

先保留原 ZIP/PDF，并将已检查目录的 ZIP 解包至原件目录的 `package/`。
对本次材料，在 `backend/` 运行：

```bash
.venv/bin/python scripts/inspect_whcns_materials.py \
  --raw-dir ../data/raw/whcns/received-2026-09-26 \
  --out ../data/processed/whcns/<新运行标识>
```

输出 `manifest.json` 和 `manual.pages.json`。清单核对解包工作簿与 ZIP 哈希，
记录档案时间、真实格式、工作表及前三行预览；手册按 PDF 页序提取。
这些是本地处理产物，不自动入 RAG，也不代表专业审核完成。

原件保存在 `data/raw/`，提取内容在 `data/processed/`，工具报告在 `backend/var/`，
都受现有 Git ignore 规则保护。公开展示范围确认前，不将原件或全文复制到前端静态目录。

## 验证

```bash
.venv/bin/python -m pytest -q tests/test_whcns_results.py
```

测试使用合成表格，覆盖单位/缺项/公式/错误值/日序检查、定位、XLSX 误标扩展名、
两种结果结构、CLI 错误和防覆盖。真实 XLS 通过本地材料独立核对，不将案例原件加入测试仓库。

## 聊天上传接口

`POST /api/files?filename=Nbal_out.xls`，请求体为原始字节，Content-Type 为
`application/octet-stream`；返回 `file_id`、文件名、类型、行数和有效期。
将 `file_id` 与 `query` 一起发送至原 `/api/chat` JSON 接口。
文件回答返回 `route=file` 和独立 `file_evidence`；需追问时 `route=clarification`，
无附件的一般知识问答维持 `route=knowledge` 和原论文 citations。

安装 `model-tools` extra 后，文件链路无需 DeepSeek key 或 RAG 配置。
使用单个 uvicorn worker；内存摘要最多 32 份，每份 30 分钟，重启即失效。
文件上传上限 10 MiB，临时原件解析后删除；摘要不会上传给 LLM。
随机 ID 是临时访问凭据，不能当作用户身份认证。刷新页面需重新上传。
