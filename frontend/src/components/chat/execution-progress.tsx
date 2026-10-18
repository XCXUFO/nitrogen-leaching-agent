import { Check, CircleAlert, LoaderCircle } from "lucide-react";
import type { ChatRunEvent, ChatRunView } from "@/lib/types";

const statuses: Record<string, string> = {
  accepted: "已受理", running: "处理中", succeeded: "已完成", failed: "执行失败",
  cancelled: "已停止", interrupted: "运行已中断", unknown: "状态待确认",
};
const outcomes: Record<string, string> = {
  has_result: "已获得结果", no_result: "未找到相关结果", clarification: "需要补充信息", unfulfilled: "未完成目标", not_executed: "未执行",
  partial_coverage: "已找到部分解答，继续处理其余问题", full_coverage: "已有问答已覆盖本轮问题", empty_answer: "匹配问答暂无答案，继续检索", unavailable: "当前未采集可用映射",
};

export function ExecutionProgress({ run, recovering = false }: {
  run: ChatRunView; recovering?: boolean;
}) {
  const steps = new Map<string, ChatRunEvent>();
  const attempts = new Map<string, Map<number, ChatRunEvent>>();
  for (const event of [...run.events].sort((a, b) => a.sequence - b.sequence)) {
    if (event.step_id && (event.type === "step_started" || event.type === "step_finished")) steps.set(event.step_id, event);
    if (event.step_id && (event.type === "step_started" || event.type === "step_finished")) {
      const group = attempts.get(event.step_id) ?? new Map<number, ChatRunEvent>();
      group.set(event.attempt_no ?? 1, event); attempts.set(event.step_id, group);
    }
  }
  const active = run.status === "accepted" || run.status === "running";
  const label = run.status === "succeeded" && run.outcome === "clarification" ? "需要补充信息" : run.status === "succeeded" && run.outcome === "partial" ? "部分完成" : statuses[run.status] ?? "状态待确认";
  const unsaved = !active && !run.result_saved && run.result
    ? <p className="text-xs text-amber-800">本次结果尚未保存，关闭页面后可能无法找回。</p> : null;
  const content = <div className="space-y-3 text-sm">
    {recovering && <p role="status" className="text-amber-800">连接中断，正在查询原运行…</p>}
    {steps.size > 0 ? <ol className="space-y-2" aria-label="实际执行步骤">{[...steps.values()].map(step => <li key={step.step_id} className="flex items-start gap-2">
      {step.status === "running" && active ? <LoaderCircle className="mt-0.5 size-4 shrink-0 animate-spin" /> : step.status === "succeeded" ? <Check className="mt-0.5 size-4 shrink-0 text-emerald-700" /> : <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-700" />}
      <span className="min-w-0 break-words">{step.name || "处理步骤"}<span className="ml-2 text-xs text-muted-foreground">{step.status === "running" && !active ? "未确认完成" : statuses[step.status]}{step.outcome && ` · ${outcomes[step.outcome] ?? step.outcome}`}</span>
        {(attempts.get(step.step_id!)?.size ?? 0) > 1 && <details className="mt-1 text-xs text-muted-foreground"><summary className="cursor-pointer">已记录 {attempts.get(step.step_id!)!.size} 次尝试</summary><ul className="mt-1 space-y-1">{[...attempts.get(step.step_id!)!.entries()].map(([number, event]) => <li key={number}>第 {number} 次 · {statuses[event.status] ?? event.status}{event.outcome ? ` · ${outcomes[event.outcome] ?? event.outcome}` : ""}</li>)}</ul></details>}
      </span>
    </li>)}</ol> : <p className="text-muted-foreground">{active ? "问题已受理，等待处理步骤。" : "本轮没有需要展示的能力步骤。"}</p>}
    {!active && !run.result_saved && !run.result && <p className="text-xs text-amber-800">原运行已结束，没有可恢复的结果。</p>}
  </div>;
  return <section aria-label="处理进度" className="space-y-3 rounded-2xl border bg-background p-5"><p role="status" className="text-sm font-medium">{label}</p>{unsaved}{content}</section>;
}
