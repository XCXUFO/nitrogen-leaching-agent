export type DemoCase = {
  id: string; title: string; body: string; body_format?: "plain" | "html"; explanation: string; source: string; enabled: boolean; tags: string[];
};
export type DemoQuestion = { id: string; question: string; answer: string };
export type DemoReceipt = {
  id: string; kind: string; aiExtract?: boolean; aiTag?: boolean;
  items: { id: string; title: string; status: string; href?: string }[];
};
export const initialDemoCases: DemoCase[] = [
  { id: "CASE-SAMPLE-001", title: "冬小麦水氮协同管理（合成示例）", body: "场景：广西示范县冬小麦田。措施：分次施氮，结合土壤水分安排灌溉，持续记录排水与氮素变化。此文本只演示资料整理，不提供施用量或效果结论。", explanation: "把施肥与灌溉安排放在一起核对，结合当地土壤和作物阶段判断适用条件。", source: "为展示工作台编写，不对应真实田间试验。", enabled: true, tags: ["leaching", "wheat", "sample-county"] },
  { id: "CASE-SAMPLE-002", title: "水稻养分管理（合成示例）", body: "场景：广西桂林水稻田。措施：记录田面水分和作物生育阶段，再结合监测资料调整水肥管理。缺少对照试验与效果数据。", explanation: "重点是根据水稻田场景核对措施，不能直接照搬冬小麦管理安排。", source: "为展示工作台编写，不对应真实田间试验。", enabled: false, tags: ["efficiency", "rice", "guilin"] },
];
export const initialDemoQuestions: DemoQuestion[] = [
  { id: "STAR-SAMPLE-001", question: "模型日序能否直接作为日历日期？", answer: "需要模型起始日期及日序定义才能换算。此处是人工整理答案的合成示例，星标记录不会自动成为 Agent 检索材料。" },
];

// Fixed suggestions demonstrate review and save behavior; they are never presented as live AI output.
export const demoPaperSuggestions = {
  authors: "示例作者甲；示例研究团队", venue: "示例学术期刊", year: "2025",
  abstract: "围绕农田水分与氮素管理整理研究问题和观测指标。此摘要为合成流程示例。",
  conclusion: "措施应用前需核对地区、作物、土壤与试验依据，不据此推断实际减排效果。此结论为合成流程示例。",
};
export function demoSuggestedTags(text: string): string[] {
  return /水稻/.test(text) ? ["efficiency", "rice"] : /小麦/.test(text) ? ["leaching", "wheat"] : ["water-n"];
}
