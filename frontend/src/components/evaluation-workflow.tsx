"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { evaluationJson, evaluationRequest as request } from "@/lib/evaluation-api";
import type { EvaluationCase, EvaluationExecution, Evaluator } from "@/lib/evaluation-api";

type Issue = {
  issue_id: string; title: string; case_id: string; case_version: number; run_id: string;
  original_question: string; review_id: string; execution_id: string; assignee: string;
  status: "open" | "in_progress" | "ready_for_retest" | "closed"; revision: number;
  history: { at: string; by: string; action: string; from_status: string | null;
    to_status: string; note?: string; assignee?: string; overall?: string }[];
  retests?: { execution_id: string; review_id: string; overall: string; fix_version: string; version_verified?: boolean }[];
};
type Assessment = {
  assessment_id: string; case_id: string; case_version: number; kind: "ai_assisted" | "domain_expert";
  overall: string; source_path: string; source_sha256: string; recorded_by: string;
  reviewer_role: string; recorded_at: string; notes: string;
};
const field = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
const button = "rounded-md border border-input px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const issueStatusLabels: Record<Issue["status"], string> = {
  open: "待处理", in_progress: "处理中", ready_for_retest: "待复测", closed: "已关闭",
};

export function EvaluationWorkflow({ token, role, currentCase, execution, onOpenExecution, mode = "issues", selectedIssue = "", onSelectIssue }: {
  token: string; role: Evaluator["role"]; currentCase?: EvaluationCase;
  execution: EvaluationExecution | null;
  onOpenExecution: (executionId: string) => void;
  mode?: "issues" | "assessment"; selectedIssue?: string; onSelectIssue?: (id: string) => void;
}) {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [issueTitle, setIssueTitle] = useState("");
  const [issueEvent, setIssueEvent] = useState("");
  const [assignee, setAssignee] = useState("");
  const [evidenceNote, setEvidenceNote] = useState("");
  const [issueStatusFilter, setIssueStatusFilter] = useState("");
  const [issueAssigneeFilter, setIssueAssigneeFilter] = useState("");
  const [retestIssue, setRetestIssue] = useState("");
  const [fixVersionEdit, setFixVersionEdit] = useState<{ executionId: string; value: string } | null>(null);
  const [assessmentOverall, setAssessmentOverall] = useState("partial");
  const [sourcePath, setSourcePath] = useState("");
  const [sourceSha, setSourceSha] = useState("");
  const [assessmentNotes, setAssessmentNotes] = useState("");

  const reload = useCallback(async () => {
    const [nextIssues, nextAssessments] = await Promise.all([
      mode === "issues" && role === "developer" ? request<Issue[]>(token, "/issues") : Promise.resolve([]),
      mode === "assessment" ? request<Assessment[]>(token, "/assessments") : Promise.resolve([]),
    ]);
    setIssues(nextIssues); setAssessments(nextAssessments);
  }, [token, role, mode]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void reload().catch(() => setError("问题或审核记录读取失败。"));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [reload]);
  const reviewedVersions = execution?.review?.runtime_config_versions;
  const observedVersion = Array.isArray(reviewedVersions) && reviewedVersions.length === 1 && typeof reviewedVersions[0] === "string"
    ? reviewedVersions[0] : "";
  const fixVersion = fixVersionEdit && fixVersionEdit.executionId === execution?.execution_id
    ? fixVersionEdit.value : observedVersion.split(":", 1)[0];

  async function perform(operation: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await operation(); await reload(); }
    catch (err) { setError(err instanceof Error ? err.message : "保存失败。"); }
    finally { setBusy(false); }
  }

  const availableEvents = execution?.events.filter((event) => event.action === "query" && event.run_id) ?? [];
  const relevantIssues = issues.filter((issue) => issue.case_id === execution?.case_id && issue.case_version === execution?.case_version);
  const visibleIssues = issues.filter((issue) => (!issueStatusFilter || issue.status === issueStatusFilter)
    && (!issueAssigneeFilter || issue.assignee.toLowerCase().includes(issueAssigneeFilter.toLowerCase())));
  const relevantAssessments = assessments.filter((item) => item.case_id === currentCase?.case.case_id && item.case_version === currentCase?.case.version);

  return <section className="space-y-5 rounded-lg border p-5">
    <div className="flex items-center justify-between gap-2"><div><h2 className="text-lg font-semibold">{mode === "issues" ? "问题与复测" : "独立审核"}</h2>
      <p className="text-xs text-muted-foreground">原执行和评分冻结；修复后另建执行，再关联复测。AI 辅助复核与专家签核分别保存。</p></div>
      <button className={button} disabled={busy} onClick={() => void perform(async () => { setNotice("记录已刷新。"); })}>刷新</button></div>
    {error && <p role="alert" className="rounded border border-destructive/40 p-2 text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {mode === "issues" && role === "developer" && <div className="space-y-5">
      {execution && <form className="space-y-3 rounded border p-4" onSubmit={(event: FormEvent) => { event.preventDefault(); void perform(async () => {
        if (!execution) return;
        const created = await request<Issue>(token, "/issues", evaluationJson({ execution_id: execution.execution_id,
          event_sequence: Number(issueEvent), title: issueTitle.trim(), assignee: assignee.trim(), evidence_note: evidenceNote.trim() }));
        setIssueTitle(""); setEvidenceNote(""); setNotice(`问题 ${created.issue_id} 已关联原 Run 和评分。`);
      }); }}>
        <h3 className="font-medium">从失败评分登记问题</h3>
        <p className="text-xs text-muted-foreground">{execution?.review ? `执行 ${execution.execution_id}` : "先打开已评为部分通过或不通过的执行"}</p>
        <select aria-label="问题轮次" className={field} required value={issueEvent} onChange={(e) => setIssueEvent(e.target.value)}><option value="">选择带 Run 的轮次</option>
          {availableEvents.map((item) => <option key={item.sequence} value={item.sequence}>第 {item.sequence} 步 · {item.input}</option>)}</select>
        <input aria-label="问题标题" className={field} required maxLength={200} placeholder="问题标题" value={issueTitle} onChange={(e) => setIssueTitle(e.target.value)} />
        <input aria-label="负责人" className={field} required maxLength={80} placeholder="负责人" value={assignee} onChange={(e) => setAssignee(e.target.value)} />
        <textarea aria-label="问题证据" className={field} required maxLength={3000} placeholder="引用哪条证据、Trace 字段或实际回答？" value={evidenceNote} onChange={(e) => setEvidenceNote(e.target.value)} />
        <button className={button} disabled={busy || !execution?.review || !issueEvent}>登记问题</button>
      </form>}
    </div>}
    {mode === "issues" && role === "developer" && <div className="space-y-5">
      {execution && <form className="space-y-3 rounded border p-4" onSubmit={(event: FormEvent) => { event.preventDefault(); void perform(async () => {
        if (!execution) return;
        await request(token, `/issues/${retestIssue}/retests`, evaluationJson({ execution_id: execution.execution_id,
          fix_version: fixVersion.trim() }));
        setNotice("复测已关联新执行与独立评分。");
      }); }}>
        <h3 className="font-medium">关联复测结果</h3>
        <p className="text-xs text-muted-foreground">打开同版本的新执行并提交评分后，再选择原问题。</p>
        <p className="break-all text-xs text-muted-foreground">{observedVersion ? `复测 Run 的实际配置：${observedVersion}` : "尚无单一可核验的 Run 配置；缺少 Run 或混用配置的执行只能记录受阻。"}</p>
        <select aria-label="待复测问题" className={field} required value={retestIssue} onChange={(e) => setRetestIssue(e.target.value)}><option value="">选择原问题</option>
          {relevantIssues.map((item) => <option key={item.issue_id} value={item.issue_id}>{item.title} · {item.issue_id.slice(0, 8)}</option>)}</select>
        <input aria-label="修复版本" className={field} required maxLength={160} placeholder="修复版本" value={fixVersion} onChange={(e) => setFixVersionEdit({ executionId: execution.execution_id, value: e.target.value })} />
        <button className={button} disabled={busy || !execution?.review || !retestIssue}>保存复测关联</button>
      </form>}
      <div className="space-y-2 rounded border p-4"><h3 className="font-medium">问题队列与处理历史</h3>
        <select aria-label="筛选问题状态" className={field} value={issueStatusFilter} onChange={(e) => setIssueStatusFilter(e.target.value)}>
          <option value="">全部状态</option>{Object.entries(issueStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <input aria-label="筛选负责人" className={field} value={issueAssigneeFilter} onChange={(e) => setIssueAssigneeFilter(e.target.value)} placeholder="筛选负责人" />
        {selectedIssue && !issues.some((item) => item.issue_id === selectedIssue) && <p role="alert">未找到此问题，请返回问题列表。</p>}
        {visibleIssues.length === 0 && <p className="text-sm text-muted-foreground">没有匹配的问题。</p>}
        {visibleIssues.filter((item) => !selectedIssue || item.issue_id === selectedIssue).map((item) => <article aria-label={`问题：${item.title}`} key={item.issue_id} className="rounded border p-2 text-xs">
          <p className="font-medium">{item.title} · {issueStatusLabels[item.status]} · {item.assignee}</p>
          {!selectedIssue && <button className="my-2 text-emerald-700 underline" onClick={() => onSelectIssue?.(item.issue_id)}>查看问题详情</button>}
          <p>{item.case_id}@{item.case_version} · {item.original_question}</p>
          <p className="break-all text-muted-foreground">原 Run {item.run_id} · 原评分 {item.review_id}</p>
          <button className="my-1 underline" onClick={() => onOpenExecution(item.execution_id)}>打开原执行与证据</button>
          <p>复测 {item.retests?.length ?? 0} 次</p>
          {item.retests?.slice(-3).reverse().map((retest) => <div key={retest.execution_id} className="mt-2 border-t pt-2">
            <p>{retest.overall} · {retest.fix_version} · {retest.version_verified ? "版本已核验" : "版本未核验"}</p>
            <button className="underline" onClick={() => onOpenExecution(retest.execution_id)}>打开复测执行与评分</button>
          </div>)}
          {selectedIssue && <form key={`${item.issue_id}:${item.revision}`} className="mt-2 space-y-2 border-t pt-2" onSubmit={(event) => {
            event.preventDefault();
            const values = new FormData(event.currentTarget);
            void perform(async () => {
              await request(token, `/issues/${item.issue_id}`, { method: "PATCH", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ expected_revision: item.revision, status: values.get("status"),
                  assignee: String(values.get("assignee") ?? "").trim(), note: String(values.get("note") ?? "").trim() }) });
              setNotice("问题状态和处理记录已保存。");
            });
          }}>
            <select aria-label={`${item.title} 状态`} name="status" className={field} defaultValue={item.status}>
              {Object.entries(issueStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <input aria-label={`${item.title} 负责人`} name="assignee" className={field} required maxLength={80} defaultValue={item.assignee} />
            <textarea aria-label={`${item.title} 处理备注`} name="note" className={field} required maxLength={3000} placeholder="这次处理的依据和下一步" />
            <button className={button} disabled={busy}>保存处理记录</button>
          </form>}
          <details><summary className="cursor-pointer">处理历史 {item.history.length} 条</summary>
            <ol className="mt-1 space-y-1">{item.history.map((event, index) => <li key={index}>
              {new Date(event.at).toLocaleString()} · {event.by} · {issueStatusLabels[event.to_status as Issue["status"]] ?? event.to_status}
              {event.assignee ? ` · ${event.assignee}` : ""}{event.overall ? ` · 复测 ${event.overall}` : ""}
              {event.note ? ` · ${event.note}` : ""}</li>)}</ol>
          </details>
        </article>)}
      </div>
    </div>}
    {mode === "assessment" && (role === "developer" || role === "reviewer") && <div className="grid gap-5 lg:grid-cols-2">
      <form className="space-y-3 rounded border p-4" onSubmit={(event: FormEvent) => { event.preventDefault(); void perform(async () => {
        if (!currentCase) return;
        const kind = role === "reviewer" ? "domain_expert" : "ai_assisted";
        await request(token, "/assessments", evaluationJson({ case_id: currentCase.case.case_id,
          case_version: currentCase.case.version, kind, overall: assessmentOverall,
          source_path: sourcePath.trim(), source_sha256: sourceSha.trim().toLowerCase(),
          notes: assessmentNotes.trim(), execution_id: execution?.case_id === currentCase.case.case_id &&
            execution.case_version === currentCase.case.version ? execution.execution_id : null }));
        setAssessmentNotes(""); setNotice(kind === "domain_expert" ? "专家审核已独立归档。" : "AI 辅助复核已归档，仍待专家审核。");
      }); }}>
        <h3 className="font-medium">{role === "reviewer" ? "领域专家审核" : "归档 AI 辅助复核"}</h3>
        <p className="text-xs text-muted-foreground">记录审核人、时间、材料路径和 SHA-256；不会覆盖开发试评或历史审核。</p>
        <select aria-label="独立审核结论" className={field} value={assessmentOverall} onChange={(e) => setAssessmentOverall(e.target.value)}>
          <option value="pass">通过</option><option value="partial">部分通过</option><option value="fail">不通过</option><option value="blocked">受阻</option></select>
        <input aria-label="审核材料路径" className={field} required maxLength={500} placeholder="审核材料路径" value={sourcePath} onChange={(e) => setSourcePath(e.target.value)} />
        <input aria-label="审核材料 SHA-256" className={field} required pattern="[0-9a-fA-F]{64}" placeholder="审核材料 SHA-256" value={sourceSha} onChange={(e) => setSourceSha(e.target.value)} />
        <textarea aria-label="审核依据" className={field} required maxLength={5000} placeholder="具体审核依据与结论" value={assessmentNotes} onChange={(e) => setAssessmentNotes(e.target.value)} />
        <button className={button} disabled={busy || !currentCase}>保存独立审核</button>
      </form>
      <div className="space-y-2 rounded border p-4"><h3 className="font-medium">当前用例版本的审核历史</h3>
        {relevantAssessments.length === 0 && <p className="text-sm text-muted-foreground">尚无独立审核。</p>}
        {relevantAssessments.map((item) => <div key={item.assessment_id} className="rounded border p-2 text-xs">
          <p className="font-medium">{item.kind === "domain_expert" ? "领域专家" : "AI 辅助复核"} · {item.overall}</p>
          <p>{item.recorded_by}（{item.reviewer_role}） · {new Date(item.recorded_at).toLocaleString()}</p>
          <p className="break-all">{item.source_path} · SHA-256 {item.source_sha256}</p><p>{item.notes}</p></div>)}
      </div>
    </div>}
  </section>;
}
