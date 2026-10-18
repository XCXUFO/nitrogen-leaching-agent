import type { ChatResponse } from "@/lib/types";
import type { Turn } from "./use-conversations";

const questions = {
  knowledge: [
    [
      "能用更通俗的话解释一下上面提到的关键机制吗？",
      "哪些因素对这个问题影响最大，为什么？",
      "土壤、作物和气候不同，结论会有什么变化？",
      "上面的结论分别有哪些文献依据？",
    ],
    [
      "结合前面的解释，田间管理可以从哪些方面改进？",
      "哪些结论比较确定，哪些还需要更多证据？",
      "如果要验证这个解释，需要监测哪些指标？",
      "能举个具体情境，说明这些因素如何共同作用吗？",
    ],
    [
      "请把前面的要点整理成一份可操作的检查清单。",
      "这些建议在什么条件下可能不适用？",
      "如果只能先做一件事，应该优先核查什么？",
      "还有哪些容易忽略的因素值得继续了解？",
    ],
  ],
  case: [
    [
      "上面案例中的关键措施是什么，为什么这样做？",
      "这些案例分别适合什么作物、土壤和气候条件？",
      "能再找一个相关案例，对比措施和适用条件吗？",
      "参考这些案例时，有哪些风险和注意事项？",
    ],
    [
      "如果换成多雨地区，参考这些措施时需要调整什么？",
      "能把前面案例的做法和适用条件整理成对比表吗？",
      "这些措施实施前，需要补充哪些田间信息？",
      "案例中的效果有哪些证据，还不能得出哪些结论？",
    ],
    [
      "请基于前面的案例，整理一份分步骤的实施参考。",
      "采用类似措施后，应该怎样监测效果？",
      "哪些情况下不宜直接照搬这些案例的做法？",
      "能把前面案例中可借鉴的经验总结成一份清单吗？",
    ],
  ],
};

const missingCaseQuestions = [
  "为了找到合适的案例，我还需要补充哪些背景信息？",
  "能扩大到相近作物或地区，再找找相关案例吗？",
  "目前缺少匹配案例时，有哪些管理原则可以先参考？",
  "请给我一个包含作物、地区和管理条件的提问模板。",
];

function topic(response: ChatResponse): keyof typeof questions | null {
  if (response.route === "file" || response.route === "out_of_scope" || response.file_evidence.length) return null;
  if (response.case_route?.length || response.case_references?.length || response.case_match) return "case";
  if (response.route === "knowledge" && response.outcome !== "clarification") return "knowledge";
  return null;
}

export function FollowUpSuggestions({ turns, disabled, onSelect }: {
  turns: Turn[]; disabled: boolean; onSelect: (question: string) => void;
}) {
  const latest = turns.at(-1);
  if (latest?.role !== "assistant") return null;
  const currentTopic = topic(latest.response);
  if (!currentTopic) return null;

  let rounds = 0;
  for (let index = turns.length - 1; index >= 0; index--) {
    const turn = turns[index];
    if (turn.role !== "assistant") continue;
    if (topic(turn.response) !== currentTopic) break;
    rounds++;
  }
  const stages = questions[currentTopic];
  const stage = Math.min(rounds - 1, stages.length - 1);
  const candidates = currentTopic === "case" && ["missing", "unavailable"].includes(latest.response.case_match ?? "")
    ? missingCaseQuestions
    : [...stages.slice(stage).flat(), ...stages.slice(0, stage).flat()];
  const asked = new Set(turns.filter((turn) => turn.role === "user").map((turn) => turn.content));
  const suggestions = candidates.filter((question) => !asked.has(question)).slice(0, 4);
  if (!suggestions.length) return null;

  return <section aria-label="推荐追问" className="space-y-2">
    <p className="text-xs text-muted-foreground">还可以继续问</p>
    <div className="grid gap-2 sm:grid-cols-2">
      {suggestions.map((question) => <button key={question} type="button" disabled={disabled}
        className="min-w-0 rounded-xl border bg-background px-3 py-2 text-left text-xs leading-6 hover:bg-muted/40 disabled:opacity-50"
        onClick={() => onSelect(question)}>{question}</button>)}
    </div>
  </section>;
}
