export type DemoTag = { id: string; dimension: string; name: string; parent: string | null };
export type DemoPaper = {
  id: string; title: string; authors: string; venue: string; year: string; language: string;
  source: string; tags: string[]; registration: "draft" | "registered"; disabled: boolean;
  events: string[];
};
export const demoDimensions = [
  { id: "region", name: "地区", description: "省、市、县逐级组织；选择上级包含全部下级。" },
  { id: "topic", name: "主题领域", description: "示例分类：按论文讨论的问题组织资料。多选，非必填。" },
  { id: "object", name: "研究对象", description: "示例分类：按研究对象缩小查找范围。多选，非必填。" },
];
export const initialDemoTags: DemoTag[] = [
  { id: "guangxi", dimension: "region", name: "广西", parent: null },
  { id: "nanning", dimension: "region", name: "南宁", parent: "guangxi" },
  { id: "guilin", dimension: "region", name: "桂林", parent: "guangxi" },
  { id: "sample-county", dimension: "region", name: "示范县", parent: "nanning" },
  { id: "water-n", dimension: "topic", name: "水氮管理", parent: null },
  { id: "leaching", dimension: "topic", name: "氮素淋失", parent: "water-n" },
  { id: "efficiency", dimension: "topic", name: "利用效率", parent: "water-n" },
  { id: "model", dimension: "topic", name: "模型方法", parent: null },
  { id: "wheat", dimension: "object", name: "冬小麦", parent: null },
  { id: "rice", dimension: "object", name: "水稻", parent: null },
];
export const blankDemoPaper = (): DemoPaper => ({
  id: "", title: "", authors: "", venue: "", year: "", language: "中文", source: "",
  tags: [], registration: "draft", disabled: false, events: [],
});
export const initialDemoPapers: DemoPaper[] = [
  { ...blankDemoPaper(), id: "SAMPLE-001", title: "水氮管理研究笔记（流程示例）", year: "2024", source: "合成示例资料", events: ["示例维护员 · 保存草稿，分类待补充"] },
  { ...blankDemoPaper(), id: "SAMPLE-002", title: "冬小麦氮素淋失研究（流程示例）", authors: "示例作者甲", venue: "示例期刊", year: "2025", source: "合成示例资料", tags: ["leaching", "wheat", "sample-county"], registration: "registered", events: ["示例维护员 · 完成登记", "示例维护员 · 添加主题与研究对象标签", "示例维护员 · 保存草稿"] },
  { ...blankDemoPaper(), id: "SAMPLE-003", title: "水稻养分利用效率研究（流程示例）", authors: "示例作者乙", venue: "示例期刊", year: "2023", source: "合成示例资料", tags: ["efficiency", "rice", "guilin"], registration: "registered", disabled: true, events: ["示例维护员 · 停用：暂不使用", "示例维护员 · 完成登记"] },
];
export function tagPath(tag: DemoTag, tags: DemoTag[]): string {
  const parent = tags.find((item) => item.id === tag.parent);
  return parent ? `${tagPath(parent, tags)} / ${tag.name}` : tag.name;
}
export function includesTag(selected: string, candidate: string, tags: DemoTag[]): boolean {
  let tag = tags.find((item) => item.id === candidate);
  while (tag) {
    if (tag.id === selected) return true;
    tag = tags.find((item) => item.id === tag!.parent);
  }
  return false;
}
