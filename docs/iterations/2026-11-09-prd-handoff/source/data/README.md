# 离线数据使用说明

本目录是交接格式，未验证为线上导入格式。导入隔离本地数据库，保留生产来源标识，不能向生产写入模拟记录。

## 1. 四份 JSON 怎样对应

- reviewed-cases.json：8 个用例定义、原审核、目标输入与历史、原路径、验收草案；是本次回归集定义来源。
- baseline-answers.json：8 条原会话的全部21轮可见问题与回答、每轮原Run；用于展示和原答案对照。
- legacy-case-catalog.json：旧目录34个发布版本、27个编号；是目录快照，不是全部机器脚本。
- online-observations.json：线上界面核对记录和7项能力；属于事实依据，不是可直接执行的配置。

前两份以records[].id连接。FIX-01等是本包整理编号，不是线上用例编号。source_session_id是原会话标识；source_run_id或baseline.run_ids是具体轮次运行标识，不能互换。source_url只是溯源链接，本地页面读取JSON即可。

## 2. 生成本地复现脚本

reviewed-cases中evaluation_mode为single_turn时，用user_input加seed_history复现目标。FIX-05应为第二轮，seed_history含2条消息；不要使用其标题“上岸”替代目标输入。除该固定历史复现外，不擅自从原完整会话加上目标之前未要求的消息。

KEEP-03按user_turns顺序，使用每轮新回答形成下一轮历史；不要注入baseline-answers中的旧回答假装新运行。baseline-answers里的is_evaluation_target共10个目标轮次，归属8个会话用例；其余轮次保留作定位，并不自动获得通过/失败结论。

本包5个修复项的旧回答为反例对照，不作合格few-shot示例。3条通过会话保留审核结论，但不要求逐字复现，也不自动证明每个数值均经过专业核验。所有new_run_ids为空、new_result为未运行，导入时保持这一点。

## 3. 原回答的保真范围

assistant_visible_text来自已登录页面可见正文抄录，段落/列表排版规范化，不是数据库原始消息或Markdown源码。引用序号按原文保留；原来源映射及已读对象线索见evidence/会话来源索引.md。论文、案例正文与完整检索片段未随包导出。

KEEP-01/03的范围数字有可见渲染疑点，已在rendering_caveats中记录；不要把“23”当有效农业频次，也不要擅自恢复成某个范围。新验收回到真实案例正文核对。

## 4. 当前版本和历史

legacy-case-catalog保留同编号多版本。readable_definition_summary_in_bundle为true只表示有可读定义与标准快照，不表示原机器脚本和附件已齐全。当前使用版本应在本地从有效版本选择后保存指针，不自动跑同编号所有旧版。

不能把原会话通过属性直接导入成候选执行已通过。原审核、候选质量结果、技术状态与实际上线状态分开保存；缺失旧配置用unknown/missing_fields，不拿当前值补写历史。

## 5. 幂等与校验

建议以包版本+来源会话+目标轮次/多轮脚本标识建立幂等映射。保留原审核文案、作者和已知时间；未知时间留空。导入两次不产生重复问题和用例，不覆盖本地后续验证尝试。

根目录manifest.json列出文件与SHA-256校验值；整包移动后可据此检查文件是否完整。包内不含线上凭证、完整数据库或生产部署配置。
