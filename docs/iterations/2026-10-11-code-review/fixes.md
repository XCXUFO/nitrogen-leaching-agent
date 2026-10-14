# 审查问题修复与交付（2026-10-11）

本次修复原审查确认的全部 5 项问题。

## 改动

1. **XLSX 漏行**：预扫描工作表实际行列坐标，按实际范围读取，不信任 `<dimension>`。保留实际矩形范围和单元格数量限制，异常稀疏工作表在分配大数组前拒绝。覆盖范围过小、缺少范围、范围过大和极大行列号。
2. **协作覆盖**：数据库新增单调递增 `revision`，更新必须提交 `expected_revision`（兼容返回记录的 `revision`）。在写事务内检查；过期返回 409，缺少版本返回 422。冲突发生在文件替换和标签写入之前。停用、恢复、删除也递增版本。页面保留输入，确认后可加载最新记录重新编辑。
3. **慢上传覆盖标题**：上传成功通过函数式状态更新读取最新标题，仅为空时填入文件名；取消编辑时终止上传，过期回调不再更新表单。
4. **日期漏查**：显示和筛选统一使用北京时间 `Asia/Shanghai`；对 UTC 时间转换后的本地日期做包含起止日的筛选；非法日期和倒置区间返回 422。
5. **过期启动清单**：默认清单更新，绑定源码、前端构建文件、BUILD_ID、构建目录和 API 地址。新增 `--check`，启动前检查端口，启动后验证健康，失败清理本次子进程；保留现有业务环境配置。

## 验证

- 完整后端非联网回归：**431 passed, 3 skipped, 1 deselected**。227 条现有 Chroma/Pydantic 弃用警告。
- 另行运行既有数据库版本字段迁移及交付校验测试：**6 passed**（其中交付 5 项也已包含于上述完整回归，迁移用例为随后追加）。
- 前端 `tsc --noEmit`、`eslint src`、Next 生产构建通过。
- 浏览器：慢上传手填标题保留、冲突输入保留/取消加载/确认加载最新版本、公开文献流程、公开标签流程、移动端 showcase，共 **5 passed**。
- 浏览器新增用例首次运行发现模拟响应缺少关联文献列表，以及定位器匹配 Next 路由播报元素；修正测试设置后全部通过。
- `git diff --check` 通过。

## 正式数据与交付

- 切换前备份：`backend/var/literature-backups/pre-review-fixes-20261011/`，校验 **90 条记录、90 个 PDF**。
- 新服务已通过默认 `start_delivery.py` 启动，前后端健康检查通过。
- 对照备份：90 条记录的所有原字段、标签关联、维度、标签和操作日志完全相同；仅新增 `revision=1`。
- 交付版本：`delivery-20261011-2f8e42857a01`。
- 清单：`docs/iterations/2026-09-29-agent-harness/delivery-source-manifest-2026-10-11.json`，243 个源码/测试/资源文件。
- 构建目录 `.next-candidate`；前端端口 3000，后端 8000；API 转发 `http://127.0.0.1:8000`。
- 启动前、启动后均通过 `backend/.venv/bin/python backend/scripts/start_delivery.py --check`。

```bash
# 在仓库根目录；已运行时先停止旧进程，避免端口冲突。
backend/.venv/bin/python backend/scripts/start_delivery.py --check
backend/.venv/bin/python backend/scripts/start_delivery.py
```

后续修改代码须重新构建、生成新命名的交付清单；当前清单会拒绝源文件或构建产物不一致的启动。详细操作见 `backend/README.md`。

## 切换后只读验收

`LITERATURE_MIGRATION_CHECK=1` 的浏览器验收在正式 3000 端口通过（**1 passed**）：多个现有账号均能看到全部 90 篇全局文献，逐一下载的 90 个 PDF SHA-256 与迁移报告一致；列表、详情、预览和编辑入口可用。该验收未保存或更改任何正式记录。连同候选版本的 5 项浏览器回归，共 6 项通过。
