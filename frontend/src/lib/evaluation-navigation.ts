import type { Evaluator } from "./evaluation-api";

export const evaluationModules = [
  { key: "overview", title: "工作台总览", group: "工作台", roles: ["developer", "tester", "reviewer"] },
  { key: "literature", title: "文献管理", group: "资料与证据", roles: ["developer", "tester", "reviewer"] },
  { key: "case-library", title: "案例与措施", group: "资料与证据", roles: ["developer", "tester", "reviewer"] },
  { key: "starred-questions", title: "星标问题", group: "资料与证据", roles: ["developer", "tester", "reviewer"] },
  { key: "literature-tags", title: "标签管理", group: "资料与证据", roles: ["developer", "tester", "reviewer"] },
  { key: "tasks", title: "任务管理", group: "评测管理", roles: ["developer", "tester", "reviewer"] },
  { key: "cases", title: "用例库", group: "评测管理", roles: ["developer", "tester", "reviewer"] },
  { key: "executions", title: "执行记录", group: "评测管理", roles: ["developer", "tester", "reviewer"] },
  { key: "regressions", title: "回归对比", group: "评测管理", roles: ["developer"] },
  { key: "reviews", title: "审核队列", group: "质量管理", roles: ["developer", "reviewer"] },
  { key: "issues", title: "问题管理", group: "质量管理", roles: ["developer"] },
  { key: "assets", title: "资产目录", group: "资料与证据", roles: ["developer", "reviewer"] },
  { key: "runs", title: "运行记录", group: "资料与证据", roles: ["developer"] },
] as const;

export type EvaluationModule = typeof evaluationModules[number]["key"];
export const canViewModule = (key: string, role: Evaluator["role"]) =>
  evaluationModules.some((item) => item.key === key && (item.roles as readonly string[]).includes(role));
export const evaluationHref = (module: string, id?: string) => `/evaluation/${module}${id ? `/${encodeURIComponent(id)}` : ""}`;
