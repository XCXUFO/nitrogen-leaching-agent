"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, Plus } from "lucide-react";
import { AnswerCard } from "@/components/chat/answer-card";
import { EvaluationRegressions } from "@/components/evaluation-regressions";
import { EvaluationDashboard } from "@/components/evaluation-dashboard";
import { EvaluationCatalog } from "@/components/evaluation-catalog";
import { EvaluationWorkflow } from "@/components/evaluation-workflow";
import { EvaluationTasks, type EvaluationTask } from "@/components/evaluation-tasks";
import { EvaluationReviewQueue } from "@/components/evaluation-review-queue";
import { EvaluationRuns } from "@/components/evaluation-runs";
import { useEvaluationReturnTask, useEvaluationSession } from "@/components/evaluation-shell";
import { evaluationJson, evaluationRequest as request } from "@/lib/evaluation-api";
import { canViewModule, evaluationHref, evaluationModules, type EvaluationModule } from "@/lib/evaluation-navigation";
import type { Evaluator, EvaluationCase, EvaluationExecution, EvaluationStats, ExecutionSummary } from "@/lib/evaluation-api";

const inputStyle = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
const buttonStyle = "rounded-md border border-input px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const labels: Record<string, string> = { route_correct: "路由是否正确", tool_correct: "工具使用是否正确", evidence_correct: "证据是否支持", answer_correct: "答案是否正确" };
const overallLabels: Record<string, string> = { pass: "通过", partial: "部分通过", fail: "不通过", blocked: "受阻" };
const blankScores = () => ({ overall: "", route_correct: "", tool_correct: "", evidence_correct: "", answer_correct: "", usability: "", tags: "", notes: "" });
type Scores = ReturnType<typeof blankScores>;
function validateScores(scores: Scores): string | null {
  const missing = [!scores.overall ? "总体结论" : "", ...Object.entries(labels).filter(([key]) => !scores[key as keyof Scores]).map(([, label]) => label)].filter(Boolean);
  if (missing.length) return `请先选择：${missing.join("、")}。`;
  const layers = [scores.route_correct, scores.tool_correct, scores.evidence_correct, scores.answer_correct];
  if (scores.overall === "blocked" && (layers.some((value) => value !== "n.a.") || !scores.notes.trim())) return "受阻时四个维度都应选择“不适用 / 无法判断”，并填写受阻原因。";
  if (scores.overall === "pass" && layers.some((value) => ["no", "partial"].includes(value))) return "总体选择“通过”时，维度不能选择“否”或“部分”。";
  if (scores.overall !== "blocked" && layers.every((value) => value === "n.a.")) return "请至少对一个维度作出判断。";
  if (["partial", "fail"].includes(scores.overall) && !scores.notes.trim()) return "部分通过或不通过时，请填写问题原句和具体依据。";
  const tags = scores.tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean);
  if (tags.length > 10 || tags.some((tag) => tag.length > 80)) return "问题标签最多 10 个，每个不超过 80 字。";
  return null;
}


export function EvaluationWorkspace({ section, detail = "", executionId = "", caseId = "" }: {
  section: EvaluationModule; detail?: string; executionId?: string; caseId?: string;
}) {
  const { token, user } = useEvaluationSession();
  const router = useRouter();
  const allowed = canViewModule(section, user.role);
  const [cases, setCases] = useState<EvaluationCase[]>([]);
  const [selectedCase, setSelectedCase] = useState(caseId || (section === "cases" && detail !== "drafts" ? detail : ""));
  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [execution, setExecution] = useState<EvaluationExecution | null>(null);
  const [query, setQuery] = useState("");
  const [note, setNote] = useState("");
  const [scores, setScores] = useState(blankScores);
  const [executionOffset, setExecutionOffset] = useState(0);
  const [stats, setStats] = useState<EvaluationStats | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [scoreError, setScoreError] = useState("");
  const [tasks, setTasks] = useState<EvaluationTask[]>([]);
  const [selectedTask, setSelectedTask] = useState(section === "tasks" && detail !== "new" ? detail : "");
  const currentCase = cases.find((c) => `${c.case.case_id}@${c.case.version}` === selectedCase);
  const owned = execution?.tester_id === user.tester_id;
  const editable = section === "executions" && !!execution && owned && execution.status === "open" && !execution.automation_running;
  const targetExecution = (["executions", "reviews"].includes(section) && detail && detail !== "new") ? detail : executionId;
  useEvaluationReturnTask(section === "executions" && execution?.execution_id === detail ? execution.task_id ?? null : null);

  async function perform(task: () => Promise<void>) {
    setBusy(true); setError("");
    try { await task(); } catch (err) { setError(err instanceof Error ? err.message : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }
  async function refresh(key = token, identity: Evaluator = user) {
    const [items, records, taskRecords] = await Promise.all([
      request<EvaluationCase[]>(key, "/cases?latest=false"),
      request<ExecutionSummary[]>(key, `/executions?offset=${executionOffset}`),
      request<EvaluationTask[]>(key, "/tasks"),
    ]);
    setCases(items); setExecutions(records); setTasks(taskRecords);
    if (identity.role === "developer" && section === "overview") setStats(await request<EvaluationStats>(key, "/statistics"));
  }
  useEffect(() => {
    if (!allowed) return;
    let active = true;
    async function load() {
      try {
        const [items, records, taskRecords, summary, record] = await Promise.all([
          section !== "runs" ? request<EvaluationCase[]>(token, "/cases?latest=false") : Promise.resolve([]),
          ["overview", "executions", "regressions", "issues"].includes(section) ? request<ExecutionSummary[]>(token, "/executions") : Promise.resolve([]),
          ["overview", "tasks", "executions"].includes(section) ? request<EvaluationTask[]>(token, "/tasks") : Promise.resolve([]),
          user.role === "developer" && section === "overview" ? request<EvaluationStats>(token, "/statistics") : Promise.resolve(null),
          targetExecution ? request<EvaluationExecution>(token, `/executions/${encodeURIComponent(targetExecution)}`) : Promise.resolve(null),
        ]);
        if (!active) return;
        setCases(items); setExecutions(records); setTasks(taskRecords); setStats(summary); setExecution(record);
        if (record) { setSelectedCase(`${record.case_id}@${record.case_version}`); setSelectedTask(record.task_id ?? ""); }
      } catch (problem) { if (active) setError(problem instanceof Error ? problem.message : "读取失败，请重试。"); }
      finally { if (active) setLoading(false); }
    }
    void load();
    return () => { active = false; };
  }, [allowed, token, user.role, section, detail, targetExecution]);

  function openExecution(id: string) { router.push(evaluationHref("executions", id)); }
  function showTrace(id: string) { router.push(evaluationHref("runs", id)); }
  async function mutate(path: string, init: RequestInit) {
    if (!execution) return;
    setExecution(await request<EvaluationExecution>(token, `/executions/${execution.execution_id}${path}`, init));
  }
  async function submitReview(event: FormEvent) {
    event.preventDefault();
    const problem = validateScores(scores);
    if (problem) { setScoreError(problem); return; }
    setBusy(true); setScoreError("");
    try {
      await mutate("/reviews", evaluationJson({ ...scores, usability: scores.usability ? Number(scores.usability) : null,
        tags: scores.tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean) }));
      await refresh();
    } catch (err) { setScoreError(err instanceof Error ? err.message : "评分未保存，请检查填写内容。"); }
    finally { setBusy(false); }
  }
  function selectContext(id: string) {
    router.push(`${evaluationHref(section, detail || undefined)}${id ? `?execution=${encodeURIComponent(id)}` : ""}`);
  }

  if (!allowed) return <section role="alert" className="rounded-xl border bg-white p-8"><h2 className="font-semibold">当前身份无权访问此模块</h2><p className="mt-2 text-sm text-muted-foreground">请从左侧选择可用的工作入口。</p><Link href="/evaluation/overview" className="mt-4 inline-block text-sm text-emerald-700 underline">返回工作台总览</Link></section>;
  if (loading) return <p role="status" className="rounded-xl border bg-white p-8 text-sm text-muted-foreground">正在读取数据…</p>;
  if (error && targetExecution && !execution) return <div role="alert" className="rounded-xl border bg-white p-6 text-sm text-destructive">{error}</div>;

  const contextSelector = <section className="flex flex-wrap items-center gap-3 rounded-xl border bg-white p-4">
    <label className="text-sm font-medium" htmlFor="related-execution">关联执行</label>
    <select id="related-execution" className={`${inputStyle} sm:max-w-xl`} value={targetExecution} onChange={(e) => selectContext(e.target.value)}>
      <option value="">选择已有执行，或从执行详情进入</option>
      {execution && !executions.some((item) => item.execution_id === execution.execution_id) && <option value={execution.execution_id}>{execution.case_id} v{execution.case_version} · {execution.execution_id}</option>}
      {executions.map((item) => <option key={item.execution_id} value={item.execution_id}>{item.case_id} v{item.case_version} · {item.tester_id} · {item.status === "reviewed" ? "已评分" : "待评分"} · {item.execution_id}</option>)}
    </select>
    {execution && <Link className="text-sm text-emerald-700 underline" href={evaluationHref("executions", execution.execution_id)}>查看执行与证据</Link>}
  </section>;

  return <div className="min-w-0 space-y-5">
    {error && <p role="alert" className="rounded-lg border border-destructive/40 bg-white p-3 text-sm text-destructive">{error}</p>}
    {busy && <p role="status" className="text-sm text-muted-foreground">正在处理…</p>}
    {section === "overview" && <>
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[{ label: "评测任务", value: tasks.length, href: "tasks" }, { label: "已发布用例版本", value: cases.length, href: "cases" },
          { label: user.role === "developer" ? "执行总数" : "近期可见执行", value: stats?.executions ?? executions.length, href: "executions" },
          { label: user.role === "developer" ? "待评分执行" : "近期待评分", value: stats?.pending ?? executions.filter((item) => item.status === "open").length, href: "executions" }].map((item) =>
          <Link href={evaluationHref(item.href)} key={item.label} className="rounded-xl border bg-white p-5 transition-shadow hover:shadow-sm"><p className="text-xs text-slate-500">{item.label}</p><p className="mt-3 text-3xl font-semibold tabular-nums">{item.value}</p></Link>)}
      </section>
      <section className="rounded-xl border bg-white p-5"><h2 className="font-semibold">开始工作</h2><div className="mt-4 grid gap-3 md:grid-cols-3">
        {evaluationModules.filter((item) => item.key !== "overview" && canViewModule(item.key, user.role)).map((item) => <Link key={item.key} href={evaluationHref(item.key)} className="group rounded-lg border p-4 hover:border-emerald-300 hover:bg-emerald-50/40"><span className="flex items-center justify-between text-sm font-medium">{item.title}<ArrowRight size={16} className="text-slate-400 group-hover:text-emerald-700" /></span><p className="mt-2 text-xs leading-5 text-slate-500">{item.description}</p></Link>)}
      </div></section>
        {stats && <div className="space-y-3 rounded-lg border p-4">
          <p className="text-sm">执行 {stats.executions} 次 · 已评分 {stats.reviewed} 次 · 待评分 {stats.pending} 次</p>
          {stats.assessment_counts && <p className="text-sm">独立审核记录：AI 辅助 {stats.assessment_counts.ai_assisted} · 领域专家 {stats.assessment_counts.domain_expert}</p>}
          <p className="text-sm">{Object.entries(stats.overall).map(([k, v]) => `${overallLabels[k]} ${v}`).join(" · ")}</p>
          <div className="overflow-auto"><table className="w-full text-left text-sm"><thead><tr>{["维度", "有效样本", "是", "部分", "否"].map((h) => <th className="p-2" key={h}>{h}</th>)}</tr></thead><tbody>{Object.entries(stats.layers).map(([key, value]) => <tr className="border-t" key={key}><td className="p-2">{labels[key]}</td>{[value.denominator, value.yes, value.partial, value.no].map((n, i) => <td className="p-2" key={i}>{n}</td>)}</tr>)}</tbody></table></div>
          <p className="text-xs text-muted-foreground">受阻单列，不适用不入该层分母，部分通过与通过分开。此表是开发试评评分分布，不能作为专业准确率。</p>
          <details><summary className="cursor-pointer text-sm">按用例版本查看</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(stats.by_case_version, null, 2)}</pre></details>
        </div>}

    </>}

    {section === "tasks" && <>
      <EvaluationTasks token={token} role={user.role} cases={cases} tasks={tasks} selectedTask={selectedTask} currentCase={currentCase}
        view={detail === "new" ? "new" : detail ? "detail" : "list"} revision=""
        onTaskCreated={(task) => router.push(evaluationHref("tasks", task.task_id))}
        onSelectTask={(id) => router.push(evaluationHref("tasks", id))}
        onRefresh={() => refresh()} onOpenExecution={openExecution} />
      {detail && detail !== "new" && user.role === "developer" && <EvaluationDashboard token={token} taskId={detail} onOpenExecution={openExecution} />}
    </>}

    {section === "cases" && <>
      {detail && detail !== "drafts" && !currentCase ? <p role="alert" className="rounded border bg-white p-5">未找到此用例版本。</p> : <>
        {currentCase && <section className="space-y-4 rounded-xl border bg-white p-5"><div><h2 className="font-semibold">{currentCase.case.case_id} v{currentCase.case.version} · {currentCase.case.title}</h2><p className="mt-2 text-sm">{currentCase.case.preconditions}</p></div>
          <ol className="list-decimal space-y-2 pl-5 text-sm">{currentCase.case.steps.map((step, i) => <li key={i}>{step.instruction}{step.input && <p className="mt-1 text-slate-500">{step.input}</p>}</li>)}</ol>
          <h3 className="text-sm font-medium">通过标准</h3><ul className="list-disc space-y-1 pl-5 text-sm">{currentCase.case.expected.map((value, i) => <li key={i}>{value}</li>)}</ul>
          <Link className="inline-flex rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white" href={`${evaluationHref("executions", "new")}?case=${encodeURIComponent(selectedCase)}`}>使用此版本新建执行</Link>
        </section>}
        {(!currentCase || user.role === "developer") && <EvaluationCatalog token={token} role={user.role} mode="cases" showDrafts={detail === "drafts" || !!currentCase} cases={cases} currentCase={currentCase}
          onSelectCase={(id) => router.push(evaluationHref("cases", id))} onPublished={() => refresh()} />}
      </>}
    </>}
    {section === "assets" && user.role !== "tester" && <EvaluationCatalog token={token} role={user.role} mode="assets" cases={cases} onSelectCase={() => {}} onPublished={() => refresh()} />}

    {section === "executions" && !detail && <section className="space-y-4 rounded-xl border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">{user.role === "developer" ? "执行列表" : "可见执行"}</h2><Link href={evaluationHref("executions", "new")} className="inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white"><Plus size={16} />新建执行</Link></div>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr>{["用例版本", "测试者", "状态", "创建时间", "操作"].map((label) => <th key={label} className="whitespace-nowrap p-3 font-medium">{label}</th>)}</tr></thead>
        <tbody>{executions.map((item) => <tr key={item.execution_id} className="border-t"><td className="p-3 font-medium">{item.case_id} v{item.case_version}</td><td className="p-3">{item.tester_id}</td><td className="p-3"><span className={`whitespace-nowrap rounded-full px-2 py-1 text-xs ${item.status === "reviewed" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>{item.status === "reviewed" ? "已评分" : "待评分"}</span></td><td className="whitespace-nowrap p-3 text-xs text-slate-500">{new Date(item.created_at).toLocaleString()}</td><td className="p-3"><Link className="whitespace-nowrap text-emerald-700 underline" href={evaluationHref("executions", item.execution_id)}>打开执行</Link></td></tr>)}</tbody></table></div>
      {!executions.length && <p className="py-8 text-center text-sm text-muted-foreground">暂无执行，选择用例新建一次测试。</p>}
      <div className="flex items-center gap-3"><span className="text-xs text-muted-foreground">第 {executionOffset / 50 + 1} 页</span>{[-50, 50].map((delta) => <button key={delta} className={buttonStyle} disabled={busy || (delta < 0 ? executionOffset === 0 : executions.length < 50)} onClick={() => void perform(async () => { const offset = Math.max(0, executionOffset + delta); setExecutions(await request<ExecutionSummary[]>(token, `/executions?offset=${offset}`)); setExecutionOffset(offset); })}>{delta < 0 ? "上一页" : "下一页"}</button>)}</div>
    </section>}
    {section === "executions" && detail === "new" && <section className="max-w-3xl space-y-4 rounded-xl border bg-white p-6">
      <h2 className="font-semibold">选择用例与任务</h2>
      <label className="block space-y-2 text-sm"><span>用例版本</span><select aria-label="用例版本" className={inputStyle} value={selectedCase} onChange={(e) => { setSelectedCase(e.target.value); setSelectedTask(""); }}><option value="">请选择</option>{cases.map(({ case: item }) => <option key={`${item.case_id}@${item.version}`} value={`${item.case_id}@${item.version}`}>{item.case_id} · v{item.version} · {item.title}</option>)}</select></label>
      <label className="block space-y-2 text-sm"><span>所属任务</span><select aria-label="测评任务" className={inputStyle} value={selectedTask} onChange={(e) => setSelectedTask(e.target.value)}><option value="">独立执行（无任务）</option>{tasks.filter((task) => task.case_versions.some((item) => `${item.case_id}@${item.case_version}` === selectedCase)).map((task) => <option key={task.task_id} value={task.task_id}>{task.title}</option>)}</select></label>
      {currentCase && <p className="text-sm text-muted-foreground">{currentCase.case.preconditions} · {currentCase.case.steps.length} 个步骤</p>}
      <button className="rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white disabled:opacity-40" disabled={busy || !currentCase} onClick={() => void perform(async () => { if (!currentCase) return; const item = await request<EvaluationExecution>(token, "/executions", evaluationJson({ case_id: currentCase.case.case_id, case_version: currentCase.case.version, task_id: selectedTask || null })); openExecution(item.execution_id); })}>新建一次执行</button>
    </section>}
    {(["executions", "reviews"].includes(section)) && execution && <>
      <div className="flex flex-wrap gap-2 text-xs">
        {execution.task_id && <Link className={buttonStyle} href={evaluationHref("tasks", execution.task_id)}>查看所属任务</Link>}
        <Link className={buttonStyle} href={evaluationHref("cases", `${execution.case_id}@${execution.case_version}`)}>查看用例版本</Link>
        {user.role === "developer" && <><Link className={buttonStyle} href={`${evaluationHref("regressions")}?execution=${encodeURIComponent(execution.execution_id)}`}>保存基线 / 回归对比</Link><Link className={buttonStyle} href={`${evaluationHref("issues")}?execution=${encodeURIComponent(execution.execution_id)}`}>登记问题 / 关联复测</Link></>}
        {user.role !== "tester" && section !== "reviews" && <Link className={buttonStyle} href={evaluationHref("reviews", execution.execution_id)}>独立审核</Link>}
      </div>
      <fieldset disabled={busy} className="min-w-0 space-y-5">
          {currentCase && <section className="space-y-3 rounded-lg border p-5">
            <h2 className="font-semibold">{currentCase.case.case_id} v{currentCase.case.version} · {currentCase.case.title}</h2>
            <p className="text-sm">前提：{currentCase.case.preconditions}</p>
            <ol className="list-decimal space-y-2 pl-5 text-sm">{currentCase.case.steps.map((s, i) => <li key={i}>{s.instruction}{s.attachment && <span>（{s.attachment}）</span>}{s.input && <div className="mt-1 flex flex-wrap items-center gap-2"><span>{s.input}</span><button disabled={!editable} className="underline" onClick={() => setQuery(s.input ?? "")}>填入问题</button></div>}</li>)}</ol>
            <details><summary className="cursor-pointer text-sm">查看本版本通过标准与附件指纹（{currentCase.professional_review === "domain_expert_reviewed" ? `已有专家审核：${overallLabels[currentCase.professional_outcome ?? ""] ?? currentCase.professional_outcome}` : "专业标准待审核"}）</summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{currentCase.case.expected.map((e, i) => <li key={i}>{e}</li>)}</ul>
              {currentCase.fixtures.map((f) => <p key={f.filename} className="mt-2 break-all font-mono text-xs">{f.filename} · SHA-256: {f.sha256 ?? "执行时另备"}</p>)}
            </details>
          </section>}
          {execution && <section className="space-y-4 rounded-lg border p-5">
            <div><h2 className="font-semibold">本次执行 · {execution.status === "reviewed" ? "已提交评分" : "待评分"}</h2><p className="break-all text-xs text-muted-foreground">{execution.execution_id}</p></div>
            {execution.needs_reset && <p role="status" className="rounded bg-amber-50 p-3 text-sm text-amber-950">临时上下文不可用。先重置上下文并重新上传附件；已有运行与评分材料仍保留。</p>}
            <div className="max-h-[36rem] space-y-4 overflow-y-auto">{execution.events.map((e) => <article key={e.sequence} className="space-y-2 rounded border p-3 text-sm">
              <p className="text-xs text-muted-foreground">第 {e.sequence} 步 · {e.action} · {new Date(e.created_at).toLocaleTimeString()}</p>
              {e.input && <p className="font-medium">{e.input}</p>}{e.note && <p>{e.note}</p>}
              {e.attachment && <p>附件：{e.attachment.filename} · {e.attachment.status}</p>}
              {e.error && <p role="alert">未完成：{e.error.message ?? e.error.code}（HTTP {e.error.http_status}）</p>}
              {e.response && <AnswerCard response={e.response} scope={`${execution.execution_id}-${e.sequence}`} />}
              {e.trace_missing && <p className="text-destructive">本轮运行记录未保存，本次执行请标记受阻。</p>}
              {e.run_id && <div className="flex flex-wrap gap-2 text-xs"><span>Run：{e.run_id}</span>{user.role === "developer" && <button className="underline" onClick={() => showTrace(e.run_id!)}>查看 Trace</button>}</div>}
            </article>)}</div>
            {editable && <div className="space-y-3 border-t pt-4">
              <p className="text-sm">当前附件：{execution.attachment ? `${execution.attachment.filename}（${execution.attachment.status}）` : "无"}</p>
              <p className="text-xs text-muted-foreground">同一执行内上传一次即可，后续提问自动复用，刷新页面也无需重传。上传新文件失败会保留原附件。重置上下文、移除附件、闲置过期或服务重启后需重新上传。</p>
              <label className="block text-sm">上传本用例附件<input className="mt-1 block max-w-full" type="file" accept=".xls,.xlsx" disabled={execution.needs_reset} onChange={(e) => {
                const file = e.target.files?.[0]; e.target.value = ""; if (!file) return;
                if (file.size > 10 * 1024 * 1024) { setError("文件超过 10 MiB；如在测试超限场景，请使用手动记录并注明结果。"); return; }
                void perform(() => mutate(`/files?filename=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file }));
              }} /></label>
              <div className="flex flex-wrap gap-2"><button className={buttonStyle} onClick={() => void perform(() => mutate("/actions", evaluationJson({ action: "clear" })))}>重置上下文</button><button className={buttonStyle} disabled={execution.needs_reset} onClick={() => void perform(() => mutate("/actions", evaluationJson({ action: "remove_attachment" })))}>移除附件</button></div>
              <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void perform(async () => { await mutate("/query", evaluationJson({ query: query.trim() })); setQuery(""); }); }}>
                <textarea aria-label="执行问题" className={inputStyle} rows={3} maxLength={1000} required value={query} onChange={(e) => setQuery(e.target.value)} placeholder="按照用例步骤提问，所有轮次将保存在本次执行中" />
                <button className={buttonStyle} disabled={execution.needs_reset || !query.trim()}>发送本轮</button>
              </form>
              <div className="flex flex-wrap gap-2"><input aria-label="手动操作记录" className={`${inputStyle} flex-1`} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="记录手动步骤、等待、页面刷新或受阻情况" /><button className={buttonStyle} disabled={!note.trim()} onClick={() => void perform(async () => { await mutate("/actions", evaluationJson({ action: "manual", note })); setNote(""); })}>保存操作记录</button></div>
            </div>}
          </section>}
          {editable && <form noValidate className="space-y-4 rounded-lg border p-5" onSubmit={(e) => void submitReview(e)}>
            <h2 className="font-semibold">提交本次评分</h2><p className="text-xs text-muted-foreground">请明确选择。无法执行时选“受阻”，四层选“不适用/无法判断”并说明原因。提交后记录冻结，复测另建执行。</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-sm"><span>总体结论</span><select required className={inputStyle} value={scores.overall} onChange={(e) => setScores({ ...scores, overall: e.target.value })}><option value="">请选择</option>{Object.entries(overallLabels).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
              {Object.entries(labels).map(([key, label]) => <label className="space-y-1 text-sm" key={key}><span>{label}</span><select required className={inputStyle} value={scores[key as keyof typeof scores]} onChange={(e) => setScores({ ...scores, [key]: e.target.value })}><option value="">请选择</option><option value="yes">是</option>{["evidence_correct", "answer_correct"].includes(key) && <option value="partial">部分</option>}<option value="no">否</option><option value="n.a.">不适用 / 无法判断</option></select></label>)}
              <label className="space-y-1 text-sm"><span>可用性（可选）</span><select className={inputStyle} value={scores.usability} onChange={(e) => setScores({ ...scores, usability: e.target.value })}><option value="">未评</option>{[1, 2, 3, 4, 5].map((v) => <option key={v} value={v}>{v} / 5</option>)}</select></label>
            </div>
            <input aria-label="问题标签" className={inputStyle} maxLength={800} placeholder="问题标签，以逗号分隔，例如：引用不支持、作物不适用" value={scores.tags} onChange={(e) => setScores({ ...scores, tags: e.target.value })} />
            <textarea aria-label="评分说明" className={inputStyle} rows={3} maxLength={5000} placeholder="记录问题原句、依据和修改建议；部分通过、不通过或受阻必须填写" value={scores.notes} onChange={(e) => setScores({ ...scores, notes: e.target.value })} />
            <button className={buttonStyle}>提交并冻结评分</button>
            {scoreError && <p role="alert" className="rounded border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">{scoreError}</p>}
          </form>}
          {execution?.review && <section className="space-y-3 rounded-lg border p-5"><h2 className="font-semibold">已保存的开发试评</h2>
            <p className="text-sm font-medium">总体结论：{overallLabels[String(execution.review.overall)] ?? String(execution.review.overall)}</p>
            <dl className="grid gap-3 sm:grid-cols-2">{Object.entries(labels).map(([key, label]) => <div key={key} className="rounded-lg bg-slate-50 p-3 text-sm"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1">{({ yes: "是", no: "否", partial: "部分", "n.a.": "不适用 / 无法判断" } as Record<string, string>)[String(execution.review?.[key])] ?? "未记录"}</dd></div>)}</dl>
            {execution.review.notes ? <p className="whitespace-pre-wrap text-sm">{String(execution.review.notes)}</p> : null}
            <p className="text-xs text-muted-foreground">此评分已冻结；专业审核结论单独记录。</p>
            <details><summary className="cursor-pointer text-xs text-muted-foreground">查看评分原始记录</summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(execution.review, null, 2)}</pre></details>
          </section>}
      </fieldset>
    </>}
    {section === "regressions" && <>{contextSelector}<EvaluationRegressions token={token} execution={execution} onOpenExecution={openExecution} /></>}
    {section === "issues" && <>{contextSelector}<EvaluationWorkflow mode="issues" selectedIssue={detail} onSelectIssue={(id) => router.push(evaluationHref("issues", id))} token={token} role={user.role} currentCase={currentCase} execution={execution} onOpenExecution={openExecution} /></>}
    {section === "reviews" && !detail && <EvaluationReviewQueue token={token} role={user.role} revision="" onOpenExecution={(id) => router.push(evaluationHref("reviews", id))} />}
    {section === "reviews" && execution && <EvaluationWorkflow mode="assessment" token={token} role={user.role} currentCase={currentCase} execution={execution} onOpenExecution={openExecution} />}
    {section === "runs" && <EvaluationRuns token={token} detail={detail} />}
  </div>;
}
