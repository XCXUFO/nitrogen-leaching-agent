# V2.1 二期：历史会话侧边栏

需求日期：2026-10-13。

## 交互调整

- 移除顶部横向历史标签，历史会话改为左侧纵向列表，当前会话高亮、长标题省略，悬停可查看完整标题。
- 电脑端（768px 起）默认展开侧栏，支持收起和重新打开；收起后聊天区域使用释放出的宽度。
- 手机端默认隐藏侧栏，点击左上角图标打开抽屉。选择会话、新建、点击遮罩、点击收起按钮或按 Escape 均可关闭；抽屉内支持键盘焦点循环，关闭后恢复触发按钮焦点。切换到桌面宽度时关闭手机抽屉。
- 界面只保留“新对话”“最近对话”等简洁文案，不常驻展示保留数量、容量上限或刷新清空说明。
- 创建超限会话时才在输入区下方提示，避免侧栏隐藏时漏看；提示数字读取 `CONVERSATION_LIMIT`，扩容时无需修改文案中的数字。
- 继续沿用一期消息、草稿、附件和重试上下文恢复逻辑。输入框按实际内容和宽度自动增高，达到既有高度上限后内部滚动。

会话仍仅保存在当前页面内存中，刷新、关闭或离开页面后清空。本次不改变一期存储边界。

交互参考：ChatGPT 的[历史会话侧栏](https://help.openai.com/en/articles/10056348-finding-your-chats-projects-and-files-in-chatgpt)，Claude 的[左侧历史列表](https://support.claude.com/en/articles/8230524-delete-or-rename-a-conversation)。断点、抽屉关闭方式和简化文案按本项目需求确定。

## 实现

- `frontend/src/components/chat/chat-shell.tsx`：桌面侧栏、手机抽屉、导航按钮及页面布局。
- `frontend/src/app/page.tsx`：接入布局，并将超限提示放在输入区。
- `frontend/src/components/chat/use-conversations.ts`：导出会话类型，容量提示读取统一常量。
- `frontend/tests/conversation-history.spec.ts`：补充桌面布局、收起展开、移动端默认隐藏、抽屉关闭和焦点、无溢出、上限提示时机检查。

## 验证

- `pnpm lint`、`pnpm exec tsc --noEmit`、`git diff --check` 通过。
- `NITROGEN_NEXT_DIST_DIR=.next-candidate pnpm build` 通过。
- 浏览器回归中 `tests/chat.spec.ts` 的 16 项和 `tests/conversation-history.spec.ts` 的 8 项全部通过，使用模拟接口。
- 同一批次额外包含 `tests/public-demo.spec.ts`：首个真实示例用例停留在“正在准备示例”并超时，余下 3 项因 `--max-failures=1` 未执行。因此不宣称真实后端端到端验证通过。
- 已检查桌面、手机抽屉和 320px 手机聊天截图。测试容器缺少中文字体，截图中文字显示为缺字方框；中文文案与可访问名称由浏览器断言验证，截图仅用于确认布局。
- 本次完成本地代码、候选构建及验证，未部署。
