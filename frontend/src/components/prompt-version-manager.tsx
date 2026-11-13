"use client";

import { useState } from "react";
import { evaluationJson, evaluationRequest } from "@/lib/evaluation-api";
import { type Prompt, promptField as field, promptButton as button } from "@/lib/prompt-types";
import { PromptContent } from "./prompt-content";
import { TaskPromptEditor } from "./task-prompt-editor";

export function PromptVersionManager({ token, developer, prompts, active, activeTaskKey, onSaved, onActivated, onTasksChanged }: {
  token: string; developer: boolean; prompts: Prompt[]; active: Prompt; onSaved: (p: Prompt) => void; onActivated: (p: Prompt) => void; onTasksChanged: () => void;
  activeTaskKey: string;
}) {
  const [chosen, setChosen] = useState(active.prompt_id);
  const [label, setLabel] = useState("");
  const [text, setText] = useState(active.text);
  const [activeSelection, setActiveSelection] = useState({ current: active.prompt_id, chosen: active.prompt_id });
  const activeChoice = activeSelection.current === active.prompt_id ? activeSelection.chosen : active.prompt_id;
  if (activeSelection.current !== active.prompt_id) setActiveSelection({ current: active.prompt_id, chosen: active.prompt_id });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  async function save() {
    setBusy(true); setError("");
    try {
      const saved = await evaluationRequest<Prompt>(token, "/prompt-versions", evaluationJson({ label, text }));
      onSaved(saved); setChosen(saved.prompt_id); setLabel(""); setNotice(`已保存版本：${saved.label}；尚未启用。`);
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
    finally { setBusy(false); }
  }
  async function activate() {
    setBusy(true); setError("");
    try {
      const saved = await evaluationRequest<Prompt>(token, "/active-prompt", { ...evaluationJson({ prompt_id: activeChoice }), method: "PUT" });
      onActivated(saved); setNotice(`全局生效版本已切换为：${saved.label}，之后的新回答使用此版本。`);
    } catch (e) { setError(e instanceof Error ? e.message : "启用失败"); }
    finally { setBusy(false); }
  }
  return <div className="space-y-4">
    <section className="space-y-4 rounded-xl border bg-white p-4" aria-label="全局 Prompt 版本管理">
      <h2 className="font-semibold">全局表达 Prompt</h2>
      <div className="space-y-2 rounded-lg bg-emerald-50 p-3 text-sm"><p>全局生效：<strong>{active.label}</strong></p><div className="flex flex-wrap gap-2"><select aria-label="选择全局版本" className={`${field} sm:w-80`} value={activeChoice} onChange={e => setActiveSelection({ current: active.prompt_id, chosen: e.target.value })}>{prompts.map(p => <option key={p.prompt_id} value={p.prompt_id}>{p.label} · {p.version}</option>)}</select><button className={button} disabled={busy || activeChoice === active.prompt_id} onClick={() => void activate()}>设为全局生效版本</button></div></div>
      <label className="block space-y-1 text-sm">选择版本 / 新增<select aria-label="全局已保存版本" className={field} value={chosen} onChange={e => { setChosen(e.target.value); const p = prompts.find(p => p.prompt_id === e.target.value); setText(p?.text ?? ""); setLabel(""); }}><option value="">新增空白版本</option>{prompts.map(p => <option key={p.prompt_id} value={p.prompt_id}>{p.label} · {p.version}</option>)}</select></label>
      <PromptContent label="全局 Prompt" value={text} onChange={setText} />
      <div className="flex flex-wrap items-end gap-2"><label className="min-w-0 flex-1 space-y-1 text-sm">新版本名称<input aria-label="全局 Prompt 新版本名称" className={field} value={label} maxLength={100} onChange={e => setLabel(e.target.value)} /></label><button className={button} disabled={busy || !label.trim() || !text.trim()} onClick={() => void save()}>保存全局新版本</button></div>
    </section>
    {developer ? <TaskPromptEditor key={activeTaskKey} token={token} allowActivation onSaved={onTasksChanged} /> : <p className="text-sm text-slate-500">任务 Prompt 由开发者维护；可在组测评中选择已保存的版本组。</p>}
    <p className="text-sm text-slate-500">保存版本和运行测评不会自动启用。任务版本的示例随版本保存，可用于 zero-shot / few-shot 对照。</p>
    {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}{error && <p role="alert" className="text-sm text-red-800">{error}</p>}
  </div>;
}
