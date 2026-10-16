"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiBaseUrl } from "@/lib/api";

type Item = { case_id: string; title: string; status: string; message: string; retryable: boolean };
type Job = { id: string; created_at: string; items: Item[] };
const button = "rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-50";
const labels: Record<string, string> = { queued: "排队中", processing: "打标中", ready: "已完成", failed: "失败", conflict: "已跳过" };

export function CaseBatchTagging({ token, selectedIds, selectedRecords, onSubmitted, onChanged }: {
  token: string; selectedIds: string[]; selectedRecords: { id: string; revision: number }[]; onSubmitted: () => void; onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"actions" | "current" | "history">("actions");
  const [currentId, setCurrentId] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const locked = useRef(false);
  const changed = useRef(onChanged);
  useEffect(() => { changed.current = onChanged; }, [onChanged]);
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  const request = useCallback(async <T,>(path: string, init?: RequestInit, availability = false): Promise<T> => {
    const response = await fetch(`${apiBaseUrl}/api/case-library${availability ? "/batch-availability" : `/tag-jobs${path}`}`, {
      ...init, headers: { Authorization: `Bearer ${token}`, ...init?.headers }, cache: "no-store",
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new CustomEvent("evaluation-session-expired", { detail: { token } }));
      const fallback = response.status === 404 || response.status === 405
        ? "批量操作服务版本未更新，请联系管理员更新后端后重试。"
        : response.status === 401 ? "登录已失效，请重新登录。"
        : response.status === 422 ? "案例选择无效，请刷新列表后重试。"
        : `批量操作服务异常（HTTP ${response.status}），请稍后重试。`;
      throw new Error(data?.detail?.message || fallback);
    }
    return data;
  }, [token]);
  useEffect(() => {
    if (!open || !currentId && view !== "history") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let previous = "";
    const poll = async () => {
      try {
        const result = currentId ? [await request<Job>(`/${currentId}`)] : (await request<{ items: Job[] }>("")).items;
        if (cancelled) return;
        setJobs(result); setError("");
        const signature = JSON.stringify(result);
        if (currentId && signature !== previous) changed.current();
        previous = signature;
      } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : "读取失败。"); }
      if (!cancelled) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [open, currentId, view, request]);

  async function start() {
    if (locked.current || !selectedIds.length) return;
    locked.current = true; setBusy(true); setError(""); setJobs([]); setCurrentId(""); setView("current"); setOpen(true);
    try {
      const job = await request<Job>("", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_ids: selectedIds }) });
      setJobs([job]); setCurrentId(job.id); onSubmitted(); changed.current();
    } catch (e) { setError(e instanceof Error ? e.message : "打标失败。"); }
    finally { locked.current = false; setBusy(false); }
  }
  async function retry() {
    if (locked.current || !currentId) return;
    locked.current = true; setBusy(true); setError("");
    try {
      setJobs([await request<Job>(`/${currentId}/retry`, { method: "POST" })]);
      changed.current();
    } catch (e) { setError(e instanceof Error ? e.message : "重试失败。"); }
    finally { locked.current = false; setBusy(false); }
  }
  async function changeAvailability(enabled: boolean) {
    if (locked.current || !selectedIds.length) return;
    locked.current = true; setBusy(true); setError(""); setResult("");
    try {
      const result = await request<{ updated: number }>("", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        items: selectedRecords.filter((item) => selectedIds.includes(item.id)).map((item) => ({ case_id: item.id, expected_revision: item.revision })), enabled,
      }) }, true);
      setResult(`已${enabled ? "开放" : "关闭"} ${result.updated} 条案例的 Agent 使用`);
      onSubmitted(); changed.current();
    } catch (e) { setError(e instanceof Error ? e.message : "批量操作失败。"); }
    finally { locked.current = false; setBusy(false); }
  }
  const current = jobs.find((job) => job.id === currentId);
  return <div className="flex flex-wrap gap-2">
    <button type="button" className={`${button} bg-emerald-700 text-white`} disabled={busy || !selectedIds.length} onClick={() => { setView("actions"); setCurrentId(""); setJobs([]); setError(""); setResult(""); setOpen(true); }}>批量操作{selectedIds.length ? `（${selectedIds.length}）` : ""}</button>
    <button type="button" className={button} disabled={busy} onClick={() => { setView("history"); setCurrentId(""); setJobs([]); setError(""); setOpen(true); }}>打标记录</button>
    <dialog ref={dialog} aria-label={view === "actions" ? "批量操作" : "案例 AI 打标"} onCancel={(event) => { if (busy) event.preventDefault(); else setOpen(false); }} onClose={() => setOpen(false)} className="fixed inset-0 m-auto max-h-[80vh] w-[min(40rem,94vw)] space-y-4 overflow-auto rounded-xl border bg-white p-5 backdrop:bg-black/40">
      <div className="flex items-center justify-between"><h2 className="font-semibold">{view === "actions" ? "批量操作" : view === "history" && !currentId ? "打标记录" : "案例 AI 打标"}</h2><button type="button" className={button} disabled={busy} onClick={() => setOpen(false)}>关闭</button></div>
      {view === "actions" && <>
        {!result && <p className="text-sm text-slate-600">已选择 {selectedIds.length} 条案例</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" className={`${button} bg-emerald-700 text-white`} disabled={busy || !selectedIds.length} onClick={() => void start()}>AI 一键打标</button>
          <button type="button" className={button} disabled={busy || !selectedIds.length} onClick={() => void changeAvailability(true)}>批量开放 Agent 使用</button>
          <button type="button" className={button} disabled={busy || !selectedIds.length} onClick={() => void changeAvailability(false)}>批量关闭 Agent 使用</button>
        </div>
        {result && <p role="status" className="text-sm text-emerald-700">{result}</p>}
      </>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {busy && <p role="status" className="text-sm">正在提交…</p>}
      {view === "history" && !currentId && jobs.map((job) => <button type="button" key={job.id} className={`${button} block w-full text-left`} onClick={() => setCurrentId(job.id)}>
        {new Date(job.created_at).toLocaleString("zh-CN")} · {job.items.length} 条 · {job.items[0]?.title}
      </button>)}
      {current && <>
        <p role="status" className="text-sm">已完成 {current.items.filter((item) => item.status === "ready").length} / {current.items.length}</p>
        <ul className="space-y-2">{current.items.map((item) => <li key={item.case_id} className="rounded-lg border p-3 text-sm">
          <div className="flex justify-between gap-3"><Link className="text-emerald-700 underline" href={`/evaluation/case-library/${item.case_id}`}>{item.title}</Link><span>{labels[item.status]}</span></div>
          {item.message && <p className="mt-1 text-slate-600">{item.message}</p>}
        </li>)}</ul>
        {current.items.some((item) => item.retryable) && <button type="button" className={button} disabled={busy} onClick={() => void retry()}>重试未完成</button>}
      </>}
    </dialog>
  </div>;
}
