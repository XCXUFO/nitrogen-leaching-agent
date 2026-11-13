"use client";

import Link from "next/link";
import { type GroupActivation, type PromptGroup, type Trial, type TrialStep, scopes, taskScopes, variants, side, shots, trialStatuses } from "@/lib/prompt-types";
import { PromptContent } from "./prompt-content";
import { MarkdownAnswer } from "./chat/markdown-answer";
import { PromptGroupActivationButton } from "./prompt-group-activation";

export function GroupSnapshot({ group }: { group: PromptGroup }) {
  return <div className="space-y-2 text-sm"><p className="font-medium">{group.label} <span className="break-all text-xs text-slate-400">{group.version}</span></p>
    <details><summary className="cursor-pointer">全局表达：{group.communication.label}</summary><PromptContent label={`${group.label}全局快照`} value={group.communication.text} readOnly /></details>
    {taskScopes.map(scope => { const p = group.task_prompts[scope]; return <details key={scope}><summary className="cursor-pointer">{scopes[scope]}：{p.label} <span className="text-xs text-slate-500">{shots(p)}</span></summary><p className="my-1 break-all text-xs text-slate-500">{p.version}</p><PromptContent label={`${group.label}${scopes[scope]}快照`} value={p.text} readOnly />{p.examples.map((e, i) => <div key={i} className="my-2 space-y-1 rounded border p-3"><p className="font-medium">示例 {i + 1}：{e.query}</p><MarkdownAnswer content={e.answer} /><p className="text-xs text-slate-500">来源 {e.source_case} · {e.source_revision} · 已确认范围：{e.review_scope}</p></div>)}</details>; })}
  </div>;
}

function StepResult({ step, trial, variant }: { step: TrialStep; trial: Trial; variant: "baseline" | "candidate" }) {
  const group = trial.groups?.[variant];
  return <div className="space-y-2 text-sm">
    <p className="text-xs text-slate-500">{trialStatuses[step.status] ?? step.status}{step.skills?.length ? ` · ${step.skills.map(s => scopes[s as keyof typeof scopes] ?? s).join("、")}` : ""}</p>
    {step.actual_prompt && <p className="text-xs">{step.task_prompt_usage?.length ? "实际全局表达" : "记录的全局表达版本"}：{step.actual_prompt.label} · {step.actual_prompt.version}</p>}
    {step.task_prompt_usage?.length ? <ul className="space-y-1 text-xs text-slate-600">{step.task_prompt_usage.map(u => {
      const p = group?.task_prompts[u.scope];
      const count = u.example_count ?? p?.examples?.length ?? 0;
      return <li key={`${u.scope}:${u.version}`}>实际任务：{scopes[u.scope]} · {u.version} · {count ? `few-shot，${count} 个示例` : "zero-shot"}</li>;
    })}</ul> : <p className="text-xs text-amber-800">本轮未调用任务 Prompt，不用于判断任务规则或示例的效果。</p>}
    <MarkdownAnswer content={step.response?.answer ?? "尚无已完成回答"} />
    {step.response?.model && <p className="text-xs text-slate-500">模型：{step.response.model}{step.response.usage ? ` · 输入 ${step.response.usage.prompt_tokens} / 输出 ${step.response.usage.completion_tokens} tokens` : ""}</p>}
    {step.error && <p role="alert" className="text-red-800">{step.error.message}</p>}
    {!!step.response?.citations?.length && <details><summary className="cursor-pointer text-xs">本轮引用依据</summary>{step.response.citations.map(c => <div key={c.index} className="my-2 rounded border p-2"><p>[{c.index}] {c.title || c.source}</p><p>{c.snippet}</p></div>)}</details>}
    <Link href={`/evaluation/runs/${encodeURIComponent(step.run_id)}`} className="text-xs text-emerald-800 underline">查看运行详情</Link>
  </div>;
}

export function PromptGroupResults({ trial, activation }: { trial: Trial; activation?: GroupActivation }) {
  const queries = [trial.query, ...(trial.followups ?? [])];
  return <section className="space-y-4" aria-label="Prompt 组测评结果">
    <p role="status" className="text-sm">{trialStatuses[trial.status] ?? trial.status}</p>
    <details className="rounded-xl border bg-white p-4"><summary className="cursor-pointer text-sm">本次问题、材料与初始历史</summary><p className="mt-2 whitespace-pre-wrap text-sm">{trial.query}</p><p className="mt-2 whitespace-pre-wrap text-sm text-slate-600">{trial.material || "未提供额外材料"}</p>{trial.history?.map((turn, i) => <p className="mt-2 whitespace-pre-wrap text-sm" key={i}>{turn.role === "user" ? "用户" : "助手"}：{turn.content}</p>)}</details>
    <div className="grid gap-4 lg:grid-cols-2">{variants.map(variant => <section key={variant} aria-label={`${side[variant]}版本组快照`} className="min-w-0 space-y-3 rounded-xl border bg-white p-4"><h3 className="font-semibold">{side[variant]}版本组</h3>{trial.groups ? <GroupSnapshot group={trial.groups[variant]} /> : trial.prompts?.[variant] ? <><p>{trial.prompts[variant].label}</p><PromptContent label={`${side[variant]}历史表达 Prompt`} value={trial.prompts[variant].text} readOnly /></> : <p className="text-sm">历史记录未保存完整 Prompt。</p>}
      {!!trial.variants[variant]?.unused_task_scopes?.length && <p className="text-xs text-slate-500">本次未使用：{trial.variants[variant]!.unused_task_scopes!.map(s => scopes[s]).join("、")}。这些任务及其示例尚未验证。</p>}
      {activation && trial.groups && <PromptGroupActivationButton group={trial.groups[variant]} {...activation} label={`将本次${side[variant]}方案设为当前方案`} />}
    </section>)}</div>
    {trial.groups ? queries.map((query, i) => {
      const left = trial.variants.baseline?.steps?.[i], right = trial.variants.candidate?.steps?.[i];
      return <section className="space-y-3" key={i}><h3 className="text-sm font-semibold">第 {i + 1} 轮：{query}</h3>
        {left?.response?.model && right?.response?.model && left.response.model !== right.response.model && <p className="text-xs text-amber-800">两侧使用的模型不同，请结合执行路线核对差异。</p>}
        {left?.evidence_fingerprint && right?.evidence_fingerprint && left.evidence_fingerprint !== right.evidence_fingerprint && <p className="text-xs text-amber-800">两侧引用依据或案例取材不同，回答差异需要结合材料核对。</p>}
        <div className="grid gap-4 lg:grid-cols-2">{variants.map(variant => { const step = trial.variants[variant]?.steps?.[i]; return <article aria-label={`${side[variant]}第${i + 1}轮结果`} key={variant} className="min-w-0 space-y-2 rounded-xl border bg-white p-4"><h4 className="font-medium">{side[variant]}回答</h4>{step ? <StepResult step={step} trial={trial} variant={variant} /> : <p className="text-sm text-slate-500">{trial.variants[variant]?.status === "failed" ? "此组执行失败" : "尚未执行本轮"}</p>}</article>; })}</div>
      </section>;
    }) : <div className="grid gap-4 lg:grid-cols-2">{variants.map(variant => <article key={variant} className="min-w-0 rounded-xl border bg-white p-4"><MarkdownAnswer content={trial.variants[variant]?.answer ?? "尚无已完成回答"} /></article>)}</div>}
  </section>;
}
