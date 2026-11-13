"use client";

import Link from "next/link";
import { EvaluationHandoff } from "./evaluation-handoff";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Search } from "lucide-react";
import { evaluationJson, evaluationRequest } from "@/lib/evaluation-api";
import type { SessionDetail, SessionSummary, SessionTrace } from "@/lib/evaluation-api";
import { MarkdownAnswer } from "./chat/markdown-answer";
import { RunOverview } from "./run-overview";
import { evaluationHref } from "@/lib/evaluation-navigation";
import { RunAttachmentPreview, type RunAttachment } from "./run-attachment-preview";
import { CaptureConversation } from './conversation-cases';

type Filters = { information: string; from: string; to: string; status: string;
  durationMode: string; duration: string; durationMax: string; operator: string };
const emptyFilters = (): Filters => ({ information: "", from: "", to: "", status: "",
  durationMode: "", duration: "", durationMax: "", operator: "" });
const field = "wb-field";
const button = "wb-button";
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
  const starred = turn.starred_match && typeof turn.starred_match === "object" ? turn.starred_match as Record<string, unknown> : null;
  const coverageLabels: Record<string, string> = { full: "完整覆盖", partial: "部分覆盖", empty_answer: "命中空答案", conflict: "材料有冲突", empty_library: "空库", not_ready: "内容未就绪", no_match: "未命中", failed: "匹配失败，已继续原链路", unavailable: "服务不可用", not_applicable: "本轮不适用" };
  const pipelines = (Array.isArray(turn.retrieval) ? turn.retrieval : []).flatMap((record: unknown) => {
    if (!record || typeof record !== "object" || !("pipeline" in record)) return [];
    const pipeline = record.pipeline;
    return pipeline && typeof pipeline === "object" ? [pipeline as Record<string, unknown>] : [];
  });
  const groups: [string, unknown][] = [
    ["路由决策", turn.decision], ["任务计划与依赖", turn.execution_plan], ["工具调用", turn.tool_calls], ["运行前状态", turn.state_before],
    ["运行后状态", turn.state_after], ["证据", turn.evidence], ["答案与证据关联", turn.sections],
    ["未完成部分", turn.warnings], ["配置与文件版本", turn.config_manifest],
    ["问题理解与条件来源", turn.understanding], ["星标后剩余需求上下文", turn.execution_context], ["标签映射与用途", turn.tag_mapping],
    ["星标匹配与覆盖", turn.starred_match], ["检索与条件核对", turn.retrieval], ["联网取证与充分性", turn.web_retrieval],
    ["案例对象与任务模式", turn.case_context], ["当时的表达配置", turn.skill_config], ["实际执行事件", turn.execution_steps], ["最终输出组成", turn.answer_assembly],
  ];
  return <details className="rounded-lg border bg-white p-3">
    <summary className="cursor-pointer text-sm font-medium">展开本轮 MQ 明细 · Run {turn.run_id}</summary>
    <div className="mt-3 space-y-2"><StateContext turn={turn} /><Flow turn={turn} />
      {turn.execution_plan && <p className="rounded border bg-slate-50 p-3 text-xs text-slate-600">本轮计划：{turn.execution_plan.tasks?.length ?? 0} 项子任务 · {turn.execution_plan.mode === "specified" ? "指定模式" : "自动模式"}。实际记录 {turn.execution_plan.actual_calls?.length ?? 0} 次能力调用，结果：{turn.execution_plan.outcome ?? "未知"}。候选能力及依赖状态可展开核对。</p>}
      {starred && <p className="rounded border bg-amber-50/50 p-3 text-xs text-slate-600">星标前置：{coverageLabels[String(starred.status)] ?? "历史状态未知"} · 采用 {Array.isArray(starred.adopted) ? starred.adopted.length : 0} 项参考答复 · 剩余 {Array.isArray(starred.remaining_subtask_ids) ? starred.remaining_subtask_ids.length : "未知"} 项任务。范围、来源、内容快照及未覆盖需求可在明细中核对。</p>}
      {pipelines.map((pipeline, index) => <p key={index} className="rounded border bg-slate-50 p-3 text-xs text-slate-600">检索索引：{String(pipeline.version ?? "未知")} · 状态 {String(pipeline.status ?? "未知")} · 候选 {String(pipeline.candidate_count ?? "未知")} · 本次更新 {String(pipeline.rebuilt_materials ?? "未知")} 份 · {String(pipeline.elapsed_ms ?? "未知")} ms{pipeline.coverage === "bounded" ? " · 已应用候选预算" : ""}{pipeline.fallback ? ` · 回退 ${String(pipeline.fallback)}` : ""}。各路贡献与条件核对见明细。</p>)}
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

function TurnAttachments({ turn, token, sessionId }: { turn: SessionTrace; token: string; sessionId: string }) {
  const files: RunAttachment[] = [...(turn.request_snapshot?.attachments ?? [])];
  if (!files.length && turn.request_snapshot?.has_attachments !== false) {
    for (const item of (turn.evidence ?? []) as { source_type?: string; provenance?: { filename?: string; source?: string } }[]) {
      const source = item.provenance?.source;
      if (item.source_type === "file" && item.provenance?.filename) files.push({ filename: item.provenance.filename });
      else if (source?.startsWith("session://")) files.push({ filename: source.split("/").slice(3).join("/") });
    }
  }
  const attachments = files.filter((file, index) => file.filename && files.findIndex((other) => other.filename === file.filename && other.sha256 === file.sha256) === index);
  return <div aria-label="本轮附件" className="mt-3 border-t border-white/20 pt-2 text-xs">
    {attachments.length ? <><p className="opacity-75">本轮附件（{attachments.length}）</p><ul className="mt-2 space-y-2">
      {attachments.map((attachment, index) => <li key={index}><RunAttachmentPreview attachment={attachment} token={token} sessionId={sessionId} runId={turn.run_id} /></li>)}
    </ul></> : <p className="opacity-75">{turn.request_snapshot?.has_attachments
      ? "本轮携带附件，历史记录未保存文件名。" : turn.request_snapshot?.has_attachments === false
        ? "本轮未携带附件" : "历史记录未保存本轮附件信息。"}</p>}
  </div>;
}

function EvaluationRunsCore({ token, detail, query = "", actor = "", canEdit = false }: { token: string; detail: string; query?: string; actor?: string; canEdit?: boolean }) {
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
  const detailHref = `${evaluationHref("runs", detail)}${suffix}`;
  const previousKey = (href: string) => `conversation-review-previous:${actor}:${href}`;
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
  function openNext(sessionId: string, targetQuery = query) {
    const href = `${evaluationHref("runs", sessionId)}${targetQuery ? `?${targetQuery}` : ""}`;
    try { sessionStorage.setItem(previousKey(href), detailHref); } catch { /* Ordered navigation still works without storage. */ }
    router.push(href);
  }
  async function previousSession(current: SessionDetail) {
    try {
      const visited = sessionStorage.getItem(previousKey(detailHref));
      if (visited?.startsWith(`${evaluationHref("runs")}/`) && visited !== detailHref) {
        router.push(visited); return;
      }
    } catch { /* Fall back to the preceding record in the filtered list. */ }
    try {
      const precedes = (item: SessionSummary) => item.created_at > current.created_at
        || (item.created_at === current.created_at && item.session_id > current.session_id);
      const queue = await evaluationRequest<Queue>(token, `/sessions?${search}`);
      let candidate = queue.items.filter(precedes).at(-1);
      let targetPage = page;
      if (!candidate && page > 1) {
        const earlier = new URLSearchParams(search); earlier.set("offset", String((page - 2) * size));
        candidate = (await evaluationRequest<Queue>(token, `/sessions?${earlier}`)).items.filter(precedes).at(-1);
        targetPage = page - 1;
      }
      if (candidate) {
        const earlierQuery = new URLSearchParams(query);
        if (targetPage !== page) earlierQuery.set("page", String(targetPage));
        router.push(`${evaluationHref("runs", candidate.session_id)}${earlierQuery.size ? `?${earlierQuery}` : ""}`);
      } else setNotice("已经是第一条记录。");
    } catch (problem) { setError(`切换上一条失败，请重试。${problem instanceof Error ? problem.message : ""}`); }
  }
  async function nextSession(current: SessionDetail) {
    try {
      const queue = await evaluationRequest<Queue>(token, `/sessions?${search}`);
      let candidate = queue.items.find((item) => item.created_at < current.created_at || (item.created_at === current.created_at && item.session_id < current.session_id));
      if (!candidate && queue.total > page * size) {
        const later = new URLSearchParams(search); later.set("offset", String(page * size));
        candidate = (await evaluationRequest<Queue>(token, `/sessions?${later}`)).items.find((item) => item.session_id !== current.session_id);
        if (candidate) { const laterQuery = new URLSearchParams(query); laterQuery.set("page", String(page + 1)); openNext(candidate.session_id, laterQuery.toString()); return; }
      }
      if (!candidate && page > 1 && ["pending", "needs_changes"].includes(reviewFilter) && current.review_status !== reviewFilter) {
        const first = new URLSearchParams(search); first.set("offset", "0");
        candidate = (await evaluationRequest<Queue>(token, `/sessions?${first}`)).items.find((item) => item.session_id !== current.session_id);
        if (candidate) { const firstQuery = new URLSearchParams(query); firstQuery.set("page", "1"); openNext(candidate.session_id, firstQuery.toString()); return; }
      }
      if (candidate) openNext(candidate.session_id);
      else router.push(listHref);
    } catch (problem) { setError(`切换下一条失败，请重试。${problem instanceof Error ? problem.message : ""}`); }
  }
  async function viewAdjacent(direction: "previous" | "next") {
    if (!session) return;
    setBusy(true); setError(""); setNotice("");
    try { await (direction === "previous" ? previousSession(session) : nextSession(session)); }
    finally { setBusy(false); }
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
      if (next) await nextSession(current);
      return true;
    } catch (problem) { setError(problem instanceof Error ? problem.message : "保存失败，输入已保留。"); return false; }
    finally { setBusy(false); }
  }

  if (detail) return <section className="space-y-5">
    <div className="flex justify-end"><button className={button} disabled={busy} onClick={() => void refresh()}>刷新记录</button></div>
    {loading && <p role="status">正在读取会话…</p>}{error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}
    {session && !loading && <>
      <section className="wb-panel space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{session.topic}</h2><p className="mt-1 text-xs text-slate-500">{dateTime(session.created_at)} · {session.turn_count} 轮 · {session.operator_id}</p></div>
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-sm">{reviewLabels[session.review_status ?? "pending"]}</span></div>
        {!!session.reviewed_turn_count && <p className="text-sm text-slate-600">上次已审到第 {session.reviewed_turn_count} 轮{session.reviewed_turn_count < session.turn_count ? "，新增内容待审核。" : "。"}</p>}
        <CaptureConversation token={token} sessionId={session.session_id} title={session.topic} readOnly={!canEdit} onSaved={() => void refresh()} />
        {!!session.case_groups?.length && <div className="flex flex-wrap gap-3 text-sm">{session.case_groups.map((g) => <Link className="text-emerald-800 underline" key={g.group_id} href={`/evaluation/case-groups/${g.group_id}`}>已收藏：{g.title}</Link>)}</div>}
        <div className="flex flex-wrap gap-2"><button className="rounded-lg bg-emerald-800 px-4 py-2 text-sm text-white disabled:opacity-50" disabled={!canEdit || busy || !!session.open_issue_count || !!editing || !!comment.trim()}
          onClick={() => void act("pass", { run_ids: session.turns.map((turn) => turn.run_id) }, true)}>通过并看下一条</button>
          <button className={button} disabled={!canEdit || busy || !!session.open_issue_count || !!editing || !!comment.trim()} onClick={() => void act("pass", { run_ids: session.turns.map((turn) => turn.run_id) })}>通过</button>
          <button className={button} disabled={busy || !!editing || !!comment.trim()} onClick={() => void viewAdjacent("previous")}>上一条</button>
          <button className={button} disabled={busy || !!editing || !!comment.trim()} onClick={() => void viewAdjacent("next")}>下一条</button>
          {!!session.open_issue_count && <span className="self-center text-sm text-amber-800">还有 {session.open_issue_count} 个问题待处理。</span>}</div>
        <details className="text-xs text-slate-500"><summary className="cursor-pointer">会话信息</summary><p className="mt-2 break-all">{session.session_id} · 运行{session.status} · 累计 {session.latency_ms} ms</p></details>
      </section>
      <ol className="space-y-5">{session.turns.map((turn, index) => {
        const canRetest = !!turn.request_snapshot?.query && !turn.request_snapshot.has_attachments && !turn.state_before?.attachment_ref && !(turn.evidence as { source_type?: string }[] | undefined)?.some((item) => item.source_type === "file");
        const issues = session.review?.issues.filter((item) => item.run_id === turn.run_id) ?? [];
        const retests = session.review?.retests.filter((item) => item.source_run_id === turn.run_id) ?? [];
        return <li key={turn.run_id} className="wb-panel space-y-4">
          <p className="text-xs text-slate-500">第 {index + 1} 轮 · {dateTime(turn.started_at)}{index >= (session.reviewed_turn_count ?? 0) ? " · 待审核" : ""}</p>
          <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-4 py-3 text-sm text-slate-900"><p className="mb-1 text-xs opacity-75">用户</p><p className="whitespace-pre-wrap break-words">{turn.input}</p><TurnAttachments turn={turn} token={token} sessionId={session.session_id} /></div>
          <div className="rounded-xl bg-slate-50 px-4 py-3 text-sm"><p className="mb-1 text-xs text-slate-500">助手{turn.status !== "ok" ? " · 本轮运行异常" : ""}</p><MarkdownAnswer content={turn.answer || (turn.error_code ? `本轮未完成：${turn.error_code}` : "本轮没有回答内容")} /></div>
          <EvidenceLinks turn={turn} />
          <RunOverview turn={turn} />
          <div className="flex flex-wrap gap-3">{canEdit && <button className={button} disabled={busy || (!!editing && editing !== turn.run_id)} onClick={() => setEditing(turn.run_id)}>标记问题</button>}
            <Link className={button} href="/evaluation/issues">到问题处理归纳与验证</Link></div>
          {editing === turn.run_id && <form className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3" onSubmit={(event) => { event.preventDefault(); const next = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "next"; void act("issue", { run_id: turn.run_id, note: issueNote }, next).then((saved) => { if (saved) { setEditing(""); setIssueNote(""); } }); }}>
            <label className="block space-y-2 text-sm"><span>哪里有问题，希望怎么改</span><textarea autoFocus className={field} rows={3} required maxLength={5000} value={issueNote} onChange={(event) => setIssueNote(event.target.value)} /></label>
            <div className="flex flex-wrap gap-2"><button className={button} disabled={busy || !issueNote.trim()}>保存问题</button><button className={button} value="next" disabled={busy || !issueNote.trim() || !!comment.trim()}>保存并看下一条</button><button type="button" className={button} disabled={busy} onClick={() => { setEditing(""); setIssueNote(""); }}>取消</button></div>
          </form>}
          {issues.map((issue) => {
            const verification = [...retests].reverse().find((item) => item.issue_id === issue.issue_id && item.status === "succeeded");
            return <section key={issue.issue_id} aria-label="已标记问题" className="space-y-3 rounded-lg border border-amber-200 p-3 text-sm">
              <p className="font-medium">{issue.status === "open" ? "待修改" : "已确认解决"} · {issue.recorded_by}</p><p className="whitespace-pre-wrap">{issue.note}</p>
              {issue.status === "open" ? <fieldset disabled={!canEdit} className="space-y-3">
                <div className="flex flex-wrap gap-3"><Link className={button} href="/evaluation/issues">验证完整会话并处理问题</Link>
                  <Link target="_blank" rel="noopener noreferrer" className="self-center text-emerald-800 underline" href={evaluationHref("literature")}>修改文献 ↗</Link><Link target="_blank" rel="noopener noreferrer" className="self-center text-emerald-800 underline" href={evaluationHref("case-library")}>修改案例 ↗</Link>
                  <Link target="_blank" rel="noopener noreferrer" className="self-center text-emerald-800 underline" href={`${evaluationHref("explanation-trials")}?source_run=${encodeURIComponent(turn.run_id)}`}>调整 Prompt ↗</Link></div>
                <details open={!canRetest || undefined}><summary className="cursor-pointer text-xs text-slate-500">直接核对或已在前台验证？填写确认依据</summary><label className="mt-2 block space-y-1"><span className="text-xs">手动确认依据</span><textarea className={field} rows={2} maxLength={5000} value={resolutionNotes[issue.issue_id] ?? ""} onChange={(event) => setResolutionNotes((current) => ({ ...current, [issue.issue_id]: event.target.value }))} /></label></details>
                <button className={button} disabled={busy || (!verification && !resolutionNotes[issue.issue_id]?.trim())} onClick={() => void act("resolve", { issue_id: issue.issue_id, verification_run_id: verification?.run_id ?? null, note: resolutionNotes[issue.issue_id] ?? "" })}>确认解决</button>
              </fieldset> : <><p className="text-xs text-slate-500">{issue.resolution_note || "已核对验证回答"}</p>{canEdit && <button className={button} disabled={busy} onClick={() => void act("reopen", { issue_id: issue.issue_id, note: "复查后仍需修改" })}>仍有问题，重新打开</button>}</>}
            </section>;
          })}
          {retests.map((item) => <section key={item.run_id} aria-label="验证回答" className="space-y-2 rounded-lg border border-emerald-200 bg-emerald-50/40 p-3 text-sm"><p className="font-medium">验证回答 · {item.recorded_by} · {dateTime(item.recorded_at)}</p><p className="text-xs text-slate-500">使用当前资料和配置，原回答保留在上方。</p>
            <MarkdownAnswer content={item.answer || item.error || (["accepted", "running"].includes(item.status) ? "正在生成验证回答…" : "本次验证未完成，请重新验证。")} />
            {item.status === "succeeded" && <p className="text-xs text-emerald-800">请人工核对回答是否符合修改要求。</p>}</section>)}
          <TraceDetails turn={turn} />
        </li>;
      })}</ol>
      <section className="wb-panel space-y-4"><details><summary className="cursor-pointer text-sm font-medium">补充意见 / 协助复核（可选）</summary><div className="mt-3 space-y-3">
        <textarea aria-label="补充审核意见" disabled={!canEdit} className={field} rows={3} maxLength={5000} value={comment} onChange={(event) => setComment(event.target.value)} />
        <button className={button} disabled={!canEdit || busy || !comment.trim()} onClick={() => void act("comment", { note: comment }).then((saved) => { if (saved) setComment(""); })}>保存意见</button></div></details>
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
  return <section className="wb-panel space-y-5"><div className="wb-panel-header border-b pb-1">
    <div className="wb-tabs border-b-0" role="group" aria-label="审核状态快捷筛选">{[["pending", "待审核"], ["needs_changes", "需修改"], ["passed", "已通过"], ["", "全部"]].map(([value, label]) => <button key={value} className="wb-tab" aria-pressed={reviewFilter === value} onClick={() => navigate({ review_status: value, page: 1 })}>{label}</button>)}</div>
    <button className={button} onClick={() => void refresh()}><RefreshCw size={14} aria-hidden="true" />刷新记录</button></div>
    <form className="space-y-4" onSubmit={submit}>
      <div className="wb-filter-grid"><label className="wb-filter-label">会话信息<input name="information" autoComplete="off" className={field} placeholder="搜索主题或会话 ID…" value={draft.information} onChange={(event) => setDraft({ ...draft, information: event.target.value })} /></label>
        <label className="wb-filter-label">审核状态<select name="review_status" className={field} value={draftReview} onChange={(event) => setDraftReview(event.target.value)}><option value="">全部</option>{Object.entries(reviewLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="wb-filter-label">运行状态<select name="status" className={field} value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="">全部</option><option value="正常">运行正常</option><option value="异常">运行异常</option></select></label>
        <div className="wb-filter-actions"><button type="submit" className="wb-button wb-button-primary"><Search size={14} aria-hidden="true" />查询</button><button type="button" className={button} onClick={() => router.push(evaluationHref("runs"))}>重置</button></div></div>
      <details><summary className="cursor-pointer text-xs text-slate-500">更多筛选</summary><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="space-y-1 text-sm">起始时间<input className={field} type="datetime-local" value={draft.from} onChange={(event) => setDraft({ ...draft, from: event.target.value })} /></label>
        <label className="space-y-1 text-sm">结束时间<input className={field} type="datetime-local" value={draft.to} onChange={(event) => setDraft({ ...draft, to: event.target.value })} /></label>
        <label className="space-y-1 text-sm">操作人<input className={field} value={draft.operator} onChange={(event) => setDraft({ ...draft, operator: event.target.value })} /></label>
        <label className="space-y-1 text-sm">耗时条件<select className={field} value={draft.durationMode} onChange={(event) => setDraft({ ...draft, durationMode: event.target.value })}><option value="">不限</option><option value="gt">大于</option><option value="lt">小于</option><option value="eq">等于</option><option value="between">区间</option></select></label>
        <label className="space-y-1 text-sm">耗时（毫秒）<input className={field} type="number" min="0" disabled={!draft.durationMode} value={draft.duration} onChange={(event) => setDraft({ ...draft, duration: event.target.value })} /></label>
        {draft.durationMode === "between" && <label className="space-y-1 text-sm">最大耗时（毫秒）<input className={field} type="number" min="0" value={draft.durationMax} onChange={(event) => setDraft({ ...draft, durationMax: event.target.value })} /></label>}
      </div></details>
    </form>
    <p role="status" aria-live="polite" className="text-xs text-slate-500">{loading ? "正在查询…" : `共查到 ${list.total} 条会话记录`}</p>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <div className="wb-table-wrap"><table aria-label="会话运行记录" aria-busy={loading} className="wb-table min-w-[680px]"><thead><tr>{["会话主题", "创建时间", "问答轮数", "审核状态", "操作"].map((name, index) => <th key={name} scope="col" className={index === 2 ? "wb-numeric" : index === 4 ? "text-right" : ""}>{name}</th>)}</tr></thead>
      <tbody>{list.items.map((item) => <tr key={item.session_id}><td className="wb-topic break-words [overflow-wrap:anywhere]"><Link onClick={rememberPosition} href={`${evaluationHref("runs", item.session_id)}${suffix}`}>{item.topic}</Link><p>{item.operator_id} · 运行{item.status}</p></td><td className="whitespace-nowrap text-slate-500">{dateTime(item.created_at)}</td><td className="wb-numeric">{item.turn_count}</td><td><span className="wb-status" data-status={item.review_status ?? "pending"}>{reviewLabels[item.review_status ?? "pending"]}</span>{!!item.open_issue_count && <span className="mt-1 block text-xs text-slate-500">{item.open_issue_count} 个问题</span>}</td><td className="text-right"><Link onClick={rememberPosition} className="text-emerald-800 hover:underline" href={`${evaluationHref("runs", item.session_id)}${suffix}`}>查看</Link></td></tr>)}
      {!loading && !list.items.length && <tr><td colSpan={5}><p className="wb-empty">{reviewFilter === "pending" ? "当前范围的会话已审核完，可查看全部或需修改的会话。" : "没有符合条件的会话。"}</p></td></tr>}</tbody></table></div>
    <div className="wb-pagination"><label className="flex items-center gap-2 whitespace-nowrap">每页<select aria-label="每页条数" className={field} value={size} onChange={(event) => navigate({ size: event.target.value, page: 1 })}>{pageSizes.map((count) => <option key={count} value={count}>{count}</option>)}</select>条</label>
      <nav aria-label="会话分页" className="flex items-center gap-1"><button className={button} disabled={page <= 1} onClick={() => navigate({ page: page - 1 })}>上一页</button>
        <span className="px-2 sm:hidden">{page} / {pages}</span>
        {visiblePages.map((number, index) => <span key={number} className="hidden items-center gap-1 sm:flex">{index > 0 && number - visiblePages[index - 1] > 1 && <span className="px-1">…</span>}<button aria-current={number === page ? "page" : undefined} className={button} onClick={() => navigate({ page: number })}>{number}</button></span>)}
        <button className={button} disabled={page >= pages} onClick={() => navigate({ page: page + 1 })}>下一页</button></nav></div>
  </section>;
}

export function EvaluationRuns(props: { token: string; detail: string; query?: string; actor?: string; canHandoff?: boolean; canEdit?: boolean }) {
  const offline = new URLSearchParams(props.query ?? "").get("source") === "handoff";
  if (offline && !props.canHandoff) return <p role="alert">本地交接复测仅供开发者使用。</p>;
  if (offline) return <EvaluationHandoff key={props.detail} token={props.token} detail={props.detail} />;
  return <div className="space-y-4"><EvaluationRunsCore {...props} />{props.canHandoff && <Link href="/evaluation/runs?source=handoff" className="inline-block text-xs text-slate-500 hover:text-emerald-800 hover:underline">查看本地交接的 8 条审核来源</Link>}</div>;
}
