# data/papers/

论文语料目录。

## 用途

- `backend/scripts/index_papers.py` 离线索引脚本的输入源
- `backend/tests/test_index_pipeline.py` / `tests/test_rag_live.py` 的 fixture

## 文件约定

| 文件 | 入仓 | 用途 |
|---|---|---|
| `sample.txt` | ✅ | 仓库内冒烟用真实主题文本（约 1.5 KB），不可删除 |
| `README.md` | ✅ | 本文件 |
| `*.pdf` | ❌ | 论文 PDF 受版权保护，**绝不入库**（已在 .gitignore 中排除） |

## 命名建议

PDF 入本地后建议命名为 `{author}_{year}_{topic_short}.pdf`，例如：

```
data/papers/wang_2024_whcns.pdf
data/papers/li_2023_n_leaching.pdf
```

`document_id` 由索引脚本按"相对仓库根的路径去后缀 + 字符规范化"生成（见
M1.2.3 spec §3.6.1），所以重命名 PDF 等于重建 chunk_id；如需更名，
建议清空 collection 再重跑索引。

## 索引

```bash
cd backend
uv sync --extra rag                                  # 首次需要
uv run python scripts/index_papers.py \
  --paths ../data/papers/sample.txt \
  --persist-dir var/chroma \
  --collection papers \
  --repo-root ..
```
