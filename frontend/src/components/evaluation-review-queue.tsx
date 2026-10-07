"use client";

import { useCallback, useEffect, useState } from "react";
import { evaluationJson, evaluationRequest as request } from "@/lib/evaluation-api";
import type { Evaluator } from "@/lib/evaluation-api";

type Assessment = { assessment_id: string; recorded_by: string; overall: string; notes: string; source_path: string };
type QueueItem = {
  execution_id: string; case_id: string; case_version: number; tester_id: string; created_at: string;
  status: string; development_review: { overall: string } | null;
  assignments: { reviewer_id: string; assigned_by: string; note: string }[];
  pending_reviewers: string[]; expert_assessments: Assessment[];
  resolution: { conclusion: string; rationale: string; resolved_by: string } | null;
};
const field = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
const button = "rounded-md border border-input px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const labels: Record<string, string> = {
  pending_development: "待开发评分", unassigned: "待分派专家", pending_expert: "待专家审核",
  expert_consensus: "专家结论一致", expert_disagreement: "专家结论有分歧",
  resolved_disagreement: "分歧已记录处理意见",
};

export function EvaluationReviewQueue({ token, role, onOpenExecution, revision }: {
  token: string; role: Evaluator["role"]; onOpenExecution: (id: string) => void; revision: string;
}) {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [reviewers, setReviewers] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [selectedReviewer, setSelectedReviewer] = useState<Record<string, string>>({});
  const [rationale, setRationale] = useState<Record<string, string>>({});
  const [conclusion, setConclusion] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const reload = useCallback(async () => {
    const [queue, identities] = await Promise.all([
      request<QueueItem[]>(token, "/review-queue"),
      role === "developer" ? request<{ tester_id: string }[]>(token, "/reviewers") : Promise.resolve([]),
    ]);
    setItems(queue); setReviewers(identities.map((item) => item.tester_id));
  }, [token, role]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void reload().catch((err) => setError(String(err)));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [reload, revision]);
  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); await reload(); } catch (err) { setError(err instanceof Error ? err.message : "审核队列操作失败。"); }
    finally { setBusy(false); }
  }
  const visible = items.filter((item) => (!status || item.status === status)
    && `${item.case_id} ${item.execution_id} ${item.tester_id}`.toLowerCase().includes(search.toLowerCase()));
  return <section aria-label="独立审核队列" className="space-y-4 rounded-lg border p-5">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="text-lg font-semibold">独立审核队列</h2>
      <p className="text-xs text-muted-foreground">开发评分、专家结论和分歧处理分别保存。这里的队列状态不表示专业通过率。</p></div>
      <button className={button} disabled={busy} onClick={() => void perform(async () => { setNotice("审核队列已刷新。"); })}>刷新审核队列</button></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <div className="grid gap-2 sm:grid-cols-2">
      <select aria-label="筛选审核状态" className={field} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">全部状态</option>
        {Object.entries(labels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select>
      <input aria-label="检索审核执行" className={field} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="用例、执行 ID 或测试者" />
    </div>
    <div className="max-h-[36rem] space-y-3 overflow-auto">{visible.map((item) => <article key={item.execution_id} className="space-y-2 rounded border p-3 text-sm">
      <h3 className="font-medium">{item.case_id}@{item.case_version} · {labels[item.status] ?? item.status}</h3>
      <p className="break-all text-xs text-muted-foreground">执行 {item.execution_id} · {item.tester_id} · {new Date(item.created_at).toLocaleString()}</p>
      <p className="text-xs">开发评分：{item.development_review?.overall ?? "未提交"}；已分派：{item.assignments.map((assignment) => assignment.reviewer_id).join("、") || "无"}；待审核：{item.pending_reviewers.join("、") || "无"}</p>
      <button className="text-xs underline" disabled={busy} onClick={() => onOpenExecution(item.execution_id)}>打开执行与审核表单</button>
      {role === "developer" && item.development_review && <div className="flex flex-wrap gap-2">
        <select aria-label={`${item.execution_id} 分派审核人`} className={`${field} sm:max-w-56`} value={selectedReviewer[item.execution_id] ?? ""}
          onChange={(e) => setSelectedReviewer((old) => ({ ...old, [item.execution_id]: e.target.value }))}>
          <option value="">选择专家身份</option>{reviewers.filter((name) => !item.assignments.some((assignment) => assignment.reviewer_id === name))
            .map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        <button className={button} disabled={busy || !selectedReviewer[item.execution_id]} onClick={() => void perform(async () => {
          await request(token, `/review-queue/${item.execution_id}/assignments`, evaluationJson({ reviewer_id: selectedReviewer[item.execution_id] }));
          setSelectedReviewer((old) => ({ ...old, [item.execution_id]: "" })); setNotice("审核人已分派。");
        })}>分派审核</button>
      </div>}
      {item.expert_assessments.length > 0 && <details className="rounded border p-2 text-xs"><summary>专家审核 {item.expert_assessments.length} 份</summary>
        {item.expert_assessments.map((assessment) => <p key={assessment.assessment_id} className="mt-2 break-all border-t pt-2">
          {assessment.recorded_by} · {assessment.overall} · {assessment.assessment_id}<br />{assessment.source_path} · {assessment.notes}</p>)}
      </details>}
      {item.status === "expert_disagreement" && role === "reviewer" && <form className="space-y-2 rounded border p-2" onSubmit={(event) => {
        event.preventDefault(); void perform(async () => {
          await request(token, `/review-queue/${item.execution_id}/resolutions`, evaluationJson({
            assessment_ids: item.expert_assessments.map((assessment) => assessment.assessment_id),
            conclusion: conclusion[item.execution_id] ?? "unresolved", rationale: rationale[item.execution_id]?.trim(),
          }));
          setNotice("专家分歧处理意见已单独保存；原审核结论仍保留。");
        });
      }}><p>专家结论有分歧，请核对全部审核材料后记录处理依据。</p>
        <select aria-label={`${item.execution_id} 分歧处理结论`} className={field} value={conclusion[item.execution_id] ?? "unresolved"}
          onChange={(e) => setConclusion((old) => ({ ...old, [item.execution_id]: e.target.value }))}>
          <option value="unresolved">仍待核实</option><option value="pass">通过</option><option value="partial">部分通过</option><option value="fail">不通过</option><option value="blocked">受阻</option></select>
        <textarea aria-label={`${item.execution_id} 分歧处理依据`} required maxLength={5000} className={field} value={rationale[item.execution_id] ?? ""}
          onChange={(e) => setRationale((old) => ({ ...old, [item.execution_id]: e.target.value }))} />
        <button className={button} disabled={busy}>保存分歧处理</button>
      </form>}
      {item.resolution && <p className="rounded bg-muted p-2 text-xs">分歧处理：{item.resolution.conclusion} · {item.resolution.resolved_by} · {item.resolution.rationale}</p>}
    </article>)}{!visible.length && <p className="text-sm text-muted-foreground">没有匹配的执行。</p>}</div>
  </section>;
}
