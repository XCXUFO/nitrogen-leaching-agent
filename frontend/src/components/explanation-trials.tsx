"use client";

import { useEffect, useState } from "react";
import { evaluationJson, evaluationRequest } from "@/lib/evaluation-api";
import { type ActivePromptGroup, type Prompt, type PromptGroup, type TaskCatalog } from "@/lib/prompt-types";
import { useEvaluationSession } from "./evaluation-shell";
import { PromptVersionManager } from "./prompt-version-manager";
import { PromptGroupEvaluation } from "./prompt-group-evaluation";
import { PromptSchemeDashboard } from "./prompt-scheme-dashboard";

export function ExplanationTrials({ sourceRun = "" }: { sourceRun?: string }) {
  const { token, user } = useEvaluationSession();
  const developer = user.role === "developer";
  const [tab, setTab] = useState<"schemes" | "versions" | "groups">(sourceRun ? "groups" : "schemes");
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [active, setActive] = useState<Prompt | null>(null);
  const [tasks, setTasks] = useState<TaskCatalog | null>(null);
  const [groups, setGroups] = useState<PromptGroup[]>([]);
  const [activeGroup, setActiveGroup] = useState<ActivePromptGroup | null>(null);
  const [activating, setActivating] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [compareGroup, setCompareGroup] = useState<PromptGroup | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let disposed = false;
    Promise.all([evaluationRequest<Prompt[]>(token, "/prompt-versions"), evaluationRequest<ActivePromptGroup>(token, "/active-prompt-group"), evaluationRequest<PromptGroup[]>(token, "/prompt-groups"), developer ? evaluationRequest<TaskCatalog>(token, "/task-prompts") : Promise.resolve(null)])
      .then(([versions, current, savedGroups, taskCatalog]) => { if (!disposed) { setPrompts(versions); setActive(current.communication); setActiveGroup(current); setGroups(savedGroups); setTasks(taskCatalog); setLoaded(true); } })
      .catch(e => { if (!disposed) setError(e.message); });
    return () => { disposed = true; };
  }, [token, developer]);
  async function reloadTasks() {
    try {
      const [catalog, current] = await Promise.all([evaluationRequest<TaskCatalog>(token, "/task-prompts"), evaluationRequest<ActivePromptGroup>(token, "/active-prompt-group")]);
      setTasks(catalog); setActiveGroup(current); setActive(current.communication);
    }
    catch (e) { setError(e instanceof Error ? e.message : "读取任务版本失败"); }
  }
  async function activateGroup(group: PromptGroup) {
    setActivating(group.group_id); setError(""); setNotice("");
    try {
      const current = await evaluationRequest<ActivePromptGroup>(token, "/active-prompt-group", { ...evaluationJson({ group_id: group.group_id }), method: "PUT" });
      setActiveGroup(current); setActive(current.communication); setTasks(catalog => catalog ? { ...catalog, active: current.task_prompts } : catalog);
      setNotice(`已启用方案「${current.group?.label ?? group.label}」，之后的新回答使用组内全局表达和三类任务版本。`);
    } catch (e) { setError(e instanceof Error ? e.message : "启用方案失败"); }
    finally { setActivating(null); }
  }
  async function globalActivated(prompt: Prompt) {
    setActive(prompt); setNotice("");
    try { setActiveGroup(await evaluationRequest<ActivePromptGroup>(token, "/active-prompt-group")); }
    catch (e) { setError(e instanceof Error ? e.message : "读取当前方案失败"); }
  }
  return <div className="space-y-4">
    <div role="tablist" aria-label="Prompt 管理功能" className="wb-tabs" onKeyDown={(event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
      const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      event.preventDefault(); tabs[next]?.focus(); tabs[next]?.click();
    }}>
      <button id="prompt-schemes-tab" role="tab" aria-controls="prompt-schemes-panel" aria-selected={tab === "schemes"} tabIndex={tab === "schemes" ? 0 : -1} className="wb-tab" onClick={() => setTab("schemes")}>方案看板</button>
      <button id="prompt-versions-tab" role="tab" aria-controls="prompt-versions-panel" aria-selected={tab === "versions"} tabIndex={tab === "versions" ? 0 : -1} className="wb-tab" onClick={() => setTab("versions")}>Prompt 版本管理</button>
      <button id="prompt-groups-tab" role="tab" aria-controls="prompt-groups-panel" aria-selected={tab === "groups"} tabIndex={tab === "groups" ? 0 : -1} className="wb-tab" onClick={() => setTab("groups")}>Prompt 组测评</button>
    </div>
    {error && <p role="alert" className="text-sm text-red-800">{error}</p>}
    {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}
    {!loaded && !error && <p role="status" className="text-sm">正在读取 Prompt 版本…</p>}
    {loaded && active && activeGroup && <>
      <div id="prompt-schemes-panel" role="tabpanel" aria-labelledby="prompt-schemes-tab" hidden={tab !== "schemes"}><PromptSchemeDashboard groups={groups} developer={developer} activeGroup={activeGroup} activating={activating} onActivate={activateGroup} onCompare={group => { setCompareGroup({ ...group }); setTab("groups"); }} /></div>
      <div id="prompt-versions-panel" role="tabpanel" aria-labelledby="prompt-versions-tab" hidden={tab !== "versions"}><fieldset disabled={!developer}><PromptVersionManager token={token} developer={developer} prompts={prompts} active={active} activeTaskKey={Object.values(activeGroup.task_prompts).map(p => p.prompt_id).join(":")} onSaved={p => setPrompts(list => [p, ...list.filter(item => item.prompt_id !== p.prompt_id)])} onActivated={p => void globalActivated(p)} onTasksChanged={() => void reloadTasks()} /></fieldset></div>
      <div id="prompt-groups-panel" role="tabpanel" aria-labelledby="prompt-groups-tab" hidden={tab !== "groups"}><fieldset disabled={user.role === 'tester'}>{groups.length ? <PromptGroupEvaluation token={token} developer={developer} prompts={prompts} tasks={tasks} active={active} groups={groups} setGroups={setGroups} sourceRun={sourceRun} activeGroup={activeGroup} activating={activating} onActivate={activateGroup} compareGroup={compareGroup} /> : <p className="text-sm">暂无可用的 Prompt 组。</p>}</fieldset></div>
    </>}
  </div>;
}
