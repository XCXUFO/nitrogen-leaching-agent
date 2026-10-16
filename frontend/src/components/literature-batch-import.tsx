"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiBaseUrl } from "@/lib/api";

type ImportItem = { filename: string; paper_id?: string; status: string; warnings: string[]; retryable?: boolean };
type Batch = { kind?: "existing"; id: string; created_at: string; items: ImportItem[] };
type Upload = { file: File; fingerprint?: string; status: "waiting" | "uploading" | "uploaded" | "failed" | "duplicate"; upload_id?: string; paper_id?: string; message?: string };
const button = "rounded-lg border px-3 py-2 text-sm disabled:opacity-50";
const primary = `${button} bg-emerald-700 text-white`;
const labels: Record<string, string> = { waiting: "等待上传", uploading: "上传中", uploaded: "已上传", queued: "等待 AI 处理", processing: "AI 处理中", ready: "已成功录入", warning: "已保存（有异常）", failed: "处理失败", duplicate: "重复文件，已跳过" };

class ImportError extends Error {
  constructor(message: string, public paperId?: string) { super(message); }
}

export function LiteratureBatchImport({ token, maxPdfMb, onChanged, selectedIds, onSubmitted, onSingle }: { token: string; maxPdfMb: number; onChanged: () => void; selectedIds: string[]; onSubmitted: () => void; onSingle: () => void }) {
  const [mode, setMode] = useState<"import" | "existing" | "history" | null>(null);
  const [currentId, setCurrentId] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (mode) dialog.current?.showModal(); else dialog.current?.close(); }, [mode]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [aiExtract, setAiExtract] = useState(true);
  const [aiTag, setAiTag] = useState(true);
  const [processExtract, setProcessExtract] = useState(true);
  const [processTag, setProcessTag] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const locked = useRef(false);
  const changed = useRef(onChanged);
  useEffect(() => { changed.current = onChanged; }, [onChanged]);
  const request = useCallback(async <T,>(path: string, init?: RequestInit): Promise<T> => {
    const response = await fetch(`${apiBaseUrl}/api/literature${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, ...init?.headers }, cache: "no-store" });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new CustomEvent("evaluation-session-expired", { detail: { token } }));
      throw new ImportError(data?.detail?.message || `请求失败（${response.status}），请重试。`, data?.detail?.paper_id);
    }
    return data;
  }, [token]);
  const refresh = useCallback(async () => {
    if (!currentId) return;
    const result = await request<Batch>(`/imports/${currentId}`);
    setBatches([result]);
  }, [request, currentId]);
  useEffect(() => {
    if (!mode || !currentId && mode !== "history") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let previous = "";
    const poll = async () => {
      try {
        const result = currentId
          ? { items: [await request<Batch>(`/imports/${currentId}`)] }
          : await request<{ items: Batch[] }>("/imports");
        if (cancelled) return;
        setBatches(result.items);
        const signature = JSON.stringify(result.items);
        if (signature !== previous) changed.current();
        previous = signature;
      } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : "无法获取导入进度。"); }
      if (!cancelled) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [request, currentId, mode]);
  useEffect(() => {
    if (!busy) return;
    const leave = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    const navigate = (event: MouseEvent) => {
      if ((event.target as HTMLElement).closest("a[href]") && !window.confirm("文件仍在上传，离开可能中断导入。确认离开？")) {
        event.preventDefault(); event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", leave);
    document.addEventListener("click", navigate, true);
    return () => { window.removeEventListener("beforeunload", leave); document.removeEventListener("click", navigate, true); };
  }, [busy]);

  function select(files: File[]) {
    if (locked.current || !files.length) return;
    setError("");
    if (uploads.length + files.length > 100) { setError("一次批量导入最多 100 篇，已保留当前队列，请减少新增文件后重新选择。"); return; }
    const added: Upload[] = files.map((file) => ({ file, status: !file.name.toLowerCase().endsWith(".pdf") || !file.size || file.size > maxPdfMb * 1024 * 1024 ? "failed" : "waiting",
      message: !file.name.toLowerCase().endsWith(".pdf") ? "仅支持 PDF 文件。" : !file.size ? "文件为空。" : file.size > maxPdfMb * 1024 * 1024 ? `单篇不能超过 ${maxPdfMb} MB。` : undefined }));
    setUploads((previous) => [...previous, ...added]);
  }
  async function uploadValid() {
    if (locked.current || !uploads.length) return;
    locked.current = true; setBusy(true); setError("");
    const rows = uploads.map((row) => ({ ...row }));
    const publish = () => setUploads(rows.map((row) => ({ ...row })));
    let cursor = 0;
    const fingerprints = new Set(rows.filter((row) => row.status === "uploaded").flatMap((row) => row.fingerprint ? [row.fingerprint] : []));
    try {
      const worker = async () => {
        while (cursor < rows.length) {
          const row = rows[cursor++];
          if (row.status === "uploaded" || row.status === "duplicate") continue;
          if (!row.file.name.toLowerCase().endsWith(".pdf") || !row.file.size || row.file.size > maxPdfMb * 1024 * 1024) continue;
          row.status = "uploading"; row.message = ""; publish();
          try {
            if (crypto.subtle) {
              const digest = await crypto.subtle.digest("SHA-256", await row.file.arrayBuffer());
              const fingerprint = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
              if (fingerprints.has(fingerprint)) { row.status = "duplicate"; row.message = "与本批次文件内容重复。"; publish(); continue; }
              fingerprints.add(fingerprint); row.fingerprint = fingerprint;
            }
            const receipt = await request<{ upload_id: string; sha256?: string }>(`/uploads?filename=${encodeURIComponent(row.file.name)}`, { method: "POST", body: row.file });
            if (!row.fingerprint && receipt.sha256) {
              if (fingerprints.has(receipt.sha256)) { row.status = "duplicate"; row.message = "与本批次文件内容重复。"; publish(); continue; }
              fingerprints.add(receipt.sha256); row.fingerprint = receipt.sha256;
            }
            row.upload_id = receipt.upload_id; row.status = "uploaded";
          } catch (e) {
            row.status = e instanceof ImportError && e.paperId ? "duplicate" : "failed";
            row.paper_id = e instanceof ImportError ? e.paperId : undefined;
            row.message = e instanceof Error ? e.message : "上传失败。";
          }
          publish();
        }
      };
      await Promise.all([worker(), worker(), worker()]);
    } catch (e) { setError(e instanceof Error ? e.message : "导入失败，请重试。"); }
    finally { locked.current = false; setBusy(false); }
  }
  async function start() {
    const ids = uploads.flatMap((row) => row.status === "uploaded" && row.upload_id ? [row.upload_id] : []);
    if (locked.current || !ids.length || uploads.some((row) => row.status === "waiting")) return;
    locked.current = true; setBusy(true); setError("");
    try {
      const batch = await request<Batch>("/imports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ upload_ids: ids, ai_extract: aiExtract, ai_tag: aiTag }) });
      setCurrentId(batch.id); setBatches([batch]); changed.current();
    } catch (e) { setError(e instanceof Error ? e.message : "导入失败，请重试。"); }
    finally { locked.current = false; setBusy(false); }
  }
  async function processSelected() {
    if (locked.current || !selectedIds.length || !processExtract && !processTag) return;
    locked.current = true; setBusy(true); setError("");
    try {
      const batch = await request<Batch>("/batch-ai", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paper_ids: selectedIds, ai_extract: processExtract, ai_tag: processTag }) });
      setCurrentId(batch.id); setBatches([batch]); onSubmitted(); changed.current();
    } catch (e) { setError(e instanceof Error ? e.message : "批量处理失败，请重试。"); }
    finally { locked.current = false; setBusy(false); }
  }
  async function retry(id: string, paperId?: string) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError("");
    try { await request(`/imports/${id}/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paper_ids: paperId ? [paperId] : undefined }) }); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "重试失败。"); }
    finally { locked.current = false; setBusy(false); }
  }
  const batch = batches.find((item) => item.id === currentId);
  const active = batch?.items.some((item) => ["queued", "processing"].includes(item.status) && !item.retryable);
  const success = batch && batch.items.every((item) => item.status === "ready");
  function open(next: "import" | "existing" | "history") { setMode(next); setCurrentId(""); setBatches([]); setUploads([]); setError(""); }
  return <section className="flex flex-wrap items-center gap-3">
    <button className={primary} onClick={onSingle}>单个导入</button>
    <button className={primary} onClick={() => open("import")}>批量导入</button>
    <button className={button} disabled={!selectedIds.length} onClick={() => open("existing")}>批量 AI 解析 · 已选 {selectedIds.length} 篇</button>
    <button className={button} onClick={() => open("history")}>近期批次与恢复</button>
    <dialog aria-labelledby="literature-batch-title" ref={dialog} onCancel={(event) => { if (busy) event.preventDefault(); else setMode(null); }} onClose={() => setMode(null)} className="fixed inset-0 m-auto max-h-[85vh] w-[min(56rem,94vw)] overflow-auto rounded-xl border bg-white p-6 backdrop:bg-black/40">
      <div className="mb-4 flex items-center justify-between"><h2 id="literature-batch-title" className="text-lg font-semibold">{mode === "import" ? "批量导入文献" : mode === "history" ? "近期批次与恢复" : "已有文献批量 AI 解析"}</h2><button className={button} disabled={busy} onClick={() => setMode(null)}>关闭流程</button></div>
      {error && <p role="alert" className="mb-3 text-sm text-red-700">{error}</p>}
      {mode === "import" && !currentId && <div className="space-y-4">
        <h3 className="font-medium">第一步：上传并校验文献</h3>
        <label className="block text-sm">一次最多 100 篇 PDF，每篇不超过 {maxPdfMb} MB<input aria-label="批量选择 PDF" type="file" multiple accept=".pdf,application/pdf" disabled={busy} onChange={(event) => { select(Array.from(event.target.files || [])); event.target.value = ""; }} /></label>
        <button className={button} disabled={busy || !uploads.some((row) => ["waiting", "failed"].includes(row.status) && row.file.size > 0 && row.file.size <= maxPdfMb * 1024 * 1024 && row.file.name.toLowerCase().endsWith(".pdf"))} onClick={() => void uploadValid()}>{busy ? "正在上传…" : "上传并校验"}</button>
        <p role="status" className="text-sm">有效文献 {uploads.filter((row) => row.status === "uploaded").length} 篇 / 已选择 {uploads.length} 篇</p>
      </div>}
      {mode === "import" && !!uploads.length && <ul className="my-4 max-h-48 space-y-2 overflow-auto text-sm">{uploads.map((row, index) => <li key={index}>{row.file.name} · {labels[row.status]} {row.message}{row.paper_id && <Link className="ml-2 underline" href={`/evaluation/literature/${row.paper_id}`}>查看现有文献</Link>}{!currentId && <button type="button" className="ml-2 text-slate-500 underline disabled:opacity-50" aria-label={`移除 ${row.file.name}`} disabled={busy} onClick={() => setUploads((previous) => previous.filter((_, position) => position !== index))}>移除</button>}</li>)}</ul>}
      {mode === "history" && !currentId && <div className="space-y-3">
        <p className="text-sm text-slate-500">当前账号最近 10 批。关闭流程不会取消后台处理；中断任务等待 5 分钟后可重试。</p>
        {batches.map((item) => <button key={item.id} className={`${button} block w-full text-left`} onClick={() => { setCurrentId(item.id); setError(""); }}>
          {item.kind === "existing" ? "已有文献 AI 处理" : "批量导入"} · {item.created_at} · {item.items.length} 篇 · {item.items[0]?.filename}
        </button>)}
        {!batches.length && !error && <p className="text-sm text-slate-500">暂无批次记录</p>}
      </div>}
      {!currentId && mode !== "history" && <div className="mt-4 space-y-3">
        <h3 className="font-medium">{mode === "import" ? "第二步：选择 AI 处理并录入" : `已选择 ${selectedIds.length} 篇文献`}</h3>
        <div className="flex gap-5 text-sm">
          <label><input type="checkbox" checked={mode === "import" ? aiExtract : processExtract} disabled={busy} onChange={(e) => mode === "import" ? setAiExtract(e.target.checked) : setProcessExtract(e.target.checked)} />AI 解析字段</label>
          <label><input type="checkbox" checked={mode === "import" ? aiTag : processTag} disabled={busy} onChange={(e) => mode === "import" ? setAiTag(e.target.checked) : setProcessTag(e.target.checked)} />AI 一键打标</label>
        </div>
        <p className="text-xs text-slate-500">{mode === "import" ? "可分别勾选，也可不使用 AI。有效文献将保存为草稿，处理结果自动保存。" : "解析成功的字段覆盖已有值，未解析到的字段保留；打标成功后替换原标签。"}</p>
        <button className={primary} disabled={busy || (mode === "import" ? !uploads.some((row) => row.status === "uploaded") || uploads.some((row) => row.status === "waiting") : !selectedIds.length || !processExtract && !processTag)} onClick={() => void (mode === "import" ? start() : processSelected())}>{busy ? "正在提交…" : mode === "import" ? "处理并录入" : "AI 解析所选文献"}</button>
      </div>}
      {batch && <div className="mt-4 space-y-3">
        <p role="status">{active ? "本批次正在处理…" : success ? "本批次全部成功解析并录入，流程已完成。" : "本批次处理结束，存在异常。可重试异常文献或关闭流程。"}</p>
        <ul className="space-y-2 text-sm">{batch.items.map((item, index) => <li key={index} className="rounded border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><span>{item.filename} · {labels[item.status]}</span>{item.paper_id && <Link className="underline" href={`/evaluation/literature/${item.paper_id}?edit=1`}>审核文献</Link>}</div>
          {item.warnings.map((warning, i) => <p key={i} className="text-amber-800">{warning}</p>)}
          {item.retryable && <button className={button} disabled={busy} onClick={() => void retry(batch.id, item.paper_id)}>重新解析此文献</button>}
        </li>)}</ul>
        {success && <button className={primary} onClick={() => setMode(null)}>完成</button>}
      </div>}
    </dialog>
  </section>;
}
