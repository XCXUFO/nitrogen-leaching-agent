"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { evaluationHref } from "@/lib/evaluation-navigation";
import { evaluationJson, evaluationRequest as request } from "@/lib/evaluation-api";
import type { EvaluationCase, Evaluator } from "@/lib/evaluation-api";

export type EvaluationTask = {
  task_id: string; title: string; case_versions: { case_id: string; case_version: number }[];
  build_version: string; knowledge_version: string; runtime_config_version: string;
  created_at: string; created_by: string;
};
type Progress = {
  task: EvaluationTask; scope: "all" | "own";
  summary: { total_cases: number; prepared_cases: number; started_cases: number; reviewed_cases: number; executions: number };
  cases: { case_id: string; case_version: number; started: boolean; reviewed: boolean;
    executions: { execution_id: string; tester_id: string; status: string; overall: string | null; event_count: number }[] }[];
};
const field = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
const button = "rounded-md border border-input px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const keyOf = (item: EvaluationCase) => `${item.case.case_id}@${item.case.version}`;
const outcomes: Record<string, string> = { pass: "通过", partial: "部分通过", fail: "不通过", blocked: "受阻" };

export function EvaluationTasks({ token, role, cases, tasks, currentCase, selectedTask, revision, view = "list",
  onSelectTask, onTaskCreated, onOpenExecution, onRefresh }: {
  token: string; role: Evaluator["role"]; cases: EvaluationCase[]; tasks: EvaluationTask[];
  currentCase?: EvaluationCase; selectedTask: string; revision: string;
  view?: "list" | "new" | "detail";
  onSelectTask: (id: string) => void; onTaskCreated: (task: EvaluationTask) => void;
  onOpenExecution: (id: string) => void; onRefresh: () => Promise<void>;
}) {
  const [selection, setSelection] = useState<string[] | null>(null);
  const selected = selection ?? (currentCase ? [keyOf(currentCase)] : []);
  const [caseSearch, setCaseSearch] = useState("");
  const [taskSearch, setTaskSearch] = useState("");
  const [title, setTitle] = useState("");
  const [build, setBuild] = useState("");
  const [knowledge, setKnowledge] = useState("");
  const [config, setConfig] = useState("");
  const [progressLoad, setProgressLoad] = useState<{ key: string; progress: Progress | null } | null>(null);
  const [generation, setGeneration] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const progressKey = JSON.stringify([token, selectedTask, revision, generation]);
  const progress = progressLoad?.key === progressKey ? progressLoad.progress : null;
  const loading = Boolean(selectedTask) && progressLoad?.key !== progressKey;
  useEffect(() => {
    let active = true;
    void request<{ build_version: string; runtime_config_version: string }>(token, "/config")
      .then((value) => { if (active) { setBuild(value.build_version); setConfig(value.runtime_config_version); } })
      .catch((err) => { if (active) setError(String(err)); });
    return () => { active = false; };
  }, [token, generation]);
  useEffect(() => {
    let active = true;
    if (!selectedTask) return;
    void request<Progress>(token, `/tasks/${selectedTask}/progress`)
      .then((value) => { if (active) setProgressLoad({ key: progressKey, progress: value }); })
      .catch((err) => {
        if (active) { setError(String(err)); setProgressLoad({ key: progressKey, progress: null }); }
      });
    return () => { active = false; };
  }, [token, selectedTask, progressKey]);
  async function perform(operation: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await operation(); } catch (err) { setError(err instanceof Error ? err.message : "任务操作失败。"); }
    finally { setBusy(false); }
  }
  const visibleCases = cases.filter((item) => `${keyOf(item)} ${item.case.title}`.toLowerCase().includes(caseSearch.toLowerCase()));
  const visibleTasks = tasks.filter((item) => `${item.title} ${item.task_id} ${item.build_version}`.toLowerCase().includes(taskSearch.toLowerCase()));
  if (view === "new" && role !== "developer") return <p role="alert">当前身份只能查看任务和准备自己的执行。</p>;
  return <section aria-label="任务管理" className="space-y-4 rounded-lg border p-5">
    <div className="flex flex-wrap justify-between gap-3"><div><h2 className="text-lg font-semibold">任务管理</h2>
      <p className="text-xs text-muted-foreground">冻结多个用例版本，逐项查看执行和评分进度。已评分表示记录完整，不表示通过。</p></div>
      <div className="flex gap-2">{role === "developer" && view === "list" && <Link className="rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white" href={evaluationHref("tasks", "new")}>新建任务</Link>}<button className={button} disabled={busy} onClick={() => void perform(async () => { await onRefresh(); setGeneration((value) => value + 1); })}>刷新任务</button></div></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <fieldset disabled={busy} className="min-w-0 space-y-5">
      {view === "new" && role === "developer" && <form className="max-w-3xl space-y-3 rounded border p-4" onSubmit={(event) => {
        event.preventDefault(); void perform(async () => {
          const chosen = cases.filter((item) => selected.includes(keyOf(item)));
          if (!chosen.length || chosen.length > 50) throw new Error("请选择 1 至 50 个用例版本。");
          const created = await request<EvaluationTask>(token, "/tasks", evaluationJson({ title: title.trim(),
            case_versions: chosen.map(({ case: item }) => ({ case_id: item.case_id, case_version: item.version })),
            build_version: build.trim(), knowledge_version: knowledge.trim() }));
          onTaskCreated(created); setTitle(""); setNotice(`任务已创建，冻结 ${chosen.length} 个用例版本。`);
        });
      }}>
        <h3 className="font-medium">新建多用例任务</h3>
        <input aria-label="任务标题" className={field} required maxLength={200} value={title} placeholder="任务标题" onChange={(e) => setTitle(e.target.value)} />
        <input aria-label="构建版本" className={field} required maxLength={160} value={build} placeholder="构建版本" onChange={(e) => setBuild(e.target.value)} />
        <input aria-label="知识库版本" className={field} required maxLength={160} value={knowledge} placeholder="知识库版本" onChange={(e) => setKnowledge(e.target.value)} />
        <input aria-label="检索任务用例" className={field} value={caseSearch} placeholder="按用例编号、版本或标题检索" onChange={(e) => setCaseSearch(e.target.value)} />
        <div className="flex flex-wrap items-center gap-2 text-xs"><span>已选 {selected.length} / 50</span>
          <button type="button" className={button} onClick={() => setSelection([])}>清空选择</button>
          <button type="button" className={button} disabled={!currentCase} onClick={() => setSelection(currentCase ? [keyOf(currentCase)] : [])}>仅选当前用例</button></div>
        <div className="max-h-60 space-y-2 overflow-auto rounded border p-2">
          {visibleCases.map((item) => <label key={keyOf(item)} className="flex items-start gap-2 text-sm">
            <input type="checkbox" aria-label={`任务用例 ${keyOf(item)}`} checked={selected.includes(keyOf(item))}
              disabled={selected.length >= 50 && !selected.includes(keyOf(item))}
              onChange={(e) => setSelection(e.target.checked ? [...selected, keyOf(item)] : selected.filter((key) => key !== keyOf(item)))} />
            <span>{keyOf(item)} · {item.case.title}</span></label>)}
          {!visibleCases.length && <p className="text-xs">没有匹配的用例。</p>}
        </div>
        <button className={button} disabled={!selected.length || selected.length > 50 || !config}>创建任务</button>
      </form>}
      {view === "list" && <div className="min-w-0 space-y-3"><h3 className="font-medium">任务列表</h3>
        <input aria-label="检索任务" className={field} value={taskSearch} placeholder="按标题、任务编号或构建检索" onChange={(e) => setTaskSearch(e.target.value)} />
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr>{["任务名称", "用例版本数", "构建版本", "创建人", "创建时间", "操作"].map((label) => <th key={label} className="whitespace-nowrap p-3 font-medium">{label}</th>)}</tr></thead><tbody>
          {visibleTasks.map((task) => <tr key={task.task_id} className="border-t"><td className="p-3 font-medium">{task.title}</td><td className="p-3">{task.case_versions.length}</td><td className="max-w-56 break-all p-3 text-xs">{task.build_version}</td><td className="p-3">{task.created_by}</td><td className="whitespace-nowrap p-3 text-xs">{new Date(task.created_at).toLocaleString()}</td><td className="p-3"><button className="whitespace-nowrap text-emerald-700 underline" onClick={() => onSelectTask(task.task_id)}>查看任务</button></td></tr>)}
        </tbody></table>{!visibleTasks.length && <p className="py-10 text-center text-sm text-muted-foreground">没有匹配的任务。创建任务后，可批量准备测试执行。</p>}</div>
      </div>}
    </fieldset>
    {loading && <p role="status">正在读取任务详情…</p>}
    {view === "detail" && progress && <div aria-label="任务详情" className="space-y-3 rounded border p-4">
      <h3 className="font-medium">{progress.task.title}</h3>
      <p className="break-all text-xs text-muted-foreground">{progress.task.task_id} · {progress.task.runtime_config_version}</p>
      <p className="text-sm">{progress.scope === "own" ? "我的进度" : "任务整体进度"}：{progress.summary.total_cases} 个用例版本 · 已准备 {progress.summary.prepared_cases} · 已开始 {progress.summary.started_cases} · 已评分 {progress.summary.reviewed_cases} · 执行 {progress.summary.executions} 次</p>
      <p className="text-xs text-muted-foreground">批量准备为本人补齐尚无执行的用例；重复点击不会新建重复记录。打开后重置上下文，再按用例步骤执行并独立评分。</p>
      {config && config !== progress.task.runtime_config_version && <p className="text-sm text-amber-800">当前服务配置与冻结任务不同，请为新版本新建任务；历史证据仍可查看。</p>}
      <button className={button} disabled={busy || !config || config !== progress.task.runtime_config_version} onClick={() => void perform(async () => {
        await request(token, `/tasks/${progress.task.task_id}/prepare`, evaluationJson({}));
        await onRefresh(); setGeneration((value) => value + 1); setNotice("已为本人补齐执行，请逐项打开继续。");
      })}>批量准备我的执行</button>
      {role === "developer" && <button className={`${button} ml-2`} disabled={busy} onClick={() => void perform(async () => {
        const evidence = await request<Record<string, unknown>>(token, `/tasks/${progress.task.task_id}/evidence`);
        const url = URL.createObjectURL(new Blob([JSON.stringify(evidence, null, 2)], { type: "application/json" }));
        const link = document.createElement("a"); link.href = url; link.download = `task-${progress.task.task_id}-evidence.json`;
        link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        setNotice("任务证据已下载；文件可能包含测试原句和审核备注，请按项目资料权限保存。");
      })}>下载任务证据 JSON</button>}
      <div className="grid gap-3 md:grid-cols-2">{progress.cases.map((item) => <article key={`${item.case_id}@${item.case_version}`} className="min-w-0 space-y-2 rounded border p-3">
        <h4 className="text-sm font-medium">{item.case_id}@{item.case_version} · {item.reviewed ? "已有评分" : item.started ? "执行中" : item.executions.length ? "待执行" : "尚未准备"}</h4>
        {item.executions.map((entry) => <div key={entry.execution_id} className="text-xs">
          <p>{entry.tester_id} · {entry.event_count} 步 · {entry.overall ? outcomes[entry.overall] : "待评分"}</p>
          <button className="break-all text-left underline" disabled={busy} onClick={() => onOpenExecution(entry.execution_id)}>打开执行 {entry.execution_id}</button>
        </div>)}
      </article>)}</div>
    </div>}
  </section>;
}
