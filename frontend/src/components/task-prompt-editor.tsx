"use client";

import { useEffect, useState } from "react";
import { evaluationJson, evaluationRequest } from "@/lib/evaluation-api";
import { MarkdownAnswer } from "./chat/markdown-answer";

export type TaskScope = "concept_explanation" | "knowledge_search" | "case_assistant";
type Example = { source_case: string; source_revision: string; review_scope: string; confirmed: boolean; query: string; answer: string };
type TaskPrompt = { prompt_id: string; scope: TaskScope; label: string; text: string; version: string; examples: Example[] };
type Catalog = { versions: TaskPrompt[]; active: Record<TaskScope, TaskPrompt> };
const scopes: Record<TaskScope, string> = { concept_explanation: "概念解释", knowledge_search: "专业问答", case_assistant: "案例任务" };
const field = "wb-field";
const button = "wb-button";

export function TaskPromptEditor({ token, initialScope = "concept_explanation", onCandidate, onSaved, allowActivation = false }: {
  token: string; initialScope?: TaskScope; onCandidate?: (scope: TaskScope, id: string) => void; onSaved?: () => void; allowActivation?: boolean;
}) {
  const [scope, setScope] = useState<TaskScope>(initialScope);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [chosen, setChosen] = useState("");
  const [label, setLabel] = useState("");
  const [text, setText] = useState("");
  const [examples, setExamples] = useState<Example[]>([]);
  const [shotMode, setShotMode] = useState<"zero-shot" | "few-shot">("zero-shot");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    evaluationRequest<Catalog>(token, "/task-prompts").then(value => {
      if (active) { const current = value.active[initialScope]; setCatalog(value); setText(current.text); setExamples(current.examples); setShotMode(current.examples.length ? "few-shot" : "zero-shot"); }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [token, initialScope]);
  function changeScope(next: TaskScope) {
    if (onCandidate) onCandidate(scope, "");
    const current = catalog?.active[next];
    setScope(next); setChosen(""); setLabel(""); setExamples(current?.examples ?? []); setShotMode(current?.examples.length ? "few-shot" : "zero-shot"); setText(current?.text ?? ""); setNotice("");
  }
  function select(id: string) {
    setChosen(id); onCandidate?.(scope, id);
    const value = catalog?.versions.find(p => p.prompt_id === id) ?? catalog?.active[scope];
    if (value) { setText(value.text); setExamples(value.examples ?? []); setShotMode(value.examples?.length ? "few-shot" : "zero-shot"); setLabel(""); }
  }
  async function save() {
    setBusy(true); setError(""); setNotice("");
    try {
      const saved = await evaluationRequest<TaskPrompt>(token, "/task-prompts", evaluationJson({ scope, label, text, examples: shotMode === "few-shot" ? examples : [] }));
      const next = await evaluationRequest<Catalog>(token, "/task-prompts");
      setCatalog(next); setChosen(saved.prompt_id); onCandidate?.(scope, saved.prompt_id); setNotice(`已保存任务候选：${saved.label}；尚未启用。`);
      onSaved?.();
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
    finally { setBusy(false); }
  }
  async function activate() {
    setBusy(true); setError("");
    try {
      await evaluationRequest(token, `/task-prompts/${scope}/active`, { ...evaluationJson({ prompt_id: chosen }), method: "PUT" });
      setCatalog(await evaluationRequest<Catalog>(token, "/task-prompts")); setNotice("已显式启用所选任务版本，后续新请求使用该版本。");
      onSaved?.();
    } catch (e) { setError(e instanceof Error ? e.message : "启用失败"); }
    finally { setBusy(false); }
  }
  const selected = catalog?.versions.find(p => p.prompt_id === chosen) ?? catalog?.active[scope];
  function addExample() {
    setExamples(list => [...list, { source_case: "", source_revision: "", review_scope: "", confirmed: false, query: "", answer: "" }]);
  }
  function updateExample(index: number, updates: Partial<Example>) {
    setExamples(list => list.map((e, i) => i === index ? { ...e, ...updates } : e));
  }
  const examplesValid = shotMode === "zero-shot" || (examples.length > 0 && examples.every(e => e.confirmed && e.query.trim() && e.answer.trim() && e.source_case.trim() && e.source_revision.trim() && e.review_scope.trim()));
  return <section className="space-y-3 rounded border p-3" aria-label="任务 Prompt">
    <h3 className="font-medium">任务 Prompt · 独立版本</h3>
    <p className="text-sm text-muted-foreground">任务规则补充现有事实、来源、数字和输出约束。保存候选不会启用；复测时可与表达层版本组合。</p>
    <label className="block text-sm">适用任务<select aria-label="适用任务" className={field} value={scope} onChange={e => changeScope(e.target.value as TaskScope)}>{Object.entries(scopes).map(([id, name]) => <option value={id} key={id}>{name}</option>)}</select></label>
    <p className="text-xs">当前生效：{catalog?.active[scope].label ?? "读取中…"} · {catalog?.active[scope].version}</p>
    <label className="block text-sm">任务候选<select aria-label="任务候选" className={field} value={chosen} onChange={e => select(e.target.value)}><option value="">使用当前生效任务版本</option>{catalog?.versions.filter(p => p.scope === scope).map(p => <option key={p.prompt_id} value={p.prompt_id}>{p.label} · {p.examples.length ? "few-shot" : "zero-shot"} · {p.version}</option>)}</select></label>
    {selected && <details><summary className="cursor-pointer text-sm">所选任务层预览 · {selected.examples?.length ? "含示例" : "无示例"}</summary><MarkdownAnswer content={selected.text} /><pre className="whitespace-pre-wrap text-xs">{JSON.stringify(selected.examples, null, 2)}</pre></details>}
    <details><summary className="cursor-pointer text-sm">编辑并另存任务候选</summary><div className="mt-2 space-y-2">
      <input aria-label="任务候选名称" placeholder="新版本名称" className={field} maxLength={100} value={label} onChange={e => setLabel(e.target.value)} />
      <textarea aria-label="任务规则" className={field} rows={6} maxLength={16000} value={text} onChange={e => setText(e.target.value)} />
      <fieldset className="space-y-2 rounded border p-3"><legend className="px-1 text-sm">示例方式</legend>
        <label className="mr-4 inline-flex items-center gap-2 text-sm"><input type="radio" name="task-shot-mode" checked={shotMode === "zero-shot"} onChange={() => setShotMode("zero-shot")} />zero-shot · 不带示例</label>
        <label className="inline-flex items-center gap-2 text-sm"><input type="radio" name="task-shot-mode" checked={shotMode === "few-shot"} onChange={() => { setShotMode("few-shot"); if (!examples.length) addExample(); }} />few-shot · 带示例</label>
        <p className="text-xs text-muted-foreground">可保留同一份任务规则，分别另存不带示例与带示例的版本，用于组测评。示例仅示范回答方式，不作为当前问题的事实依据。</p>
        {shotMode === "few-shot" && <div className="space-y-3">{examples.map((example, index) => <section key={index} aria-label={`任务示例${index + 1}`} className="space-y-2 rounded border p-3">
          <div className="flex items-center justify-between"><h4 className="text-sm font-medium">示例 {index + 1}</h4><button type="button" className={button} onClick={() => setExamples(list => list.filter((_, i) => i !== index))}>移除示例 {index + 1}</button></div>
          <label className="block space-y-1 text-xs">示例问题<textarea aria-label={`示例${index + 1}问题`} className={field} rows={2} maxLength={3000} value={example.query} onChange={e => updateExample(index, { query: e.target.value })} /></label>
          <label className="block space-y-1 text-xs">示范回答<textarea aria-label={`示例${index + 1}回答`} className={field} rows={4} maxLength={6000} value={example.answer} onChange={e => updateExample(index, { answer: e.target.value })} /></label>
          <div className="grid gap-2 sm:grid-cols-2"><label className="block space-y-1 text-xs">来源案例 / 用例<input aria-label={`示例${index + 1}来源`} className={field} maxLength={160} value={example.source_case} onChange={e => updateExample(index, { source_case: e.target.value })} /></label><label className="block space-y-1 text-xs">来源版本<input aria-label={`示例${index + 1}来源版本`} className={field} maxLength={160} value={example.source_revision} onChange={e => updateExample(index, { source_revision: e.target.value })} /></label></div>
          <label className="block space-y-1 text-xs">已核对的适用范围<input aria-label={`示例${index + 1}核对范围`} className={field} maxLength={1000} value={example.review_scope} onChange={e => updateExample(index, { review_scope: e.target.value })} /></label>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={example.confirmed} onChange={e => updateExample(index, { confirmed: e.target.checked })} />已核对示例内容与来源，确认可用作示范</label>
        </section>)}<button type="button" className={button} disabled={examples.length >= 3} onClick={addExample}>添加示例（最多 3 个）</button></div>}
      </fieldset>
      <button className={button} disabled={busy || !catalog || !label.trim() || !text.trim() || !examplesValid} onClick={() => void save()}>保存任务候选</button>
    </div></details>
    {allowActivation && <button className={button} disabled={busy || !chosen || chosen === catalog?.active[scope].prompt_id} onClick={() => void activate()}>启用所选任务版本</button>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
  </section>;
}
