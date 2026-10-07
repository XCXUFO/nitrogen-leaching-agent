"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { evaluationRequest } from "@/lib/evaluation-api";
import type { SessionDetail, SessionSummary, SessionTrace } from "@/lib/evaluation-api";
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
  if (filters.from) params.set("created_from", new Date(filters.from).toISOString());
  if (filters.to) params.set("created_to", new Date(new Date(filters.to).getTime() + 60_000 - 1).toISOString());
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
  ];
  return <details className="rounded-lg border bg-white p-3">
    <summary className="cursor-pointer text-sm font-medium">展开本轮 MQ 明细 · Run {turn.run_id}</summary>
    <div className="mt-3 space-y-2">
      {groups.map(([name, value]) => <details key={name} open={name === "工具调用"} className="rounded border p-2">
        <summary className="cursor-pointer text-xs">{name}</summary>
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words bg-slate-50 p-2 text-xs">{JSON.stringify(value ?? null, null, 2)}</pre>
      </details>)}
      <details className="rounded border p-2"><summary className="cursor-pointer text-xs">完整运行记录</summary>
        <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words bg-slate-50 p-2 text-xs">{JSON.stringify(turn, null, 2)}</pre>
      </details>
    </div>
  </details>;
}

export function EvaluationRuns({ token, detail }: { token: string; detail: string }) {
  const router = useRouter();
  const [draft, setDraft] = useState(emptyFilters);
  const [applied, setApplied] = useState(emptyFilters);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [revision, setRevision] = useState(0);
  const [list, setList] = useState<{ total: number; items: SessionSummary[] }>({ total: 0, items: [] });
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const path = detail ? `/sessions/${encodeURIComponent(detail)}` : `/sessions?${queryString(applied, page, size)}`;
    evaluationRequest<SessionDetail | { total: number; items: SessionSummary[] }>(token, path)
      .then((result) => { if (!active) return; if (detail) setSession(result as SessionDetail); else setList(result as typeof list); })
      .catch((problem) => { if (active) setError(problem instanceof Error ? problem.message : "读取会话失败。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token, detail, applied, page, size, revision]);

  if (detail) return <section className="space-y-5 rounded-xl border bg-white p-5">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="font-semibold">会话运行详情</h2>
      {session && <p className="mt-1 break-all font-mono text-xs text-slate-500">{session.session_id}</p>}</div>
      <button className={button} onClick={() => router.push(evaluationHref("runs"))}>返回列表</button></div>
    {loading && <p role="status">正在读取会话…</p>}{error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {session && !loading && <><dl className="grid gap-3 rounded-lg bg-slate-50 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
      <div><dt className="text-slate-500">会话主题</dt><dd>{session.topic}</dd></div>
      <div><dt className="text-slate-500">创建时间</dt><dd>{dateTime(session.created_at)}</dd></div>
      <div><dt className="text-slate-500">运行状态</dt><dd>{session.status}</dd></div>
      <div><dt className="text-slate-500">操作人</dt><dd className="break-all">{session.operator_id}</dd></div>
      <div><dt className="text-slate-500">累计耗时</dt><dd>{session.latency_ms} ms</dd></div>
      <div><dt className="text-slate-500">问答轮数</dt><dd>{session.turn_count}</dd></div>
    </dl>
      <p className="text-xs text-slate-500">此处展示前台问答及实际运行轨迹。完整用例评分需另建评测执行。</p>
      <ol className="space-y-5">{session.turns.map((turn, index) => <li key={turn.run_id} className="space-y-3 rounded-xl border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"><span>第 {index + 1} 轮 · {dateTime(turn.started_at)}</span><span>{turn.latency_ms} ms · {turn.status === "ok" ? "正常" : "异常"}</span></div>
        <div className="ml-auto max-w-[90%] rounded-xl bg-emerald-900 px-4 py-3 text-sm text-white"><p className="mb-1 text-xs opacity-75">用户</p><p className="whitespace-pre-wrap break-words">{turn.input}</p></div>
        <div className="max-w-[95%] rounded-xl bg-slate-50 px-4 py-3 text-sm"><p className="mb-1 text-xs text-slate-500">助手 · 任务结果：{turn.outcome ?? turn.error_code ?? "未记录"}</p>
          <p className="whitespace-pre-wrap break-words">{turn.answer || (turn.error_code ? `本轮未完成：${turn.error_code}` : "本轮没有回答内容")}</p></div>
        <StateContext turn={turn} />
        <Flow turn={turn} />
        <TraceDetails turn={turn} />
      </li>)}</ol></>}
  </section>;

  const pages = Math.max(1, Math.ceil(list.total / size));
  const visiblePages = Array.from({ length: pages }, (_, i) => i + 1).filter((number) =>
    pages <= 7 || number === 1 || number === pages || Math.abs(number - page) <= 2);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (draft.from && draft.to && new Date(draft.from) > new Date(draft.to)) { setError("结束时间不能早于起始时间。"); return; }
    if (draft.durationMode && (draft.duration === "" || Number(draft.duration) < 0 ||
        (draft.durationMode === "between" && (draft.durationMax === "" || Number(draft.durationMax) < Number(draft.duration))))) {
      setError("请填写有效的耗时条件。"); return;
    }
    setError(""); setLoading(true); setPage(1); setApplied({ ...draft }); setRevision((value) => value + 1);
  }
  return <section className="space-y-4 rounded-xl border bg-white p-5"><h2 className="font-semibold">运行记录 · 会话总览</h2>
    <p className="text-xs text-slate-500">前台会话自动进入本列表；评测执行和人工评分在“执行记录”中单独管理。耗时为会话内各轮累计。</p>
    <form className="grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4" onSubmit={submit}>
      <label className="space-y-1 text-sm">会话信息<input className={field} placeholder="会话 ID 或主题" value={draft.information} onChange={(e) => setDraft({ ...draft, information: e.target.value })} /></label>
      <label className="space-y-1 text-sm">起始时间<input className={field} type="datetime-local" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} /></label>
      <label className="space-y-1 text-sm">结束时间<input className={field} type="datetime-local" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} /></label>
      <label className="space-y-1 text-sm">运行状态<select className={field} value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}><option value="">全部</option><option>正常</option><option>异常</option></select></label>
      <label className="space-y-1 text-sm">耗时条件<select className={field} value={draft.durationMode} onChange={(e) => setDraft({ ...draft, durationMode: e.target.value })}><option value="">不限</option><option value="gt">大于</option><option value="lt">小于</option><option value="eq">等于</option><option value="between">区间</option></select></label>
      <label className="space-y-1 text-sm">耗时（毫秒）<input className={field} type="number" min="0" disabled={!draft.durationMode} value={draft.duration} onChange={(e) => setDraft({ ...draft, duration: e.target.value })} /></label>
      {draft.durationMode === "between" && <label className="space-y-1 text-sm">最大耗时（毫秒）<input className={field} type="number" min="0" value={draft.durationMax} onChange={(e) => setDraft({ ...draft, durationMax: e.target.value })} /></label>}
      <label className="space-y-1 text-sm">操作人<input className={field} placeholder="游客 ID 或测评者 ID" value={draft.operator} onChange={(e) => setDraft({ ...draft, operator: e.target.value })} /></label>
      <div className="flex items-end gap-2"><button type="submit" className={button}>查询</button><button type="button" className={button} onClick={() => { const empty = emptyFilters(); setDraft(empty); setApplied(empty); setPage(1); setError(""); setLoading(true); setRevision((value) => value + 1); }}>重置</button></div>
    </form>
    <p role="status" className="text-sm">{loading ? "正在查询…" : `共查到 ${list.total} 条会话记录`}</p>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <div className="overflow-x-auto rounded-lg border"><table className="w-full min-w-[900px] text-left text-sm"><thead className="bg-slate-50"><tr>{["会话 ID", "会话主题", "创建时间", "运行状态", "耗时", "操作人", "操作"].map((name) => <th key={name} className="p-3">{name}</th>)}</tr></thead>
      <tbody>{list.items.map((item) => <tr key={item.session_id} className="border-t"><td className="max-w-48 break-all p-3 font-mono text-xs">{item.session_id}</td><td className="p-3">{item.topic}</td><td className="whitespace-nowrap p-3">{dateTime(item.created_at)}</td><td className="p-3">{item.status}</td><td className="whitespace-nowrap p-3">{item.latency_ms} ms</td><td className="max-w-48 break-all p-3 text-xs">{item.operator_id}</td><td className="p-3"><button className="text-emerald-700 underline" onClick={() => router.push(evaluationHref("runs", item.session_id))}>查看</button></td></tr>)}</tbody></table></div>
    {!loading && !list.items.length && <p className="py-6 text-center text-sm text-slate-500">没有符合条件的会话。</p>}
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm"><label className="flex items-center gap-2">每页<select aria-label="每页条数" className={field} value={size} onChange={(e) => { setLoading(true); setSize(Number(e.target.value)); setPage(1); }}>{pageSizes.map((count) => <option key={count} value={count}>{count}</option>)}</select>条</label>
      <nav aria-label="会话分页" className="flex flex-wrap gap-1"><button className={button} disabled={page <= 1} onClick={() => { setLoading(true); setPage(page - 1); }}>上一页</button>
        {visiblePages.map((number, index) => <span key={number} className="flex items-center gap-1">{index > 0 && number - visiblePages[index - 1] > 1 && <span className="px-1">…</span>}<button aria-current={number === page ? "page" : undefined} className={`${button} ${number === page ? "border-emerald-700 bg-emerald-50" : ""}`} onClick={() => { setLoading(true); setPage(number); }}>{number}</button></span>)}
        <button className={button} disabled={page >= pages} onClick={() => { setLoading(true); setPage(page + 1); }}>下一页</button></nav></div>
  </section>;
}
