"use client";

import { useEffect, useRef, useState } from "react";
import { evaluationRequest } from "@/lib/evaluation-api";
import { useEvaluationSession } from "./evaluation-shell";
import { MarkdownAnswer } from "./chat/markdown-answer";

type Variant = "baseline" | "candidate";
type Prompt = { label: string; text: string; version?: string; sha256?: string };
type Prompts = Record<Variant, Prompt>;
type SavedPrompt = Prompt & { prompt_id: string; created_at: string; actor: string };
type Trial = { trial_id: string; query: string; material: string; status: string; method_version: string; material_fingerprint: string; prompts?: Prompts; variants: Partial<Record<Variant, { run_id: string; status: string; answer?: string; model?: string; checks?: unknown; prompt?: Prompt }>> };
type Method = { version: string; title: string; edition: string; url: string; notice: string; adaptation: string; scope: string; prompts: Prompts };
const field = "w-full rounded-lg border bg-white px-2.5 py-1.5 text-sm";
const button = "rounded-lg border bg-white px-2.5 py-1.5 text-xs disabled:opacity-50";
const status: Record<string, string> = { accepted: "已受理", running: "执行中", completed: "对照已生成", failed: "试验未完成", interrupted: "已中断", unknown: "执行状态未知" };
const variants: Variant[] = ["baseline", "candidate"];
const side = { baseline: "旧版", candidate: "新版" };
const draftPrompts = (prompts: Prompts): Prompts => ({ baseline: { label: prompts.baseline.label, text: prompts.baseline.text }, candidate: { label: prompts.candidate.label, text: prompts.candidate.text } });

export function ExplanationTrials({ sourceRun = "" }: { sourceRun?: string }) {
  const { token } = useEvaluationSession();
  const [method, setMethod] = useState<Method | null>(null);
  const [prompts, setPrompts] = useState<Prompts>({ baseline: { label: "旧版 Prompt", text: "" }, candidate: { label: "新版 Prompt", text: "" } });
  const [savedPrompts, setSavedPrompts] = useState<SavedPrompt[]>([]);
  const [saving, setSaving] = useState<Variant | null>(null);
  const [activePrompt, setActivePrompt] = useState<SavedPrompt | null>(null);
  const [activeChoice, setActiveChoice] = useState("");
  const [activating, setActivating] = useState(false);
  const [notice, setNotice] = useState("");
  const [trials, setTrials] = useState<Trial[]>([]);
  const [selected, setSelected] = useState<Trial | null>(null);
  const [query, setQuery] = useState("");
  const [material, setMaterial] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ fingerprint: string; id: string } | null>(null);
  useEffect(() => {
    let active = true;
    Promise.all([evaluationRequest<Method>(token, "/explanation-method"), evaluationRequest<Trial[]>(token, "/explanation-trials"), evaluationRequest<SavedPrompt[]>(token, "/prompt-versions"), evaluationRequest<SavedPrompt>(token, "/active-prompt")])
      .then(([description, list, versions, current]) => { if (active) { setMethod(description); setPrompts({ baseline: draftPrompts(description.prompts).baseline, candidate: { label: current.label, text: current.text } }); setTrials(list); setSelected(list[0] ?? null); setSavedPrompts(versions); setActivePrompt(current); setActiveChoice(current.prompt_id); } })
      .catch((problem) => { if (active) setError(problem instanceof Error ? problem.message : "读取失败。"); });
    return () => { active = false; };
  }, [token]);
  useEffect(() => {
    if (!sourceRun) return;
    let active = true;
    evaluationRequest<{ turns: { run_id: string; input: string; request_snapshot?: { history?: { role: string; content: string }[] } }[] }>(token, `/sessions/${encodeURIComponent(sourceRun)}`)
      .then((session) => {
        if (!active) return;
        const original = session.turns.find((turn) => turn.run_id === sourceRun);
        if (!original) return;
        if (original.input.length > 3000) { setError("原问题较长，请在用户问题中摘录本次要调整的内容。"); return; }
        setQuery(original.input);
        const context = (original.request_snapshot?.history ?? []).map((item) => `${item.role === "user" ? "用户" : "助手"}：${item.content}`).join("\n\n");
        setMaterial(context.slice(0, 18000));
        setNotice(context.length > 18000 ? "已带入原问题，上下文较长，仅载入前 18000 字，请核对。" : "已带入原问题和文字上下文。调整生效后，可返回原会话重新验证。");
      }).catch((problem) => { if (active) setError(problem instanceof Error ? problem.message : "原问题读取失败。"); });
    return () => { active = false; };
  }, [sourceRun, token]);
  const activeTrial = selected && ["accepted", "running"].includes(selected.status) ? selected.trial_id : null;
  useEffect(() => {
    if (!activeTrial) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const trial = await evaluationRequest<Trial>(token, `/explanation-trials/${activeTrial}`);
        if (disposed) return;
        setSelected(trial); setTrials((items) => [trial, ...items.filter((item) => item.trial_id !== trial.trial_id)]);
        if (["accepted", "running"].includes(trial.status)) timer = setTimeout(poll, 1500);
      } catch (problem) { if (!disposed) setError(problem instanceof Error ? problem.message : "查询中断，刷新页面可读取原试验。"); }
    }
    timer = setTimeout(poll, 500);
    return () => { disposed = true; clearTimeout(timer); };
  }, [token, activeTrial]);

  async function savePrompt(variant: Variant) {
    setSaving(variant); setError(""); setNotice("");
    const draft = { label: prompts[variant].label, text: prompts[variant].text };
    try {
      const saved = await evaluationRequest<SavedPrompt>(token, "/prompt-versions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) });
      setSavedPrompts((current) => [saved, ...current.filter((item) => item.prompt_id !== saved.prompt_id)]);
      setNotice(`已保存版本：${saved.label}`);
    } catch (problem) { setError(problem instanceof Error ? problem.message : "版本保存失败，输入已保留。"); }
    finally { setSaving(null); }
  }

  async function activatePrompt() {
    setActivating(true); setError(""); setNotice("");
    try {
      const current = await evaluationRequest<SavedPrompt>(token, "/active-prompt", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt_id: activeChoice }) });
      setActivePrompt(current); setNotice(`全局生效版本已切换为：${current.label}，之后的新回答使用此版本。`);
    } catch (problem) { setError(problem instanceof Error ? problem.message : "切换失败，原生效版本保持不变。"); }
    finally { setActivating(false); }
  }

  async function start() {
    setBusy(true); setError("");
    const payload = { query, material, prompts: draftPrompts(prompts) };
    const fingerprint = JSON.stringify(payload);
    if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint, id: crypto.randomUUID() };
    try {
      const trial = await evaluationRequest<Trial>(token, "/explanation-trials", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ submission_id: pending.current.id, ...payload }) });
      setSelected(trial); setTrials((items) => [trial, ...items.filter((item) => item.trial_id !== trial.trial_id)]);
      pending.current = null;
      evaluationRequest<SavedPrompt[]>(token, "/prompt-versions").then(setSavedPrompts).catch(() => {});
    } catch (problem) { setError(problem instanceof Error ? problem.message : "提交失败；重试会沿用原试验标识。"); }
    finally { setBusy(false); }
  }

  return <div className="space-y-3">
    <section className="space-y-3 rounded-xl border bg-white p-3">
      <div className="space-y-2 rounded-lg bg-emerald-50 p-2.5 text-xs text-emerald-900">
        <div className="flex flex-wrap items-center gap-2"><p className="mr-auto">全局生效：<strong>{activePrompt?.label ?? "读取中…"}</strong></p><select aria-label="选择全局版本" className={`${field} sm:w-64`} value={activeChoice} onChange={(e) => setActiveChoice(e.target.value)}>{savedPrompts.map((item) => <option key={item.prompt_id} value={item.prompt_id}>{item.label}{item.prompt_id === activePrompt?.prompt_id ? "（当前生效）" : ""} · {item.version}</option>)}</select><button className={button} disabled={activating || !activeChoice || activeChoice === activePrompt?.prompt_id} onClick={() => void activatePrompt()}>{activating ? "正在切换…" : "设为全局生效版本"}</button></div>
        <p>保存和对比不会自动切换全局版本，切换后用于新回答。</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2"><label className="block space-y-1 text-xs">用户问题<textarea aria-label="用户问题" className={field} maxLength={3000} rows={2} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="输入要比较的问题" /></label><label className="block space-y-1 text-xs">固定输入材料（可选）<textarea aria-label="固定输入材料" className={field} maxLength={18000} rows={2} value={material} onChange={(e) => setMaterial(e.target.value)} placeholder="粘贴专业原文、检索证据、表头与单位" /></label></div>
    </section>
    <div className="grid gap-3 lg:grid-cols-2">{variants.map((variant) => <section key={variant} aria-label={`${side[variant]} Prompt 编辑`} className="space-y-2 rounded-xl border bg-white p-3">
      <h3 className="text-sm font-semibold">{variant === "baseline" ? "左侧：历史 Prompt" : "右侧：新增或历史 Prompt"}</h3>
      <div className={`grid gap-2 ${variant === "candidate" ? "sm:grid-cols-2" : ""}`}><label className="block min-w-0 space-y-1 text-xs">{variant === "baseline" ? "选择历史版本" : "选择版本 / 新增"}<select aria-label={`${side[variant]}已保存版本`} className={field} value={savedPrompts.find((item) => item.label === prompts[variant].label && item.text === prompts[variant].text)?.prompt_id ?? ""} onChange={(e) => { const saved = savedPrompts.find((item) => item.prompt_id === e.target.value); if (saved) setPrompts((current) => ({ ...current, [variant]: { label: saved.label, text: saved.text } })); else if (variant === "candidate") setPrompts((current) => ({ ...current, candidate: { ...current.candidate, label: "" } })); }}><option value="" disabled={variant === "baseline"}>{variant === "baseline" ? "请选择已保存版本" : "新增版本"}</option>{savedPrompts.map((item) => <option key={item.prompt_id} value={item.prompt_id}>{item.label} · {item.version}</option>)}</select></label>
      {variant === "candidate" && <label className="block min-w-0 space-y-1 text-xs">名称 / 版本<input aria-label={`${side[variant]} Prompt 名称`} className={field} maxLength={100} value={prompts[variant].label} onChange={(e) => setPrompts((current) => ({ ...current, [variant]: { ...current[variant], label: e.target.value } }))} /></label>}</div>
      <PromptContent label={`${side[variant]} Prompt`} value={prompts[variant].text} readOnly={variant === "baseline"} onChange={(text) => setPrompts((current) => ({ ...current, [variant]: { ...current[variant], text } }))} />
      {variant === "candidate" && <button className={button} disabled={saving !== null || !prompts[variant].label.trim() || !prompts[variant].text.trim()} onClick={() => void savePrompt(variant)}>{saving === variant ? "正在保存…" : "保存为新版本"}</button>}
    </section>)}</div>
    <div className="flex flex-wrap items-center gap-2"><button className="rounded-lg bg-emerald-800 px-3 py-1.5 text-sm text-white disabled:opacity-50" disabled={busy || !method || !query.trim() || variants.some((variant) => !prompts[variant].text.trim() || !prompts[variant].label.trim())} onClick={() => void start()}>{busy ? "正在提交…" : "生成同题对照"}</button>
      <button className={button} disabled={!savedPrompts.some((item) => item.label === prompts.candidate.label && item.text === prompts.candidate.text)} onClick={() => setPrompts((current) => ({ ...current, baseline: { ...current.candidate } }))}>将右侧版本用于左侧</button></div>
    {error && <p role="alert" className="text-sm text-amber-900">{error}</p>}
    {notice && <p className="text-sm text-emerald-800">{notice}</p>}
    <section className="flex flex-wrap items-end gap-2 rounded-xl border bg-white p-3"><label className="block min-w-48 flex-1 space-y-1 text-xs">已保存的对照<select aria-label="已保存的对照" className={field} value={selected?.trial_id ?? ""} onChange={(e) => setSelected(trials.find((item) => item.trial_id === e.target.value) ?? null)}><option value="">请选择</option>{trials.map((trial) => <option value={trial.trial_id} key={trial.trial_id}>{trial.query} · {trial.prompts ? `${trial.prompts.baseline.label} / ${trial.prompts.candidate.label}` : "历史解释对照"} · {status[trial.status] ?? trial.status}</option>)}</select></label>
      {selected?.prompts && <button className={button} onClick={() => { setQuery(selected.query); setMaterial(selected.material); setPrompts(draftPrompts(selected.prompts!)); }}>载入此记录继续迭代</button>}
    </section>
    {selected && <>
      <p role="status" className="text-xs">{status[selected.status] ?? selected.status}</p><details className="rounded-xl border bg-white p-3"><summary className="cursor-pointer text-xs">本次对照的问题与材料</summary><p className="mt-2 whitespace-pre-wrap text-sm">{selected.query}</p><p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">{selected.material || "未提供额外材料"}</p></details>
      <div className="grid gap-3 lg:grid-cols-2">{variants.map((variant) => <section aria-label={`${side[variant]}对照结果`} className="space-y-2 rounded-xl border bg-white p-3" key={`${selected.trial_id}:${variant}`}><h3 className="text-sm font-semibold">{side[variant]} Prompt 与回答</h3>
        {(selected.prompts?.[variant] ?? selected.variants[variant]?.prompt) ? <PromptSnapshot variant={variant} prompt={(selected.prompts?.[variant] ?? selected.variants[variant]?.prompt)!} /> : <p className="text-sm text-amber-800">此历史记录未保存 Prompt 原文，无法还原当时的完整提示词。</p>}
        <div className="border-t pt-3"><h4 className="mb-2 text-sm font-medium">对应回答</h4><div className="text-sm leading-7"><MarkdownAnswer content={selected.variants[variant]?.answer ?? "尚无已完成回答"} /></div></div>{selected.variants[variant]?.model && <p className="text-xs text-slate-500">模型 {selected.variants[variant]?.model}</p>}
      </section>)}</div>
    </>}
    {method && <details className="rounded-xl border bg-white p-3 text-xs leading-6 text-slate-500"><summary className="cursor-pointer">默认表达规则的参考来源</summary><p>{method.adaptation}</p><p>{method.notice}</p><a href={method.url} target="_blank" rel="noopener noreferrer" className="text-emerald-800 underline">{method.title} · {method.edition}</a></details>}
  </div>;
}

function PromptSnapshot({ variant, prompt }: { variant: Variant; prompt: Prompt }) {
  return <><p className="text-sm font-medium text-emerald-900">{prompt.label}</p><PromptContent label={`本次${side[variant]} Prompt`} value={prompt.text} readOnly compact /><p className="text-xs text-slate-400">版本 {prompt.version}</p></>;
}

function PromptContent({ label, value, readOnly = false, compact = false, onChange }: { label: string; value: string; readOnly?: boolean; compact?: boolean; onChange?: (text: string) => void }) {
  const [preview, setPreview] = useState(true);
  return <div className="space-y-2">
    <div className="flex items-center justify-between gap-2"><p className="text-xs">Prompt 内容</p><div role="group" aria-label={`${label} 展示方式`} className="flex gap-1"><button type="button" className={`${button} ${preview ? "border-emerald-600 bg-emerald-50 text-emerald-900" : ""}`} aria-pressed={preview} onClick={() => setPreview(true)}>Markdown</button><button type="button" className={`${button} ${!preview ? "border-emerald-600 bg-emerald-50 text-emerald-900" : ""}`} aria-pressed={!preview} onClick={() => setPreview(false)}>{readOnly ? "原文" : "编辑"}</button></div></div>
    {preview ? <div role="region" aria-label={`${label} Markdown 预览`} className={`${compact ? "max-h-48" : "h-52"} overflow-auto rounded-lg border bg-slate-50 p-2.5 text-sm leading-6`}><MarkdownAnswer content={value || "暂无内容"} /></div> : <textarea aria-label={label} readOnly={readOnly} className={`${field} h-52 resize-y font-mono leading-6`} maxLength={24000} rows={8} value={value} onChange={(event) => onChange?.(event.target.value)} />}
  </div>;
}
