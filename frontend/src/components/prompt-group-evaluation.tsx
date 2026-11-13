"use client";

import { useEffect, useRef, useState } from "react";
import { evaluationJson, evaluationRequest } from "@/lib/evaluation-api";
import { type GroupActivation, type Prompt, type PromptGroup, type TaskCatalog, type TaskScope, type Trial, type Variant, scopes, taskScopes, variants, side, shots, promptButton as button, promptField as field, trialStatuses } from "@/lib/prompt-types";
import { GroupSnapshot, PromptGroupResults } from "./prompt-group-results";
import { PromptGroupActivationButton } from "./prompt-group-activation";

type Selection = { groupId: string; label: string; promptId: string; taskIds: Record<TaskScope, string> };
const selection = (g: PromptGroup): Selection => ({ groupId: g.group_id, label: g.label, promptId: g.communication.prompt_id, taskIds: Object.fromEntries(taskScopes.map(s => [s, g.task_prompts[s].prompt_id])) as Record<TaskScope, string> });

export function PromptGroupEvaluation({ token, developer, prompts, tasks, active, groups, setGroups, sourceRun, activeGroup, activating, onActivate, compareGroup }: GroupActivation & {
  token: string; developer: boolean; prompts: Prompt[]; tasks: TaskCatalog | null; active: Prompt; groups: PromptGroup[]; setGroups: (fn: (groups: PromptGroup[]) => PromptGroup[]) => void; sourceRun: string;
  compareGroup: PromptGroup | null;
}) {
  const [chosen, setChosen] = useState<Record<Variant, Selection>>({ baseline: selection(groups[0]), candidate: selection(groups[0]) });
  const [query, setQuery] = useState("");
  const [material, setMaterial] = useState("");
  const [followups, setFollowups] = useState<string[]>([]);
  const [history, setHistory] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [trials, setTrials] = useState<Trial[]>([]);
  const [selected, setSelected] = useState<Trial | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState<Variant | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef<{ fingerprint: string; id: string } | null>(null);
  const [lastCompareGroup, setLastCompareGroup] = useState<PromptGroup | null>(null);
  if (compareGroup !== lastCompareGroup) {
    setLastCompareGroup(compareGroup);
    if (compareGroup) {
      setChosen(current => ({ ...current, candidate: selection(compareGroup) }));
      setNotice(`已将方案「${compareGroup.label}」载入右侧，可选择左侧方案后开始测评。`);
    }
  }
  useEffect(() => {
    let disposed = false;
    evaluationRequest<Trial[]>(token, "/explanation-trials").then(list => { if (!disposed) { setTrials(list); setSelected(list[0] ?? null); } }).catch(e => { if (!disposed) setError(e.message); });
    return () => { disposed = true; };
  }, [token]);
  useEffect(() => {
    if (!sourceRun) return;
    let disposed = false;
    evaluationRequest<{ turns: { run_id: string; input: string; request_snapshot?: { history?: typeof history } }[] }>(token, `/sessions/${encodeURIComponent(sourceRun)}`).then(session => {
      if (disposed) return;
      const turn = session.turns.find(t => t.run_id === sourceRun);
      if (!turn) return;
      if (turn.input.length > 3000) { setError("原问题超过3000字，请摘录要测评的问题。"); return; }
      setQuery(turn.input); setHistory(turn.request_snapshot?.history ?? []); setNotice("已载入原问题和初始历史，两组将各自继续生成回答。");
    }).catch(e => { if (!disposed) setError(e.message); });
    return () => { disposed = true; };
  }, [token, sourceRun]);
  const running = selected && ["accepted", "running"].includes(selected.status) ? selected.trial_id : null;
  useEffect(() => {
    if (!running) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const trial = await evaluationRequest<Trial>(token, `/explanation-trials/${running}`);
        if (disposed) return;
        setSelected(trial); setTrials(list => [trial, ...list.filter(t => t.trial_id !== trial.trial_id)]);
        if (["accepted", "running"].includes(trial.status)) timer = setTimeout(poll, 1500);
      } catch (e) { if (!disposed) setError(e instanceof Error ? e.message : "读取测评失败，刷新可恢复记录。"); }
    }
    timer = setTimeout(poll, 500);
    return () => { disposed = true; clearTimeout(timer); };
  }, [token, running]);
  function change(variant: Variant, updates: Partial<Selection>) {
    setChosen(current => ({ ...current, [variant]: { ...current[variant], ...updates } }));
  }
  async function saveGroup(variant: Variant) {
    setSaving(variant); setError("");
    const draft = chosen[variant];
    try {
      const group = await evaluationRequest<PromptGroup>(token, "/prompt-groups", evaluationJson({ label: draft.label, prompt_id: draft.promptId, task_prompt_ids: draft.taskIds }));
      setGroups(list => [group, ...list]); change(variant, selection(group)); setNotice(`已保存版本组：${group.label}；可用于测评。`);
    } catch (e) { setError(e instanceof Error ? e.message : "版本组保存失败"); }
    finally { setSaving(null); }
  }
  async function start() {
    setBusy(true); setError(""); setNotice("");
    const payload = { query, material, followups, history, groups: { baseline: chosen.baseline.groupId, candidate: chosen.candidate.groupId } };
    const fingerprint = JSON.stringify(payload);
    if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint, id: crypto.randomUUID() };
    try {
      const trial = await evaluationRequest<Trial>(token, "/explanation-trials", evaluationJson({ ...payload, submission_id: pending.current.id }));
      setSelected(trial); setTrials(list => [trial, ...list.filter(t => t.trial_id !== trial.trial_id)]); pending.current = null;
    } catch (e) { setError(e instanceof Error ? e.message : "提交失败，重试会沿用原提交标识。"); }
    finally { setBusy(false); }
  }
  function loadTrial(trial: Trial) {
    if (!trial.groups) return;
    setQuery(trial.query); setMaterial(trial.material); setFollowups(trial.followups ?? []); setHistory(trial.history ?? []);
    setChosen({ baseline: selection(trial.groups.baseline), candidate: selection(trial.groups.candidate) });
    setNotice("已载入本次测评的版本组与输入，可调整后另存新组。");
  }
  const changes = [chosen.baseline.promptId !== chosen.candidate.promptId ? "全局表达" : "", ...taskScopes.filter(s => chosen.baseline.taskIds[s] !== chosen.candidate.taskIds[s]).map(s => scopes[s])].filter(Boolean);
  const taskVersion = (variant: Variant, scope: TaskScope) => tasks?.versions.find(p => p.prompt_id === chosen[variant].taskIds[scope]) ?? groups.find(g => g.group_id === chosen[variant].groupId)?.task_prompts[scope];
  return <div className="space-y-4">
    <div><h2 className="font-semibold">Prompt 组测评</h2><p className="mt-1 text-sm text-slate-500">每组由全局表达和三类任务版本组成。两组使用相同问题、材料与初始历史，按正常流程执行；后续问题使用各组自己的新回答继续。</p></div>
    <div className="grid gap-4 lg:grid-cols-2">{variants.map(variant => {
      const draft = chosen[variant], saved = groups.find(g => g.group_id === draft.groupId);
      return <section key={variant} aria-label={`${side[variant]} Prompt 版本组`} className="min-w-0 space-y-3 rounded-xl border bg-white p-4">
        <h3 className="font-semibold">{side[variant]}版本组</h3>
        <fieldset disabled={saving !== null || busy} className="min-w-0 space-y-3">
          <label className="block space-y-1 text-sm">选择已保存的组<select aria-label={`${side[variant]}已保存版本组`} className={field} value={draft.groupId} onChange={e => { const group = groups.find(g => g.group_id === e.target.value); if (group) change(variant, selection(group)); }}><option value="" disabled>未保存的组合</option>{groups.map(g => <option key={g.group_id} value={g.group_id}>{g.label} · {g.version}</option>)}</select></label>
          {developer && <><label className="block space-y-1 text-sm">全局表达<select aria-label={`${side[variant]}全局表达版本`} className={field} value={draft.promptId} onChange={e => change(variant, { promptId: e.target.value, groupId: "" })}>{prompts.map(p => <option key={p.prompt_id} value={p.prompt_id}>{p.label} · {p.version}</option>)}</select></label>
            {taskScopes.map(scope => <label key={scope} className="block space-y-1 text-sm">{scopes[scope]}<select aria-label={`${side[variant]}${scopes[scope]}版本`} className={field} value={draft.taskIds[scope]} onChange={e => change(variant, { taskIds: { ...draft.taskIds, [scope]: e.target.value }, groupId: "" })}>{tasks?.versions.filter(p => p.scope === scope).map(p => <option key={p.prompt_id} value={p.prompt_id}>{p.label} · {shots(p)} · {p.version}</option>)}</select></label>)}
            <div className="flex flex-wrap gap-2"><button type="button" className={button} onClick={() => tasks && change(variant, { promptId: active.prompt_id, taskIds: Object.fromEntries(taskScopes.map(s => [s, tasks.active[s].prompt_id])) as Record<TaskScope, string>, groupId: "" })}>载入当前生效组合</button><button type="button" className={button} onClick={() => change(variant, { ...chosen[variant === "baseline" ? "candidate" : "baseline"], groupId: "", label: "" })}>复制另一侧组合</button></div>
            <label className="block space-y-1 text-sm">另存组名称<input aria-label={`${side[variant]}版本组名称`} className={field} maxLength={100} value={draft.label} onChange={e => change(variant, { label: e.target.value, groupId: "" })} placeholder="例如：基准组 / 概念 few-shot 组" /></label>
            <button type="button" className={button} disabled={!draft.label.trim() || !draft.promptId || taskScopes.some(s => !draft.taskIds[s])} onClick={() => void saveGroup(variant)}>{saving === variant ? "正在保存…" : `保存${side[variant]}版本组`}</button>
          </>}
        </fieldset>
        {developer && saved && <PromptGroupActivationButton group={saved} activeGroup={activeGroup} activating={activating} onActivate={onActivate} label={`将${side[variant]}方案设为当前方案`} />}
        {saved && <details><summary className="cursor-pointer text-sm">查看组内 Prompt 与示例</summary><div className="mt-3"><GroupSnapshot group={saved} /></div></details>}
      </section>;
    })}</div>
    <div className="space-y-2 rounded-lg bg-emerald-50 p-3 text-sm" aria-label="版本组差异">{changes.length ? `两组不同的层：${changes.join("、")}` : "两组版本完全相同，可用作重复运行基准。"}
      {taskScopes.filter(s => chosen.baseline.taskIds[s] !== chosen.candidate.taskIds[s]).map(scope => {
        const left = taskVersion("baseline", scope), right = taskVersion("candidate", scope);
        if (!left || !right) return null;
        const sameRules = left.text === right.text;
        const sameExamples = JSON.stringify(left.examples) === JSON.stringify(right.examples);
        return <p className="text-xs" key={scope}>{scopes[scope]}：{sameRules ? sameExamples ? "规则与示例相同，版本记录不同" : "任务规则相同，仅示例不同" : "任务规则不同"}；左侧 {shots(left)}，右侧 {shots(right)}。</p>;
      })}
      <p className="text-xs text-slate-600">对比 zero-shot / few-shot 时，可固定全局和任务规则，仅替换带示例的任务版本。正常检索可能取得不同材料，结果需结合每轮取证核对。</p></div>
    <section className="space-y-3 rounded-xl border bg-white p-4" aria-label="共同测评输入">
      <label className="block space-y-1 text-sm">用户问题<textarea aria-label="用户问题" className={field} rows={3} maxLength={3000} value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label className="block space-y-1 text-sm">固定输入材料（可选）<textarea aria-label="固定输入材料" className={field} rows={3} maxLength={18000} value={material} onChange={e => setMaterial(e.target.value)} placeholder="两组共同提供的原文、表格或证据；正常流程仍会按问题取证" /></label>
      {!!history.length && <details><summary className="cursor-pointer text-sm">共同初始历史 · {history.length} 条</summary>{history.map((t, i) => <p className="mt-2 whitespace-pre-wrap text-sm" key={i}>{t.role === "user" ? "用户" : "助手"}：{t.content}</p>)}<button className={`${button} mt-2`} onClick={() => setHistory([])}>清除初始历史</button></details>}
      {followups.map((q, i) => <div key={i} className="flex items-start gap-2"><label className="min-w-0 flex-1 space-y-1 text-sm">第 {i + 2} 轮问题<textarea aria-label={`第${i + 2}轮问题`} className={field} maxLength={3000} rows={2} value={q} onChange={e => setFollowups(list => list.map((item, j) => j === i ? e.target.value : item))} /></label><button className={`${button} mt-6`} onClick={() => setFollowups(list => list.filter((_, j) => j !== i))}>移除第 {i + 2} 轮</button></div>)}
      <button className={button} disabled={followups.length >= 5} onClick={() => setFollowups(list => [...list, ""])}>添加后续问题</button>
      <div className="flex flex-wrap items-center gap-3"><button className="rounded-lg bg-emerald-800 px-4 py-2 text-sm text-white disabled:opacity-50" disabled={busy || saving !== null || !!running || !query.trim() || followups.some(q => !q.trim()) || variants.some(v => !chosen[v].groupId)} onClick={() => void start()}>{busy ? "正在提交…" : "开始左右组测评"}</button>{variants.some(v => !chosen[v].groupId) && <p className="text-xs text-amber-800">请先保存两侧的版本组合。</p>}</div>
    </section>
    {error && <p role="alert" className="text-sm text-red-800">{error}</p>}{notice && <p className="text-sm text-emerald-800">{notice}</p>}
    <section className="flex flex-wrap items-end gap-2 rounded-xl border bg-white p-4"><label className="min-w-0 flex-1 space-y-1 text-sm">历史测评<select aria-label="历史测评" className={field} value={selected?.trial_id ?? ""} onChange={e => setSelected(trials.find(t => t.trial_id === e.target.value) ?? null)}><option value="">请选择</option>{trials.map(t => <option key={t.trial_id} value={t.trial_id}>{t.query} · {t.groups ? `${t.groups.baseline.label} / ${t.groups.candidate.label}` : "历史表达层对照"} · {trialStatuses[t.status] ?? t.status}</option>)}</select></label>{selected?.groups && <button className={button} onClick={() => loadTrial(selected)}>载入本次组合与输入</button>}</section>
    {selected && <PromptGroupResults trial={selected} activation={developer ? { activeGroup, activating, onActivate } : undefined} />}
  </div>;
}
