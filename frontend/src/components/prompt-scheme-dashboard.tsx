"use client";

import { useState } from "react";
import { type GroupActivation, type PromptGroup, groupIsActive, scopes, shots, taskScopes, promptButton as button, promptField as field } from "@/lib/prompt-types";
import { GroupSnapshot } from "./prompt-group-results";
import { PromptGroupActivationButton } from "./prompt-group-activation";

function SchemeVersions({ group }: { group: Pick<PromptGroup, "communication" | "task_prompts"> }) {
  return <dl className="wb-scheme-versions">
    <div><dt className="text-xs text-slate-500">全局表达</dt><dd className="break-words">{group.communication.label}</dd></div>
    {taskScopes.map(scope => <div key={scope}><dt className="text-xs text-slate-500">{scopes[scope]}</dt><dd className="break-words">{group.task_prompts[scope].label}<span className="ml-2 text-xs text-slate-500">{shots(group.task_prompts[scope])}</span></dd></div>)}
  </dl>;
}

export function PromptSchemeDashboard({ groups, developer, activeGroup, activating, onActivate, onCompare }: GroupActivation & { groups: PromptGroup[]; developer: boolean; onCompare: (group: PromptGroup) => void }) {
  const [search, setSearch] = useState("");
  const exampleScopes = taskScopes.filter(scope => activeGroup.task_prompts[scope].examples?.length);
  const filtered = groups.filter(g => [g.label, g.version, g.communication.label, ...taskScopes.map(s => g.task_prompts[s].label)].join(" ").toLowerCase().includes(search.trim().toLowerCase()));
  return <div className="space-y-4">
    <section aria-label="当前生效方案" className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
      <span className="wb-status" data-status="passed">当前生效</span><p>{activeGroup.group?.label ?? "自定义组合"}</p>
      <span className="text-xs text-muted-foreground">{exampleScopes.length ? exampleScopes.map(scope => `${scopes[scope]}：${shots(activeGroup.task_prompts[scope])}`).join(" / ") : "zero-shot · 无示例"}</span>
      {!activeGroup.group && <div className="w-full"><SchemeVersions group={activeGroup} /></div>}
      {!activeGroup.group && <p className="text-xs text-slate-600">当前组合尚未保存为方案，可在组测评中载入当前生效组合后保存。</p>}
      {activeGroup.activated_at && <p className="text-xs text-slate-500">启用时间：{new Date(activeGroup.activated_at).toLocaleString("zh-CN")}{activeGroup.activated_by ? ` · 操作人：${activeGroup.activated_by}` : ""}</p>}
    </section>
    <div className="wb-panel-header pt-2"><input aria-label="搜索 Prompt 方案" name="scheme_search" autoComplete="off" className={`${field} sm:w-72`} placeholder="搜索方案或版本名称…" value={search} onChange={e => setSearch(e.target.value)} /><span className="text-xs text-slate-500">共 {groups.length} 套方案</span></div>
    <div className="wb-scheme-list">{filtered.map(group => <section key={group.group_id} aria-label={`已保存方案 ${group.label}`} className="wb-panel space-y-4">
      <div className="wb-panel-header"><h3 className="break-words font-semibold">{group.label}</h3><span className="wb-status" data-status={groupIsActive(group, activeGroup) ? "passed" : undefined}>{groupIsActive(group, activeGroup) ? "当前生效" : "已保存"}</span></div>
      <p className="break-all text-xs text-slate-500">{group.version}</p>
      <SchemeVersions group={group} />
      <div className="flex flex-wrap gap-2 border-t pt-4">{developer && <PromptGroupActivationButton group={group} activeGroup={activeGroup} activating={activating} onActivate={onActivate} />}<button type="button" className={button} onClick={() => onCompare(group)}>载入右侧测评</button></div>
      <details><summary className="cursor-pointer text-sm">查看完整 Prompt 与示例</summary><div className="mt-3"><GroupSnapshot group={group} /></div></details>
    </section>)}</div>
    {!filtered.length && <p className="text-sm text-slate-500">{groups.length ? "没有匹配的方案。" : "暂无已保存方案，可在组测评中保存版本组合。"}</p>}
    {!developer && <p className="text-sm text-slate-500">方案由开发者启用；你可以查看方案和运行对照测评。</p>}
  </div>;
}
