"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiBaseUrl } from "@/lib/api";

type Item = { kind: "literature" | "case"; asset_id: string; title: string; status: string; message: string; before_tags: string[] | null; after_tags: string[] | null };
type Job = { id: string; actor: string; created_at: string; mode: "merge" | "replace"; total: number; counts: Record<string, number>; assets: Record<string, number>; active: boolean; interrupted: boolean; retryable: boolean; taxonomy_changed: boolean; items?: Item[] };
type Taxonomy = { dimensions: { id: string; name: string }[]; tags: { id: string; name: string; path: string; dimension_id: string }[] };
const button = "wb-button";
const labels: Record<string, string> = { queued: "排队中", processing: "打标中", ready: "已完成", failed: "失败", conflict: "已跳过" };

export function AssetBatchTagging({ token, onChanged, taxonomy }: { token: string; onChanged: () => Promise<void>; taxonomy: Taxonomy }) {
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [selected, setSelected] = useState("");
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const locked = useRef(false);
  const changed = useRef(onChanged);
  useEffect(() => { changed.current = onChanged; }, [onChanged]);
  const request = useCallback(async <T,>(path: string, init?: RequestInit): Promise<T> => {
    const response = await fetch(`${apiBaseUrl}/api/literature/asset-tag-jobs${path}`, {
      ...init, cache: "no-store", headers: { Authorization: `Bearer ${token}`, ...init?.headers },
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new CustomEvent("evaluation-session-expired", { detail: { token } }));
      throw new Error(data?.detail?.message || `全库打标请求失败（${response.status}）。`);
    }
    return data;
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    request<{ items: Job[] }>("").then((result) => {
      if (cancelled) return;
      setJobs(result.items);
      setSelected((current) => current || result.items[0]?.id || "");
      setLoading(false);
    }).catch((e) => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [request, reload]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let previousReady: number | undefined;
    async function poll() {
      try {
        const result = await request<Job>(`/${selected}?offset=${page * 50}&limit=50`);
        if (cancelled) return;
        setJob(result); setError("");
        setJobs((current) => current.map((item) => item.id === result.id ? result : item));
        if (previousReady !== result.counts.ready) {
          previousReady = result.counts.ready;
          void changed.current().catch(() => { /* The task receipt remains available if counts cannot refresh. */ });
        }
        if (result.active) timer = setTimeout(poll, 3000);
      } catch (e) {
        if (!cancelled) { setError(e instanceof Error ? e.message : "读取任务失败。"); timer = setTimeout(poll, 5000); }
      }
    }
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [selected, page, request, reload]);

  async function submit(retry = false) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError("");
    try {
      const result = await request<Job>(retry ? `/${selected}/retry` : "", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }),
      });
      setJob(result); setSelected(result.id); setPage(0); setReload((value) => value + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "提交失败。"); }
    finally { locked.current = false; setBusy(false); }
  }

  // An older history entry must not enable a second job while the newest runs.
  const running = jobs.find((item) => item.active && !item.taxonomy_changed && item.id !== job?.id);
  const active = Boolean(running || job?.active && !job.taxonomy_changed);
  const completed = job ? (job.counts.ready || 0) + (job.counts.failed || 0) + (job.counts.conflict || 0) : 0;
  const tagLabels = new Map(taxonomy.tags.map(tag => {
    const dimension = taxonomy.dimensions.find(d => d.id === tag.dimension_id)?.name;
    return [tag.id, `${dimension ? `${dimension}：` : ""}${tag.path || tag.name}`];
  }));
  return <section aria-label="全库一键打标" className="space-y-3 rounded-xl border border-emerald-200 bg-white p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="font-semibold">全库一键打标 <span className="text-xs font-normal text-slate-500">仅开发者</span></h2>
        <p className="mt-1 text-sm text-slate-600">使用当前启用的标签，对全部已保存文献和案例打标，包含草稿和停用资产。任务在后台运行，离开页面后可回来查看。</p></div>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="全库打标方式" className="rounded-lg border px-3 py-2 text-sm" value={mode} disabled={busy || active || loading} onChange={(event) => setMode(event.target.value as "merge" | "replace")}>
          <option value="merge">补充标签，保留已有选择</option><option value="replace">重新打标，替换已有选择</option>
        </select>
        <button type="button" className={`${button} bg-emerald-700 text-white`} disabled={busy || active || loading} onClick={() => void submit()}>{busy ? "正在提交…" : "一键打标全部资产"}</button>
        <button type="button" className={button} disabled={busy} onClick={() => setReload((value) => value + 1)}>刷新打标记录</button>
      </div>
    </div>
    {mode === "replace" && <p className="text-sm text-amber-800">重新打标会替换每项资产的已有标签；未匹配到标签时保存为空。</p>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {loading && <p role="status" className="text-sm">正在读取打标记录…</p>}
    {!!jobs.length && <label className="flex flex-wrap items-center gap-2 text-sm">最近任务<select aria-label="选择全库打标任务" className="max-w-full rounded-lg border p-2" value={selected} onChange={(event) => { setSelected(event.target.value); setJob(null); setPage(0); }}>
      {jobs.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("zh-CN")} · {item.mode === "merge" ? "补充" : "重新打标"} · {item.total} 项</option>)}
    </select></label>}
    {job && <div className="space-y-3 rounded-lg border p-3">
      <p role="status" className="text-sm">{job.interrupted ? "任务中断，可重试" : job.active ? "正在处理" : "处理结束"} · 已处理 {completed} / {job.total} · 文献 {job.assets.literature || 0} 篇 · 案例 {job.assets.case || 0} 条</p>
      <progress aria-label="全库打标进度" className="h-2 w-full accent-emerald-700" value={completed} max={job.total || 1} />
      <p className="text-xs text-slate-600">成功 {job.counts.ready || 0} · 失败 {job.counts.failed || 0} · 跳过 {job.counts.conflict || 0} · {job.mode === "merge" ? "补充标签" : "重新打标"} · 发起人 {job.actor}</p>
      {job.taxonomy_changed && <p className="text-sm text-amber-800">标签体系已变更，请点击“一键打标全部资产”按最新标签重新发起。</p>}
      {job.retryable && !job.taxonomy_changed && <button type="button" className={button} disabled={busy || Boolean(running)} onClick={() => void submit(true)}>重试失败或中断项</button>}
      {!!job.items?.length && <ul className="max-h-80 space-y-2 overflow-auto">{job.items.map((item) => <li key={`${item.kind}:${item.asset_id}`} className="rounded border p-2 text-sm">
        <div className="flex items-start justify-between gap-3"><Link href={`/evaluation/${item.kind === "case" ? "case-library" : "literature"}/${encodeURIComponent(item.asset_id)}`} className="text-emerald-800 underline">{item.kind === "case" ? "案例" : "文献"} · {item.title}</Link><span className="shrink-0">{labels[item.status] || item.status}</span></div>
        <p className="mt-1 text-xs text-slate-600">{item.message}{item.after_tags && ` · 标签 ${item.before_tags?.length || 0} → ${item.after_tags.length} 个`}</p>
        {item.after_tags && <div role="group" aria-label="本次新增标签" className="mt-2 flex flex-wrap items-start gap-1.5 text-xs">
          <span className="py-0.5 text-slate-500">新增：</span>
          {item.after_tags.filter(id => !item.before_tags?.includes(id)).map(id => <span key={id} className="max-w-full break-words rounded bg-emerald-50 px-2 py-0.5 text-emerald-900">{tagLabels.get(id) || `标签 ${id}`}</span>)}
          {item.after_tags.every(id => item.before_tags?.includes(id)) && <span className="py-0.5 text-slate-500">无新增标签</span>}
        </div>}
      </li>)}</ul>}
      {job.total > 50 && <div className="flex items-center gap-3 text-sm"><button type="button" className={button} disabled={page === 0} onClick={() => setPage((value) => value - 1)}>上一页</button><span>第 {page + 1} / {Math.ceil(job.total / 50)} 页</span><button type="button" className={button} disabled={(page + 1) * 50 >= job.total} onClick={() => setPage((value) => value + 1)}>下一页</button></div>}
    </div>}
  </section>;
}
