import type { ChatResponse } from "./types";

type Topic = { kind: "model" | "agronomy"; subject: string; pattern: RegExp; outlook?: boolean };
const model = /WHCNS(?:[-_ ]?Veg)?|DSSAT|APSIM|农业模型|农田模型|作物模型|水氮模型|机理模型|过程模型|数据驱动模型/i;
const outlook = /未来|前景|发展|趋势|展望/;
const followup = /上面|上述|前面|刚才|这些|这个|其中|它|继续|再解释|^(?:那|那么|为什么|为何|能更通俗)/;
const switchTopic = /换个话题|另一个问题|不说.{0,12}了/;
const subjects: [string, RegExp][] = [
  ["氮素淋失", /氮素?淋失|氮素?淋溶|硝态氮淋失/],
  ["氧化亚氮排放", /氧化亚氮|N₂O|N2O/i], ["反硝化作用", /反硝化/], ["硝化作用", /硝化/],
  ["氮矿化", /矿化/], ["硝态氮", /硝态氮|硝酸盐|NO[₃3]/i],
  ["土壤质地", /土壤质地/], ["水氮管理", /水氮|水肥/], ["灌溉管理", /灌溉|灌水/],
  ["施肥管理", /施肥|追肥/], ["光合作用", /光合作用/], ["作物蒸腾", /蒸腾/],
];

function explicitTopic(query: string): Topic | null {
  const match = model.exec(query);
  const modelTopic: Topic | null = match ? { kind: "model", subject: match[0], pattern: /模型|模拟|预测|率定|参数|机理|数据驱动/i, outlook: outlook.test(query) } : null;
  if (modelTopic && (modelTopic.outlook || /用途|输入|数据|参数|率定|校准|可靠|验证|适合|怎么用|能做什么/.test(query))) return modelTopic;
  for (const [subject, pattern] of subjects) {
    if (pattern.test(query)) return { kind: "agronomy", subject, pattern };
  }
  return modelTopic;
}

function topicFor(queries: string[]): Topic | null {
  for (let index = queries.length - 1; index >= 0; index--) {
    const query = queries[index];
    const topic = explicitTopic(query);
    if (topic) return topic;
    // Only an explicit follow-up can inherit a previous subject. A new, unknown
    // question must not keep offering the previous conversation's suggestions.
    if (switchTopic.test(query) || !followup.test(query)) return null;
  }
  return null;
}

function modelQuestions(topic: Topic, answer: string): string[] {
  const subject = topic.subject;
  const result: string[] = [];
  if (topic.outlook) {
    result.push(`上面提到的${subject}发展方向中，哪些已有实际应用，哪些仍是研究设想？`);
    if (/人工智能|机器学习|深度学习|\bAI\b|数据驱动/i.test(answer)) result.push(`${subject}与人工智能结合时，各自能解决什么问题，又有哪些局限？`);
    result.push(`判断${subject}的发展方向是否可行，需要哪些数据和验证？`);
  } else {
    result.push(`怎样判断${subject}是否适合我的研究问题？`);
    if (/输入|数据|参数|驱动|气象|管理记录/.test(answer)) result.push(`使用${subject}前，需要准备哪些输入数据，哪些参数需要率定？`);
    if (/验证|校准|率定|误差|不确定|可靠|精度/.test(answer)) result.push(`怎样验证${subject}的结果，避免把模拟结果当成确定事实？`);
  }
  return result;
}

function agronomyQuestions(topic: Topic, query: string, answer: string, hasCitations: boolean): string[] {
  const subject = topic.subject;
  const result: string[] = [];
  const mechanism = /优先流|反硝化|硝化|矿化|下渗|淋洗|吸收|光合作用|蒸腾/.exec(answer)?.[0];
  if (mechanism && !(/通俗|解释|什么意思/.test(query) && query.includes(mechanism))) {
    const process = subject.includes(mechanism) ? `${subject}的关键过程` : `${subject}涉及的${mechanism}过程`;
    result.push(`能用更通俗的话解释${process}吗？`);
  }
  if (hasCitations) result.push(`关于${subject}的上述结论，哪些有文献直接支持，哪些仍需验证？`);
  const factors = [...new Set(answer.match(/降雨|灌溉|灌水|土壤质地|施肥|温度|根系|生育期/g) || [])];
  if (factors.length >= 2) result.push(`在${subject}问题中，${factors[0]}与${factors[1]}分别怎样起作用？`);
  if (/作物|土壤|气候|地区|条件|局限|适用|田间/.test(answer)) result.push(`关于${subject}的结论，适用条件和局限是什么？`);
  if (factors.length && /因素|影响|条件/.test(query + answer)) result.push(`判断${subject}的主要影响因素，需要补充哪些现场信息？`);
  return result;
}

function caseQuestions(response: ChatResponse): string[] {
  if (response.case_match === "missing") return [
    "为了找到合适的案例，我还需要补充哪些背景信息？",
    "请给我一个包含作物、地区和管理条件的提问模板。",
  ];
  if (response.case_match === "unavailable") return [];
  const cases = response.case_references || [];
  if (!cases.length) return [];
  const subject = cases.length === 1 ? `上面这个“${cases[0].title.slice(0, 40)}”案例` : "上面这些案例";
  const questions = [`${subject}有哪些适用条件，哪些做法不能直接照搬？`];
  if (/措施|施肥|灌溉|灌水|追肥|做法/.test(response.answer)) questions.unshift(`${subject}中的关键措施是什么，为什么这样做？`);
  if (cases.length > 1) questions.push("请比较上面这些案例的措施、适用条件和证据差异。");
  else questions.push(`${subject}的效果有哪些证据，哪些结论还不能确定？`);
  return questions;
}

const normalized = (text: string) => text.normalize("NFKC").replace(/[\s，,。.!！?？“”"：:；;]/g, "");

export function suggestFollowUps(response: ChatResponse, queries: string[]): string[] {
  if (response.route !== "knowledge" || response.outcome === "clarification" || response.file_evidence?.length) return [];
  const answer = response.answer.trim();
  if (!answer || /^(?:抱歉[，,]?|对不起[，,]?)?(?:这个问题超出|无法回答|不能回答|暂时无法回答|目前无法回答)/.test(answer)) return [];
  let candidates: string[] = [];
  if (response.case_route?.length || response.case_references?.length || response.case_match) {
    candidates = caseQuestions(response);
  } else {
    if (response.outcome === "partial") return [];
    const topic = topicFor(queries);
    // Route alone is insufficient: suggestions need an identifiable topic and
    // substantive content about it in the answer that was actually returned.
    if (!topic || answer.length < 24 || !topic.pattern.test(answer)) return [];
    candidates = topic.kind === "model" ? modelQuestions(topic, answer)
      : agronomyQuestions(topic, queries.at(-1) || "", answer, response.citations.length > 0);
    if (topic.kind === "model" && response.citations.length) candidates.push(`关于${topic.subject}的上述说明，哪些结论有文献直接支持？`);
  }
  const asked = new Set(queries.map(normalized));
  return [...new Set(candidates)].filter((question) => !asked.has(normalized(question))).slice(0, 3);
}
