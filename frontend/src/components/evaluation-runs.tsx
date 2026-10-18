"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { evaluationJson, evaluationRequest } from "@/lib/evaluation-api";
import type { SessionDetail, SessionSummary, SessionTrace, SessionIssue } from "@/lib/evaluation-api";
import { MarkdownAnswer } from "./chat/markdown-answer";
import { evaluationHref } from "@/lib/evaluation-navigation";

type Filters = { information: string; from: string; to: string; status: string;
  durationMode: string; duration: string; durationMax: string; operator: string };
const emptyFilters = (): Filters => ({ information: "", from: "", to: "", status: "",
  durationMode: "", duration: "", durationMax: "", operator: "" });
const field = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
const button = "rounded-md border border-input px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const pageSizes = [10, 20, 50, 100];

function dateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

function queryString(filters: Filters, page: number, size: number) {
  const params = new URLSearchParams({ limit: String(size), offset: String((page - 1) * size) });
  if (filters.information.trim()) params.set("information", filters.information.trim());
  if (filters.from && !Number.isNaN(new Date(filters.from).getTime())) params.set("created_from", new Date(filters.from).toISOString());
  if (filters.to && !Number.isNaN(new Date(filters.to).getTime())) params.set("created_to", new Date(new Date(filters.to).getTime() + 60_000 - 1).toISOString());
  if (filters.status) params.set("status", filters.status);
  if (filters.operator.trim()) params.set("operator_id", filters.operator.trim());
  if (filters.durationMode) {
    params.set("duration_mode", filters.durationMode);
    params.set("duration_ms", filters.duration);
    if (filters.durationMode === "between") params.set("duration_max_ms", filters.durationMax);
  }
  return params.toString();
}

function Flow({ turn }: { turn: SessionTrace }) {
  const steps = ["用户问题", turn.decision?.route ? `路由：${turn.decision.route}` : "路由未确定",
    ...(turn.tool_calls ?? []).map((call) => `${call.skill} · ${call.status} · ${call.latency_ms} ms`),
    turn.status === "ok" ? "生成回答" : `处理异常：${turn.error_code ?? turn.status}`];
  return <div aria-label="路由与调用脉络" className="flex flex-wrap items-center gap-2 text-xs">
    {steps.map((step, index) => <span key={`${index}-${step}`} className="flex items-center gap-2">
      {index > 0 && <span aria-hidden="true" className="text-slate-400">→</span>}
      <span className="rounded-md border bg-slate-50 px-2 py-1">{step}</span>
    </span>)}
  </div>;
}

function StateContext({ turn }: { turn: SessionTrace }) {
  const before = turn.state_before ?? {};
  const after = turn.state_after ?? {};
  const keys: [string, string][] = [["crop", "作物"], ["current_metric", "指标"],
    ["current_operation", "运算"], ["last_tool", "上一工具"], ["attachment_ref", "附件引用"]];
  const values = keys.filter(([key]) => before[key] != null || after[key] != null);
  return <div className="rounded-lg border bg-emerald-50/40 p-3 text-xs">
    <p className="font-medium">上下文承接 · 本轮请求携带 {turn.history_count ?? "未知"} 条历史消息</p>
    <div className="mt-2 flex flex-wrap gap-2">{values.length ? values.map(([key, label]) =>
      <span key={key} className="rounded border bg-white px-2 py-1">{label}：{JSON.stringify(before[key] ?? null)} → {JSON.stringify(after[key] ?? null)}</span>)
      : <span className="text-slate-500">本轮没有可展示的结构化任务状态</span>}</div>
  </div>;
}

function TraceDetails({ turn }: { turn: SessionTrace }) {
  const groups: [string, unknown][] = [
    ["路由决策", turn.decision], ["工具调用", turn.tool_calls], ["运行前状态", turn.state_before],
    ["运行后状态", turn.state_after], ["证据", turn.evidence], ["答案与证据关联", turn.sections],
    ["未完成部分", turn.warnings], ["配置与文件版本", turn.config_manifest],
    ["问题理解与条件来源", turn.understanding], ["标签映射与用途", turn.tag_mapping],
    ["星标匹配与覆盖", turn.starred_match], ["检索与条件核对", turn.retrieval],
    ["当时的表达配置", turn.skill_config], ["实际执行事件", turn.execution_steps],
  ];
  return <details className="rounded-lg border bg-white p-3">
    <summary className="cursor-pointer text-sm font-medium">展开本轮 MQ 明细 · Run {turn.run_id}</summary>
    <div className="mt-3 space-y-2"><StateContext turn={turn} /><Flow turn={turn} />
      {groups.map(([name, value]) => <details key={name} open={name === "工具调用"} className="rounded border p-2">
        <summary className="cursor-pointer text-xs">{name}</summary>
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words bg-slate-50 p-2 text-xs">{JSON.stringify(value ?? null, null, 2)}</pre>
        {name === "工具调用" && !!turn.tool_calls?.length && <div className="mt-2 space-y-2 text-xs">
          {[...new Set(turn.tool_calls.map((call) => call.skill))].map((skill) => <Link key={skill} href={evaluationHref("skills", skill)} className="block text-emerald-800 underline">查看当前能力说明：{skill}</Link>)}
          <p className="text-slate-500">链接展示当前能力说明；本轮实际配置以历史运行记录为准。</p>
        </div>}
      </details>)}
      <details className="rounded border p-2"><summary className="cursor-pointer text-xs">完整运行记录</summary>
        <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words bg-slate-50 p-2 text-xs">{JSON.stringify(turn, null, 2)}</pre>
      </details>
    </div>
  </details>;
}

const reviewLabels = { pending: "待审核", passed: "已通过", needs_changes: "需修改" };
const historyLabels: Record<string, string> = { pass: "通过", issue: "标记问题", comment: "补充意见", resolve: "确认解决", reopen: "重新打开问题", retest: "重新验证" };
type Queue = { total: number; items: SessionSummary[] };

function EvidenceLinks({ turn }: { turn: SessionTrace }) {
  const evidence = (turn.evidence ?? []) as { source_type?: string; source_id?: string; provenance?: Record<string, string>; location?: Record<string, string> }[];
  const links = evidence.flatMap((item) => {
    if (item.source_type === "case" && item.source_id) return [{ href: evaluationHref("case-library", item.source_id), label: item.provenance?.title || "查看案例资料" }];
    if (item.source_type === "starred") return [{ href: evaluationHref("starred-questions"), label: "查看星标问题" }];
    const id = item.provenance?.paper_id || item.provenance?.document_id || /^managed:\/\/([^/]+)\//.exec(item.provenance?.source ?? "")?.[1];
    if (item.source_type === "literature" && id) return [{ href: evaluationHref("literature", id), label: item.provenance?.title || "查看引用文献" }];
    return [];
  });
  return !!links.length && <div className="flex flex-wrap gap-3 text-xs">{links.filter((link, index) => links.findIndex((other) => other.href === link.href) === index).map((link) =>
    <Link key={link.href} target="_blank" rel="noopener noreferrer" className="text-emerald-800 underline" href={link.href}>{link.label} ↗</Link>)}</div>;
}

export function EvaluationRuns({ token, detail, query = "", actor = "" }: { token: string; detail: string; query?: string; actor?: string }) {
  const router = useRouter();
  const params = new URLSearchParams(query);
  const initialFilters = (): Filters => ({ ...emptyFilters(), information: params.get("information") ?? "",
    from: params.get("from") ?? "", to: params.get("to") ?? "", status: params.get("status") ?? "",
    operator: params.get("operator_id") ?? "", durationMode: params.get("duration_mode") ?? "",
    duration: params.get("duration_ms") ?? "", durationMax: params.get("duration_max_ms") ?? "" });
  const [draft, setDraft] = useState(initialFilters);
  const reviewFilter = params.get("review_status") ?? "pending";
  const [draftReview, setDraftReview] = useState(reviewFilter);
  const page = Math.max(1, Number(params.get("page")) || 1);
  const size = pageSizes.includes(Number(params.get("size"))) ? Number(params.get("size")) : 20;
  const applied = initialFilters();
  const apiParams = new URLSearchParams(queryString(applied, page, size));
  if (reviewFilter) apiParams.set("review_status", reviewFilter);
  const search = apiParams.toString();
  const suffix = query ? `?${query}` : "";
  const scrollKey = `conversation-review-list:${actor}:${query}`;
  const listHref = `${evaluationHref("runs")}${suffix}`;
  const [list, setList] = useState<Queue>({ total: 0, items: [] });
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState("");
  const [issueNote, setIssueNote] = useState("");
  const [comment, setComment] = useState("");
  const [resolutionNotes, setResolutionNotes] = useState<Record<string, string>>({});
  const mutation = useRef<{ fingerprint: string; action_id: string } | null>(null);
  const pendingRetest = useRef<{ fingerprint: string; submission_id: string } | null>(null);
  const draftKey = `conversation-review:${actor}:${detail}`;
  const [draftReady, setDraftReady] = useState(false);
  useEffect(() => {
    if (!detail) return;
    const timer = setTimeout(() => {
      try {
        const saved = JSON.parse(sessionStorage.getItem(draftKey) ?? "null");
        if (saved) { setEditing(saved.editing || ""); setIssueNote(saved.issueNote || ""); setComment(saved.comment || ""); setResolutionNotes(saved.resolutionNotes || {}); }
      } catch { /* A malformed browser draft can be safely replaced. */ }
      setDraftReady(true);
    }, 0);
    return () => clearTimeout(timer);
  }, [detail, draftKey]);
  useEffect(() => {
    if (!detail || !draftReady) return;
    try { sessionStorage.setItem(draftKey, JSON.stringify({ editing, issueNote, comment, resolutionNotes })); } catch { /* Reviewing still works without browser storage. */ }
  }, [detail, draftKey, draftReady, editing, issueNote, comment, resolutionNotes]);

  useEffect(() => {
    let active = true;
    const path = detail ? `/sessions/${encodeURIComponent(detail)}` : `/sessions?${search}`;
    evaluationRequest<SessionDetail | Queue>(token, path)
      .then((result) => {
        if (!active) return;
        if (detail) setSession(result as SessionDetail);
        else {
          const queue = result as Queue;
          if (queue.total > 0 && !queue.items.length && page > 1) {
            const previousPage = new URLSearchParams(query); previousPage.set("page", String(Math.ceil(queue.total / size)));
            router.replace(`${evaluationHref("runs")}?${previousPage}`);
          } else setList(queue);
        }
      })
      .catch((problem) => { if (active) setError(problem instanceof Error ? problem.message : "读取会话失败。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token, detail, search, query, page, size, router]);

  useEffect(() => {
    if (detail || loading) return;
    const timer = setTimeout(() => {
      try { window.scrollTo(0, Number(sessionStorage.getItem(scrollKey)) || 0); } catch { /* Browser storage is optional. */ }
    }, 0);
    return () => clearTimeout(timer);
  }, [detail, loading, scrollKey]);
  function rememberPosition() {
    try { sessionStorage.setItem(scrollKey, String(window.scrollY)); } catch { /* Browser storage is optional. */ }
  }
  const running = session?.review?.retests.some((item) => ["accepted", "running"].includes(item.status));
  useEffect(() => {
    if (!detail || !running) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const current = await evaluationRequest<SessionDetail>(token, `/sessions/${encodeURIComponent(detail)}`);
        if (!active) return;
        setSession(current);
        if (current.review?.retests.some((item) => ["accepted", "running"].includes(item.status))) timer = setTimeout(poll, 1500);
      } catch (problem) { if (active) setError(problem instanceof Error ? problem.message : "验证结果读取失败，请刷新记录。"); }
    }
    timer = setTimeout(poll, 800);
    return () => { active = false; clearTimeout(timer); };
  }, [detail, token, running]);

  function navigate(values: Record<string, string | number>) {
    const next = new URLSearchParams(query);
    Object.entries(values).forEach(([key, value]) => next.set(key, String(value)));
    router.push(`${evaluationHref("runs")}?${next}`);
  }
  async function refresh() {
    setError("");
    try {
      if (detail) setSession(await evaluationRequest<SessionDetail>(token, `/sessions/${encodeURIComponent(detail)}`));
      else setList(await evaluationRequest<Queue>(token, `/sessions?${search}`));
    } catch (problem) { setError(problem instanceof Error ? problem.message : "刷新失败。"); }
  }
  async function act(action: string, fields: Record<string, unknown> = {}, next = false) {
    if (!session) return false;
    setBusy(true); setError(""); setNotice("");
    const payload = { action, expected_revision: session.review?.revision ?? 0, ...fields };
    const fingerprint = JSON.stringify(payload);
    if (mutation.current?.fingerprint !== fingerprint) mutation.current = { fingerprint, action_id: crypto.randomUUID() };
    try {
      const current = await evaluationRequest<SessionDetail>(token, `/sessions/${encodeURIComponent(session.session_id)}/reviews`, evaluationJson({ ...payload, action_id: mutation.current.action_id }));
      setSession(current); mutation.current = null;
      setNotice(action === "pass" ? "人工审核已通过。" : action === "issue" ? "问题已保存，可在“需修改”中继续处理。" : "审核意见已保存。");
      if (next) {
        const queue = await evaluationRequest<Queue>(token, `/sessions?${search}`);
        let candidate = queue.items.find((item) => item.created_at < session.created_at || (item.created_at === session.created_at && item.session_id < session.session_id));
        if (!candidate && queue.total > page * size) {
          const later = new URLSearchParams(search); later.set("offset", String(page * size));
          candidate = (await evaluationRequest<Queue>(token, `/sessions?${later}`)).items.find((item) => item.session_id !== session.session_id);
          if (candidate) { const laterQuery = new URLSearchParams(query); laterQuery.set("page", String(page + 1)); router.push(`${evaluationHref("runs", candidate.session_id)}?${laterQuery}`); return true; }
        }
        if (!candidate && page > 1 && ["pending", "needs_changes"].includes(reviewFilter)) {
          const first = new URLSearchParams(search); first.set("offset", "0");
          candidate = (await evaluationRequest<Queue>(token, `/sessions?${first}`)).items.find((item) => item.session_id !== session.session_id);
          if (candidate) { const firstQuery = new URLSearchParams(query); firstQuery.set("page", "1"); router.push(`${evaluationHref("runs", candidate.session_id)}?${firstQuery}`); return true; }
        }
        if (candidate) router.push(`${evaluationHref("runs", candidate.session_id)}${suffix}`);
        else router.push(listHref);
      }
      return true;
    } catch (problem) { setError(problem instanceof Error ? problem.message : "保存失败，输入已保留。"); return false; }
    finally { setBusy(false); }
  }
  async function retest(runId: string, issue?: SessionIssue) {
    if (!session) return;
    setBusy(true); setError(""); setNotice("");
    const payload = { source_run_id: runId, issue_id: issue?.issue_id ?? null };
    const fingerprint = JSON.stringify(payload);
    if (pendingRetest.current?.fingerprint !== fingerprint) pendingRetest.current = { fingerprint, submission_id: crypto.randomUUID() };
    try {
      setSession(await evaluationRequest<SessionDetail>(token, `/sessions/${encodeURIComponent(session.session_id)}/retests`, evaluationJson({ ...payload, submission_id: pendingRetest.current.submission_id })));
      pendingRetest.current = null;
      setNotice("已开始验证，使用当前资料和配置，并保留原请求的文字上下文。完成后请核对新回答。");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "验证提交失败，可重试。"); }
    finally { setBusy(false); }
  }

  if (detail) return <section className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><Link href={listHref} className={button}>返回列表</Link><button className={button} disabled={busy} onClick={() => void refresh()}>刷新记录</button></div>
    {loading && <p role="status">正在读取会话…</p>}{error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}
    {session && !loading && <>
      <section className="space-y-3 rounded-xl border bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{session.topic}</h2><p className="mt-1 text-xs text-slate-500">{dateTime(session.created_at)} · {session.turn_count} 轮 · {session.operator_id}</p></div>
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-sm">{reviewLabels[session.review_status ?? "pending"]}</span></div>
        {!!session.reviewed_turn_count && <p className="text-sm text-slate-600">上次已审到第 {session.reviewed_turn_count} 轮{session.reviewed_turn_count < session.turn_count ? "，新增内容待审核。" : "。"}</p>}
        <div className="flex flex-wrap gap-2"><button className="rounded-lg bg-emerald-800 px-4 py-2 text-sm text-white disabled:opacity-50" disabled={busy || !!session.open_issue_count || !!editing || !!comment.trim()}
          onClick={() => void act("pass", { run_ids: session.turns.map((turn) => turn.run_id) }, true)}>通过并看下一条</button>
          <button className={button} disabled={busy || !!session.open_issue_count || !!editing || !!comment.trim()} onClick={() => void act("pass", { run_ids: session.turns.map((turn) => turn.run_id) })}>通过</button>
          {!!session.open_issue_count && <span className="self-center text-sm text-amber-800">还有 {session.open_issue_count} 个问题待处理。</span>}</div>
        <details className="text-xs text-slate-500"><summary className="cursor-pointer">会话信息</summary><p className="mt-2 break-all">{session.session_id} · 运行{session.status} · 累计 {session.latency_ms} ms</p></details>
      </section>
      <ol className="space-y-5">{session.turns.map((turn, index) => {
        const canRetest = !!turn.request_snapshot?.query && !turn.request_snapshot.has_attachments && !turn.state_before?.attachment_ref && !(turn.evidence as { source_type?: string }[] | undefined)?.some((item) => item.source_type === "file");
        const issues = session.review?.issues.filter((item) => item.run_id === turn.run_id) ?? [];
        const retests = session.review?.retests.filter((item) => item.source_run_id === turn.run_id) ?? [];
        return <li key={turn.run_id} className="space-y-3 rounded-xl border bg-white p-4">
          <p className="text-xs text-slate-500">第 {index + 1} 轮 · {dateTime(turn.started_at)}{index >= (session.reviewed_turn_count ?? 0) ? " · 待审核" : ""}</p>
          <div className="ml-auto max-w-[95%] rounded-xl bg-emerald-900 px-4 py-3 text-sm text-white"><p className="mb-1 text-xs opacity-75">用户</p><p className="whitespace-pre-wrap break-words">{turn.input}</p></div>
          <div className="rounded-xl bg-slate-50 px-4 py-3 text-sm"><p className="mb-1 text-xs text-slate-500">助手{turn.status !== "ok" ? " · 本轮运行异常" : ""}</p><MarkdownAnswer content={turn.answer || (turn.error_code ? `本轮未完成：${turn.error_code}` : "本轮没有回答内容")} /></div>
          <EvidenceLinks turn={turn} />
          <div className="flex flex-wrap gap-3"><button className={button} disabled={busy || (!!editing && editing !== turn.run_id)} onClick={() => setEditing(turn.run_id)}>标记问题</button>
            {canRetest ? <button className={button} disabled={busy || running} onClick={() => void retest(turn.run_id)}>用原问题验证</button> : <Link className={button} href="/" target="_blank" rel="noopener noreferrer">到前台补充原材料验证 ↗</Link>}</div>
          {editing === turn.run_id && <form className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3" onSubmit={(event) => { event.preventDefault(); void act("issue", { run_id: turn.run_id, note: issueNote }).then((saved) => { if (saved) { setEditing(""); setIssueNote(""); } }); }}>
            <label className="block space-y-2 text-sm"><span>哪里有问题，希望怎么改</span><textarea autoFocus className={field} rows={3} required maxLength={5000} value={issueNote} onChange={(event) => setIssueNote(event.target.value)} /></label>
            <div className="flex gap-2"><button className={button} disabled={busy || !issueNote.trim()}>保存问题</button><button type="button" className={button} disabled={busy} onClick={() => { setEditing(""); setIssueNote(""); }}>取消</button></div>
          </form>}
          {issues.map((issue) => {
            const verification = [...retests].reverse().find((item) => item.issue_id === issue.issue_id && item.status === "succeeded");
            return <section key={issue.issue_id} aria-label="已标记问题" className="space-y-3 rounded-lg border border-amber-200 p-3 text-sm">
              <p className="font-medium">{issue.status === "open" ? "待修改" : "已确认解决"} · {issue.recorded_by}</p><p className="whitespace-pre-wrap">{issue.note}</p>
              {issue.status === "open" ? <>
                <div className="flex flex-wrap gap-3">{canRetest ? <button className={button} disabled={busy || running} onClick={() => void retest(turn.run_id, issue)}>修改后重新验证</button> : <Link className={button} href="/" target="_blank" rel="noopener noreferrer">到前台补传原材料验证 ↗</Link>}
                  <Link target="_blank" rel="noopener noreferrer" className="self-center text-emerald-800 underline" href={evaluationHref("literature")}>修改文献 ↗</Link><Link target="_blank" rel="noopener noreferrer" className="self-center text-emerald-800 underline" href={evaluationHref("case-library")}>修改案例 ↗</Link>
                  <Link target="_blank" rel="noopener noreferrer" className="self-center text-emerald-800 underline" href={`${evaluationHref("explanation-trials")}?source_run=${encodeURIComponent(turn.run_id)}`}>调整 Prompt ↗</Link></div>
                <details open={!canRetest || undefined}><summary className="cursor-pointer text-xs text-slate-500">直接核对或已在前台验证？填写确认依据</summary><label className="mt-2 block space-y-1"><span className="text-xs">手动确认依据</span><textarea className={field} rows={2} maxLength={5000} value={resolutionNotes[issue.issue_id] ?? ""} onChange={(event) => setResolutionNotes((current) => ({ ...current, [issue.issue_id]: event.target.value }))} /></label></details>
                <button className={button} disabled={busy || (!verification && !resolutionNotes[issue.issue_id]?.trim())} onClick={() => void act("resolve", { issue_id: issue.issue_id, verification_run_id: verification?.run_id ?? null, note: resolutionNotes[issue.issue_id] ?? "" })}>确认解决</button>
              </> : <><p className="text-xs text-slate-500">{issue.resolution_note || "已核对验证回答"}</p><button className={button} disabled={busy} onClick={() => void act("reopen", { issue_id: issue.issue_id, note: "复查后仍需修改" })}>仍有问题，重新打开</button></>}
            </section>;
          })}
          {retests.map((item) => <section key={item.run_id} aria-label="验证回答" className="space-y-2 rounded-lg border border-emerald-200 bg-emerald-50/40 p-3 text-sm"><p className="font-medium">验证回答 · {item.recorded_by} · {dateTime(item.recorded_at)}</p><p className="text-xs text-slate-500">使用当前资料和配置，原回答保留在上方。</p>
            <MarkdownAnswer content={item.answer || item.error || (["accepted", "running"].includes(item.status) ? "正在生成验证回答…" : "本次验证未完成，请重新验证。")} />
            {item.status === "succeeded" && <p className="text-xs text-emerald-800">请人工核对回答是否符合修改要求。</p>}</section>)}
          <TraceDetails turn={turn} />
        </li>;
      })}</ol>
      <section className="space-y-3 rounded-xl border bg-white p-4"><details><summary className="cursor-pointer text-sm font-medium">补充意见 / 协助复核（可选）</summary><div className="mt-3 space-y-3">
        <textarea aria-label="补充审核意见" className={field} rows={3} maxLength={5000} value={comment} onChange={(event) => setComment(event.target.value)} />
        <button className={button} disabled={busy || !comment.trim()} onClick={() => void act("comment", { note: comment }).then((saved) => { if (saved) setComment(""); })}>保存意见</button></div></details>
        <details className="text-sm"><summary className="cursor-pointer">审核历史（{session.review?.history.length ?? 0}）</summary><div className="mt-3 space-y-3">{session.review?.history.map((event, index) => <div key={index} className="border-l-2 pl-3"><p className="text-xs text-slate-500">{event.recorded_by} · {dateTime(event.recorded_at)} · {historyLabels[event.action] ?? event.action} · 人工操作</p>{event.note && <p className="mt-1 whitespace-pre-wrap">{event.note}</p>}</div>)}</div></details>
      </section>
    </>}
  </section>;

  const pages = Math.max(1, Math.ceil(list.total / size));
  const visiblePages = Array.from({ length: pages }, (_, i) => i + 1).filter((number) => pages <= 7 || number === 1 || number === pages || Math.abs(number - page) <= 2);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (draft.from && draft.to && new Date(draft.from) > new Date(draft.to)) { setError("结束时间不能早于起始时间。"); return; }
    if (draft.durationMode && (draft.duration === "" || Number(draft.duration) < 0 || (draft.durationMode === "between" && (draft.durationMax === "" || Number(draft.durationMax) < Number(draft.duration))))) { setError("请填写有效的耗时条件。"); return; }
    navigate({ information: draft.information, from: draft.from, to: draft.to, status: draft.status, operator_id: draft.operator, duration_mode: draft.durationMode, duration_ms: draft.duration, duration_max_ms: draft.durationMax, review_status: draftReview, page: 1 });
  }
  return <section className="space-y-4 rounded-xl border bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">运行记录 · 会话审核</h2><p className="mt-1 text-sm text-slate-500">看完整会话，符合预期就通过，有问题就留下修改意见。</p></div><button className={button} onClick={() => void refresh()}>刷新记录</button></div>
    <div className="flex flex-wrap gap-2" aria-label="审核状态快捷筛选">{[["pending", "待审核"], ["needs_changes", "需修改"], ["passed", "已通过"], ["", "全部"]].map(([value, label]) => <button key={value} className={`${button} ${reviewFilter === value ? "border-emerald-700 bg-emerald-50 text-emerald-900" : ""}`} aria-pressed={reviewFilter === value} onClick={() => navigate({ review_status: value, page: 1 })}>{label}</button>)}</div>
    <form className="space-y-3 rounded-lg bg-slate-50 p-3" onSubmit={submit}>
      <div className="flex flex-wrap items-end gap-2"><label className="min-w-40 flex-1 space-y-1 text-sm">会话信息<input className={field} placeholder="主题或会话 ID" value={draft.information} onChange={(event) => setDraft({ ...draft, information: event.target.value })} /></label>
        <label className="space-y-1 text-sm">审核状态<select className={field} value={draftReview} onChange={(event) => setDraftReview(event.target.value)}><option value="">全部</option>{Object.entries(reviewLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <button type="submit" className={button}>查询</button><button type="button" className={button} onClick={() => router.push(evaluationHref("runs"))}>重置</button></div>
      <details><summary className="cursor-pointer text-xs text-slate-500">更多筛选</summary><div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <label className="space-y-1 text-sm">起始时间<input className={field} type="datetime-local" value={draft.from} onChange={(event) => setDraft({ ...draft, from: event.target.value })} /></label>
        <label className="space-y-1 text-sm">结束时间<input className={field} type="datetime-local" value={draft.to} onChange={(event) => setDraft({ ...draft, to: event.target.value })} /></label>
        <label className="space-y-1 text-sm">运行状态<select className={field} value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="">全部</option><option>正常</option><option>异常</option></select></label>
        <label className="space-y-1 text-sm">操作人<input className={field} value={draft.operator} onChange={(event) => setDraft({ ...draft, operator: event.target.value })} /></label>
        <label className="space-y-1 text-sm">耗时条件<select className={field} value={draft.durationMode} onChange={(event) => setDraft({ ...draft, durationMode: event.target.value })}><option value="">不限</option><option value="gt">大于</option><option value="lt">小于</option><option value="eq">等于</option><option value="between">区间</option></select></label>
        <label className="space-y-1 text-sm">耗时（毫秒）<input className={field} type="number" min="0" disabled={!draft.durationMode} value={draft.duration} onChange={(event) => setDraft({ ...draft, duration: event.target.value })} /></label>
        {draft.durationMode === "between" && <label className="space-y-1 text-sm">最大耗时（毫秒）<input className={field} type="number" min="0" value={draft.durationMax} onChange={(event) => setDraft({ ...draft, durationMax: event.target.value })} /></label>}
      </div></details>
    </form>
    <p role="status" className="text-sm">{loading ? "正在查询…" : `共查到 ${list.total} 条会话记录`}</p>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <div className="overflow-x-auto rounded-lg border"><table className="w-full min-w-[680px] text-left text-sm"><thead className="bg-slate-50"><tr>{["会话主题", "创建时间", "问答轮数", "审核状态", "操作"].map((name) => <th key={name} className="px-3 py-2">{name}</th>)}</tr></thead>
      <tbody>{list.items.map((item) => <tr key={item.session_id} className="border-t"><td className="px-3 py-3"><Link onClick={rememberPosition} href={`${evaluationHref("runs", item.session_id)}${suffix}`} className="font-medium text-emerald-900">{item.topic}</Link><p className="mt-1 text-xs text-slate-500">{item.operator_id} · 运行{item.status}</p></td><td className="whitespace-nowrap px-3 py-2">{dateTime(item.created_at)}</td><td className="px-3 py-2">{item.turn_count}</td><td className="px-3 py-2">{reviewLabels[item.review_status ?? "pending"]}{!!item.open_issue_count && ` · ${item.open_issue_count} 个问题`}</td><td className="px-3 py-2"><Link onClick={rememberPosition} className="text-emerald-700 underline" href={`${evaluationHref("runs", item.session_id)}${suffix}`}>查看</Link></td></tr>)}</tbody></table></div>
    {!loading && !list.items.length && <p className="py-6 text-center text-sm text-slate-500">{reviewFilter === "pending" ? "当前范围的会话已审核完，可查看全部或需修改的会话。" : "没有符合条件的会话。"}</p>}
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm"><label className="flex items-center gap-2">每页<select aria-label="每页条数" className={field} value={size} onChange={(event) => navigate({ size: event.target.value, page: 1 })}>{pageSizes.map((count) => <option key={count} value={count}>{count}</option>)}</select>条</label>
      <nav aria-label="会话分页" className="flex flex-wrap gap-1"><button className={button} disabled={page <= 1} onClick={() => navigate({ page: page - 1 })}>上一页</button>
        {visiblePages.map((number, index) => <span key={number} className="flex items-center gap-1">{index > 0 && number - visiblePages[index - 1] > 1 && <span className="px-1">…</span>}<button aria-current={number === page ? "page" : undefined} className={`${button} ${number === page ? "border-emerald-700 bg-emerald-50" : ""}`} onClick={() => navigate({ page: number })}>{number}</button></span>)}
        <button className={button} disabled={page >= pages} onClick={() => navigate({ page: page + 1 })}>下一页</button></nav></div>
  </section>;
}
