import { suggestFollowUps } from "@/lib/follow-up-questions";
import type { Turn } from "./use-conversations";

export function FollowUpSuggestions({ turns, disabled, onSelect }: {
  turns: Turn[]; disabled: boolean; onSelect: (question: string, caseIds?: string[]) => void;
}) {
  const latest = turns.at(-1);
  if (latest?.role !== "assistant") return null;
  const queries = turns.filter((turn) => turn.role === "user").map((turn) => turn.content);
  if (latest.request?.query && queries.at(-1) !== latest.request.query) queries.push(latest.request.query);
  const suggestions = suggestFollowUps(latest.response, queries);
  const caseIds = latest.response.case_references?.map((item) => item.id);
  if (!suggestions.length) return null;

  return <section aria-label="推荐追问" className="space-y-2">
    <p className="text-xs text-muted-foreground">还可以继续问</p>
    <div className="grid gap-2 sm:grid-cols-2">
      {suggestions.map((question) => <button key={question} type="button" disabled={disabled}
        className="min-w-0 rounded-xl border bg-background px-3 py-2 text-left text-xs leading-6 hover:bg-muted/40 disabled:opacity-50"
        onClick={() => onSelect(question, caseIds?.length ? caseIds : undefined)}>{question}</button>)}
    </div>
  </section>;
}
