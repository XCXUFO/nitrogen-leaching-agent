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

## 索引（sample 冒烟）

```bash
cd backend
uv sync --extra rag                                  # 首次需要
uv run python scripts/index_papers.py \
  --paths ../data/papers/sample.txt \
  --persist-dir var/chroma \
  --collection papers \
  --repo-root ..
```

## 放真实 PDF 并索引（M1.4-a 起）

1. 在本目录放 6–8 篇主题 PDF（命名约定见上：`{author}_{year}_{topic_short}.pdf`）
2. PDF 已被 `.gitignore` 排除，**不会**入库
3. 在 `data/papers/sources.md`（自建，可入库）记录每篇来源，便于答辩追溯：

   ```
   - wang_2024_n_leaching_paddy.pdf — Wang et al., 2024, Agric Water Manag, DOI:10.xxxx/yyyy
   - li_2023_controlled_release.pdf — Li et al., 2023, Field Crops Res, DOI:...
   ```

4. 质量自检：每篇 PDF 用 Ctrl+F 搜中文/英文关键词
   - 能搜到 → 文字版，可用
   - 搜不到 → 扫描版，**别用**（BGE 在 OCR 噪声上召回质量塌方）

5. 切真实数据时建议先清空旧索引（避免 sample chunks 污染评测）：

   ```bash
   rm -rf backend/var/chroma
   ```

   注意：Chroma 持久化结构是 `var/chroma/chroma.sqlite3` + 若干 UUID 目录，
   `papers` 是 **collection 名**而非目录。删整个 `var/chroma` 是最直白的清空方式；
   下次 `index_papers.py` 跑起来会按 `--persist-dir` / `--collection` 自动重建。

6. 重建索引（路径用 glob 展开）：

   ```bash
   cd backend
   uv run python scripts/index_papers.py \
     --paths ../data/papers/*.pdf \
     --persist-dir var/chroma \
     --collection papers \
     --repo-root ..
   ```

7. 索引基线快照（写入 mini eval 报告）：

   ```bash
   cd backend
   uv run python -c "from src.storage import ChromaStore; \
     s=ChromaStore('var/chroma','papers'); print('chunks:', s.count())"
   ```

入库后即可跑 mini 评测，详见 `data/eval/README.md`。
