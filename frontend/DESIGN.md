# 管理工作台界面规范

适用于 `/evaluation`。以查询、审核、资料维护为主要任务，优先保证对齐、可读性和信息密度。

## 内容

- 每页保留一个主标题，不增加解释性副标题、口号、装饰性标签或重复模块标题。
- 小标题只用于区分实际内容，例如不同版本的回答、不同组的记录。能够通过位置、分隔线或字段名表达的层级，不再补标题。
- 保留表单标签、表头、记录名称、数量和状态。帮助文字只在需要做决定、处理错误、填写复杂字段时出现。
- 页面不展示实现过程或通用使用说明。原始运行数据收进可展开的明细。

## 设计变量

变量与共用组件定义于 `src/app/evaluation/workbench.css`，限定在 `.evaluation-workspace` 内。

| 用途 | 值 |
| --- | --- |
| 页面底色 | `#f5f7f6` |
| 内容表面 | `#ffffff` |
| 边框 | `#dfe5e1` |
| 正文 | `#24332c` |
| 次要文字 | `#65726b` |
| 主操作 | `#216148` |

- 使用项目已有的 Geist 与系统中文字体。主标题 22px / 32px、600 字重，正文和控件 13–14px，表头与辅助数据 12px。
- 间距使用 4、8、12、16、20、24、28、32px。桌面内容水平边距 28px，手机 16px；同一区块左右边距一致。
- 桌面导航宽 224px，折叠后 64px；顶栏高至少 64px，品牌区与顶栏底线对齐。
- 控件高 36px、圆角 6px；内容面板圆角 8px、内边距 20px，手机 16px。使用细边框，不叠加渐变、阴影或大圆角卡片。

## 共用组件

| 类名 | 用途 |
| --- | --- |
| `wb-panel` | 独立内容表面，不把每个字段都包装成卡片 |
| `wb-button` / `wb-button-primary` | 次要操作 / 主要操作 |
| `wb-field` | 输入框、选择框、文本域；文本域按内容展开 |
| `wb-filter-grid` / `wb-filter-label` | 筛选项底部对齐，操作按钮与输入框对齐 |
| `wb-table-wrap` / `wb-table` | 表格及局部横向滚动区域 |
| `wb-numeric` | 数值列与表头同时右对齐，使用等宽数字 |
| `wb-tabs` / `wb-tab` | 平铺的页签或筛选按钮，不使用一排胶囊卡片 |
| `wb-status` | 状态文本与色点；颜色不作为唯一识别方式 |
| `wb-stat-grid` / `wb-stat` | 同一行统计，不拆成浮动的装饰卡片 |
| `wb-pagination` | 表格底部页数与条数操作 |

- 表格单元格统一上下 12px、左右 16px，表头和内容同列对齐。正文左对齐，数值右对齐。
- 文献标签列固定宽度，按其他列内容形成的实际行高自适应展示，能放下多少就显示多少，不设固定条数，也不由标签撑高记录。只有放不下的标签才收起并显示剩余数量。悬浮、键盘聚焦或点击时，在独立浮窗中显示全部标签；表格里的长标签截断，浮窗中的长标签换行，数量多时在浮窗内滚动，不挤占相邻列。
- 仅在状态与主要操作中使用强调色；普通记录名称用正文色。不要把整块内容染成状态色。
- 筛选和分页继续使用现有 URL 状态。按钮触发操作，链接负责页面跳转。
- 手机端筛选按两列排列，搜索与操作跨两列。表格可以局部横滚，整页不得横向溢出。
- 所有操作具有可见键盘焦点，页签支持方向键和 Home / End；导航抽屉支持 Escape；尊重减少动态效果设置。

## 使用的 GitHub skill

2026-11-13 从官方仓库读取并应用以下 skill：

- [Anthropic frontend-design](https://github.com/anthropics/skills/tree/main/skills/frontend-design)：先确定颜色、字体、布局与对齐规则，再实现和截图复查。这里采用适合科研管理任务的克制布局。
- [Vercel web-design-guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines)：检查控件标签、键盘焦点、表格数值、长内容和响应式布局；[规则原文](https://github.com/vercel-labs/web-interface-guidelines/blob/main/command.md)。

补充阅读以下社区项目的原始 skill 与参考文件：

- [Impeccable](https://github.com/pbakaus/impeccable)：重点阅读 [distill](https://github.com/pbakaus/impeccable/blob/main/skill/reference/distill.md)、[quieter](https://github.com/pbakaus/impeccable/blob/main/skill/reference/quieter.md)、[layout](https://github.com/pbakaus/impeccable/blob/main/skill/reference/layout.md)、[operate](https://github.com/pbakaus/impeccable/blob/main/skill/reference/operate.md)。采用删冗余、减少嵌套、稳定密度、强调色只用于操作和状态等规则。
- [interface-design](https://github.com/Dammyjay93/interface-design)：重点阅读 [SKILL.md](https://github.com/Dammyjay93/interface-design/blob/main/.claude/skills/interface-design/SKILL.md) 与 [design-deslop](https://github.com/Dammyjay93/interface-design/blob/main/.claude/commands/design-deslop.md)。先看实际界面，再检查样式；用对齐、距离和字重建立层级；共用控件避免每页重新设计。
- [Taste Skill](https://github.com/Leonxlnx/taste-skill)：检索时最新版主要面向企业网站和营销页面。这里只参考浏览器验证与边缘对齐的思路，不采用整屏章节、入场效果或视觉实验作为后台规范。

具体检查：重复文案删掉；表格不再套第二层圆角卡片；取消彩色装饰竖线；一页只保留一个主标题；保留数据、字段名、记录名称和必要操作说明。

项目要求与用户偏好优先于 skill 中的通用风格建议。后续页面应直接复用这些组件和变量，不另建一套尺寸。
