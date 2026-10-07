import type { Evaluator } from "./evaluation-api";

export const evaluationModules = [
  { key: "overview", title: "工作台总览", group: "工作台", description: "查看评测进展，继续当前工作。", roles: ["developer", "tester", "reviewer"] },
  { key: "tasks", title: "任务管理", group: "评测管理", description: "组织用例版本，跟踪执行和评分进度。", roles: ["developer", "tester", "reviewer"] },
  { key: "cases", title: "用例库", group: "评测管理", description: "维护测试步骤、通过标准和用例版本。", roles: ["developer", "tester", "reviewer"] },
  { key: "executions", title: "执行记录", group: "评测管理", description: "按用例完成测试，保存回答、证据和评分。", roles: ["developer", "tester", "reviewer"] },
  { key: "regressions", title: "回归对比", group: "评测管理", description: "保存基线，重跑并核对版本差异。", roles: ["developer"] },
  { key: "reviews", title: "审核队列", group: "质量管理", description: "分派独立审核，记录依据与分歧处理意见。", roles: ["developer", "reviewer"] },
  { key: "issues", title: "问题管理", group: "质量管理", description: "跟踪问题处理、修复版本和复测结果。", roles: ["developer"] },
  { key: "assets", title: "资产目录", group: "资料与证据", description: "登记资料来源、文件指纹和模型输入输出配对。", roles: ["developer", "reviewer"] },
  { key: "runs", title: "运行记录", group: "资料与证据", description: "查看问答运行、工具调用与证据明细。", roles: ["developer"] },
] as const;

export type EvaluationModule = typeof evaluationModules[number]["key"];
export const canViewModule = (key: string, role: Evaluator["role"]) =>
  evaluationModules.some((item) => item.key === key && (item.roles as readonly string[]).includes(role));
export const evaluationHref = (module: string, id?: string) => `/evaluation/${module}${id ? `/${encodeURIComponent(id)}` : ""}`;
