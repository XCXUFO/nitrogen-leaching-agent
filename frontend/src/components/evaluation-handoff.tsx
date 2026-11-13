"use client";

import Link from "next/link";
import { TaskPromptEditor, type TaskScope } from "./task-prompt-editor";
import { useEffect, useRef, useState } from "react";
import { evaluationJson, evaluationRequest } from "@/lib/evaluation-api";
import { MarkdownAnswer } from "./chat/markdown-answer";

type Prompt = { prompt_id: string; label: string; text: string; version: string };
type Attempt = { unused_task_scopes?: string[]; simulated?: boolean; judgments?: { basis: string; actor: string; conclusion: string }[]; attempt_id: string; status: string; quality: string; requested_prompt_id: string; error_code?: string;
  steps: { run_id: string; query: string; status: string; history: { role: string; content: string }[];
    response?: { answer: string; case_mode?: "search" | "explain" | "compare" | "evidence"; citations?: { index: number; title?: string; source: string; snippet: string }[] }; actual_prompt?: Prompt; task_prompt_usage?: { scope: string; version: string }[] }[] };
type Source = { suggested_task_scope?: TaskScope; local_id: string; evaluation_mode: string; seed_history: { role: string; content: string }[];
  source: { id: string; conversation_title: string; source_review_status: string; target_turn: number | null;
    source_session_id: string; baseline?: { skills: string[] }; original_review: { note: string }; acceptance_draft: string[]; user_turns: string[] };
  baseline: { turns: { turn: number; user: string; assistant_visible_text: string; is_evaluation_target: boolean; source_run_id: string }[] };
  attempts?: Attempt[]; missing_fields: string[] };
const button = "rounded border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const field = "w-full rounded border bg-background p-2 text-sm";
const statuses: Record<string, string> = { queued: "排队中", running: "运行中", completed: "技术完成", failed: "执行失败", interrupted: "已中断", blocked: "受阻", pending: "待复核", pass: "符合", fail: "仍需修改" };
const href = (id = "") => `/evaluation/runs${id ? `/${encodeURIComponent(id)}` : ""}?source=handoff`;

export function EvaluationHandoff({ token, detail }: { token: string; detail: string }) {
  const [items, setItems] = useState<Source[]>([]);
  const [source, setSource] = useState<Source | null>(null);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [promptId, setPromptId] = useState("");
  const [taskIds, setTaskIds] = useState<Partial<Record<TaskScope, string>>>({});
  const [label, setLabel] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [basis, setBasis] = useState<Record<string, string>>({});
  const pending = useRef<{ prompt: string; id: string } | null>(null);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        if (detail) {
          const value = await evaluationRequest<Source>(token, `/handoff-sources/${encodeURIComponent(detail)}`);
          if (!active) return;
          setSource(value);
          if (value.attempts?.some(a => ["queued", "running"].includes(a.status))) timer = setTimeout(refresh, 1500);
        } else {
          const value = await evaluationRequest<Source[]>(token, "/handoff-sources");
          if (active) setItems(value);
        }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "读取失败"); }
      finally { if (active) setLoading(false); }
    }
    void refresh();
    if (detail) void evaluationRequest<Prompt[]>(token, "/prompt-versions").then(value => {
      if (active) { setPrompts(value); setPromptId(value[0]?.prompt_id ?? ""); }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; clearTimeout(timer); };
  }, [token, detail]);

  async function savePrompt() {
    setBusy(true); setError("");
    try {
      const value = await evaluationRequest<Prompt>(token, "/prompt-versions", evaluationJson({ label, text }));
      setPrompts(await evaluationRequest<Prompt[]>(token, "/prompt-versions")); setPromptId(value.prompt_id);
      setLabel(""); setText("");
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
    finally { setBusy(false); }
  }
  async function retest() {
    setBusy(true); setError("");
    const fingerprint = JSON.stringify([promptId, taskIds]);
    if (pending.current?.prompt !== fingerprint) pending.current = { prompt: fingerprint, id: crypto.randomUUID() };
    try {
      await evaluationRequest(token, `/handoff-sources/${encodeURIComponent(detail)}/retests`, evaluationJson({ prompt_id: promptId, task_prompt_ids: taskIds, submission_id: pending.current.id }));
      // Reload resumes durable polling; the server owns execution, not this page.
      window.location.reload();
    } catch (e) { setError(e instanceof Error ? e.message : "复测未确认，请用原提交重试。"); }
    finally { setBusy(false); }
  }
  async function judge(id: string, conclusion: string) {
    setBusy(true); setError("");
    try {
      await evaluationRequest(token, `/handoff-retests/${id}/judgments`, evaluationJson({ conclusion, basis: basis[id] }));
      setSource(await evaluationRequest<Source>(token, `/handoff-sources/${encodeURIComponent(detail)}`));
    } catch (e) { setError(e instanceof Error ? e.message : "评价未保存"); }
    finally { setBusy(false); }
  }
  const program = source?.source.baseline?.skills.join(",") === "capability_guidance";
  return <section className="space-y-4 rounded-xl border bg-white p-4">
    <div className="flex flex-wrap gap-4"><h2 className="font-semibold">本地交接问题</h2><Link className="text-sm underline" href="/evaluation/runs">返回运行记录</Link>{detail && <Link className="text-sm underline" href={href()}>返回交接列表</Link>}</div>
    <p className="text-sm text-muted-foreground">原会话是只读来源快照。新验证单独保存；技术完成后仍需核对，尚未关联线上发布。</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status">正在读取…</p>}
    {!detail && <div className="space-y-2">{items.map(item => <Link className="block rounded border p-3 hover:bg-muted" key={item.local_id} href={href(item.local_id)}>
      {item.source.id} · {item.source.conversation_title}<span className="ml-3 text-sm">{item.source.source_review_status === "needs_changes" ? `原需修改 · 第 ${item.source.target_turn} 轮` : "原会话通过"} · {item.baseline.turns.length} 轮</span>
    </Link>)}{!loading && !items.length && <p>尚未导入交接来源。请在本地运行交接包导入脚本。</p>}</div>}
    {source && <>
      <h3 className="font-medium">{source.source.id} · {source.source.conversation_title}</h3>
      <p className="text-sm">原审核：{source.source.original_review.note || "会话通过，未记录文字意见"}</p>
      <div className="rounded border bg-amber-50 p-3 text-sm"><p>本次目标：{source.evaluation_mode === "multi_turn_trajectory" ? "完整三轮，使用每轮新回答继续" : `第 ${source.source.target_turn} 轮，携带 ${source.seed_history.length} 条固定历史`}</p>
        {source.source.user_turns.map((q, i) => <p key={i} className="mt-2">{q}</p>)}</div>
      <details><summary className="cursor-pointer text-sm">原历史、回答与验收点</summary>
        <ul className="my-3 list-disc pl-5 text-sm">{source.source.acceptance_draft.map(x => <li key={x}>{x}</li>)}</ul>
        {source.baseline.turns.map(t => <article className="my-3 rounded border p-3" key={t.source_run_id}><p className="mb-2 font-medium">第 {t.turn} 轮{t.is_evaluation_target ? " · 验收目标" : ""}：{t.user}</p><MarkdownAnswer content={t.assistant_visible_text} /><p className="mt-2 break-all text-xs text-muted-foreground">原 Run：{t.source_run_id}</p></article>)}
        <p className="text-xs">历史缺失：{source.missing_fields.join("、")}</p>
      </details>
      <section className="space-y-3 rounded border p-3"><h3 className="font-medium">{program ? "程序文案 · 正常入口复测" : "候选组合 · 正常全流程复测"}</h3>
        <p className="text-sm text-muted-foreground">{program ? "此能力由程序生成；修改表达 Prompt 不会改变能力说明。请修改对应代码后在当前构建复测，实际代码版本保存在运行详情中。" : "本次重新执行路由与取证，可组合任务与表达候选。材料可能变化，不能将差异全部归因于 Prompt；保存和复测均不切换生效版本。"}</p>
        {!program && <><label className="block text-sm">已保存候选<select className={field} value={promptId} onChange={e => { setPromptId(e.target.value); pending.current = null; }}>{prompts.map(p => <option key={p.prompt_id} value={p.prompt_id}>{p.label} · {p.version}</option>)}</select></label>
        <details><summary className="cursor-pointer text-sm">候选正文</summary><pre className="whitespace-pre-wrap text-xs">{prompts.find(p => p.prompt_id === promptId)?.text}</pre></details>
        <details><summary className="cursor-pointer text-sm">另存一个候选</summary><div className="mt-2 space-y-2"><input aria-label="候选名称" placeholder="候选名称" className={field} value={label} onChange={e => setLabel(e.target.value)} /><textarea aria-label="候选正文" placeholder="表达规则" rows={5} className={field} value={text} onChange={e => setText(e.target.value)} /><button className={button} disabled={busy || !label.trim() || !text.trim()} onClick={() => void savePrompt()}>保存候选</button></div></details></>}
        {!program && <TaskPromptEditor token={token} initialScope={source.suggested_task_scope} onCandidate={(scope, id) => { setTaskIds(current => { const next = { ...current }; if (id) next[scope] = id; else delete next[scope]; return next; }); }} />}
        <button className={button} disabled={busy || !promptId || source.attempts?.some(a => ["queued", "running"].includes(a.status))} onClick={() => void retest()}>{program ? "复测当前程序文案" : "用候选复测"}</button>
      </section>
      {source.attempts?.map(a => <section key={a.attempt_id} className="space-y-3 rounded border p-3">
        {a.simulated && <p className="text-sm text-amber-800">模拟执行，仅用于流程验证。</p>}
        <h3 className="font-medium">{statuses[a.status] ?? a.status} · {statuses[a.quality] ?? a.quality} · 尚未关联上线</h3>
        {!!a.unused_task_scopes?.length && <p className="text-sm text-amber-800">所选任务候选未实际调用：{a.unused_task_scopes.join("、")}。请核对路由与任务范围。</p>}
        {a.error_code && <p role="alert" className="text-sm">执行原因：{a.error_code}</p>}
        {a.steps.map((step, i) => <div key={step.run_id} className="space-y-2"><p className="text-sm font-medium">第 {i + 1} 个目标 · {statuses[step.status] ?? step.status}</p><p className="text-xs">{program ? "记录的表达版本（程序文案未调用模型）" : "实际表达候选"}：{step.actual_prompt ? `${step.actual_prompt.label} · ${step.actual_prompt.version}` : "尚未记录"}</p>
          {step.response?.case_mode && <p className="text-xs">案例任务：{{ search: "查找", explain: "解释", compare: "比较", evidence: "效果取证" }[step.response.case_mode]}</p>}
          <p className="text-xs">实际任务层：{step.task_prompt_usage?.map(u => `${u.scope} · ${u.version}`).join("；") || "未调用模型或历史未记录"}</p>
          <div className="grid gap-3 lg:grid-cols-2"><article className="rounded border p-3"><h4 className="mb-2 text-sm font-medium">原回答</h4><MarkdownAnswer content={source.baseline.turns.filter(t => t.is_evaluation_target)[i]?.assistant_visible_text ?? "未记录"} /></article><article className="rounded border p-3"><h4 className="mb-2 text-sm font-medium">候选回答</h4>{step.response ? <><MarkdownAnswer content={step.response.answer} />{!!step.response.citations?.length && <details className="mt-3"><summary className="cursor-pointer text-sm">本次引用依据</summary>{step.response.citations.map(c => <div className="my-2 rounded border p-2 text-sm" key={c.index}><p>[{c.index}] {c.title || c.source}</p>{/^https?:\/\//i.test(c.source) && <a className="underline" href={c.source} target="_blank" rel="noopener noreferrer">打开来源</a>}<p className="mt-1">{c.snippet}</p></div>)}</details>}</> : <p className="text-sm">尚无完成的回答</p>}</article></div>
          <details><summary className="cursor-pointer text-xs">运行版本、引用与实际历史</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(step, null, 2)}</pre></details>
        </div>)}
        <details><summary className="cursor-pointer text-xs">人工复核历史</summary>{a.judgments?.map((j, i) => <p className="text-sm" key={i}>{j.actor} · {statuses[j.conclusion]}：{j.basis}</p>)}</details>
        {a.status === "completed" && <div className="space-y-2"><textarea aria-label="核对依据" className={field} placeholder="核对依据；专业内容尚不能确认时选择待核验" value={basis[a.attempt_id] ?? ""} onChange={e => setBasis({ ...basis, [a.attempt_id]: e.target.value })} />
          <div className="flex gap-2">{[["pass", "符合"], ["fail", "仍需修改"], ["pending", "待核验"]].map(([v, label]) => <button key={v} className={button} disabled={busy || !basis[a.attempt_id]?.trim()} onClick={() => void judge(a.attempt_id, v)}>{label}</button>)}</div></div>}
      </section>)}
    </>}
  </section>;
}
