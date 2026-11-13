"use client";

import Image from "next/image";
import { FileText, Paperclip } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { apiBaseUrl } from "@/lib/api";
import { evaluationRequest } from "@/lib/evaluation-api";

export type RunAttachment = { filename: string; sha256?: string; format?: string };
type Preview = { filename: string } & (
  { kind: "pdf"; page: number; page_count: number; image: string }
  | { kind: "text"; text: string }
  | { kind: "table"; sheet: number; sheets: string[]; offset: number; total_rows: number;
    total_columns: number; rows: unknown[][]; columns_truncated: boolean }
);
const button = "rounded-md border px-3 py-2 text-xs hover:bg-slate-50 disabled:opacity-50";

function columnLabel(index: number): string {
  return index < 26 ? String.fromCharCode(65 + index) : `A${String.fromCharCode(65 + index - 26)}`;
}

export function RunAttachmentPreview({ attachment, token, sessionId, runId }: {
  attachment: RunAttachment; token: string; sessionId: string; runId: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const request = useRef<AbortController | null>(null);
  const downloadRequest = useRef<AbortController | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const path = `/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(runId)}/${encodeURIComponent(attachment.sha256 ?? "")}`;
  useEffect(() => () => { request.current?.abort(); downloadRequest.current?.abort(); }, []);

  function close() {
    request.current?.abort(); downloadRequest.current?.abort();
    dialog.current?.close(); setPreview(null); setLoading(false); setDownloading(false);
    setError(""); setDownloadError("");
  }
  async function load(parameters: Record<string, number> = {}) {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setError(""); setLoading(true);
    if (!attachment.sha256) {
      setError("这份历史附件未保存原文件信息，暂时无法预览。请重新上传后提交问题。");
      setLoading(false); return;
    }
    try {
      const params = new URLSearchParams(Object.entries(parameters).map(([key, value]) => [key, String(value)]));
      const result = await evaluationRequest<Preview>(token, `${path}/preview?${params}`, {
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]),
      });
      if (!controller.signal.aborted) setPreview(result);
    } catch (problem) {
      if (!controller.signal.aborted) setError(problem instanceof Error ? problem.message : "附件暂时无法预览。");
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }
  async function download() {
    const controller = new AbortController(); downloadRequest.current = controller;
    setDownloading(true); setDownloadError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/eval${path}/content`, {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(result?.detail?.message ?? "原文件下载失败，请重试。");
      }
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = attachment.filename;
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (problem) {
      if (!controller.signal.aborted) setDownloadError(problem instanceof Error ? problem.message : "原文件下载失败。");
    } finally { if (!controller.signal.aborted) setDownloading(false); }
  }
  return <>
    <button type="button" aria-label={`预览附件：${attachment.filename}`} onClick={() => { dialog.current?.showModal(); void load(); }}
      className="flex w-full items-center gap-3 rounded-lg border border-white/25 bg-white/10 p-3 text-left hover:bg-white/20">
      <FileText aria-hidden="true" className="size-7 shrink-0 opacity-80" />
      <span className="min-w-0 flex-1"><span className="block break-all font-medium">{attachment.filename}</span>
        <span className="mt-1 flex items-center gap-1 opacity-75"><Paperclip aria-hidden="true" className="size-3" />点击预览附件</span></span>
    </button>
    <dialog ref={dialog} aria-label="附件预览" onCancel={close}
      className="fixed inset-0 m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-5xl overflow-auto rounded-xl border bg-white p-4 text-slate-900 shadow-xl backdrop:bg-black/50">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1"><h3 className="break-all text-base font-semibold">{attachment.filename}</h3><p className="mt-1 text-xs text-slate-500">本轮提交的附件</p></div>
        <div className="flex gap-2"><button className={button} disabled={downloading || !attachment.sha256} onClick={() => void download()}>{downloading ? "正在下载…" : "下载原文件"}</button>
          <button className={button} onClick={close}>关闭预览</button></div>
      </div>
      {loading && <p role="status" className="py-4 text-sm">正在加载附件…</p>}
      {error && <div role="alert" className="space-y-3 rounded-lg bg-amber-50 p-4 text-sm text-amber-900"><p>{error}</p>
        {attachment.sha256 && <button className={button} onClick={() => void load()}>重试预览</button>}</div>}
      {downloadError && <p role="alert" className="mb-3 text-sm text-red-700">{downloadError}</p>}
      {preview?.kind === "pdf" && <div className="space-y-3">
        <div className="flex items-center justify-center gap-3 text-sm"><button className={button} disabled={loading || preview.page <= 1} onClick={() => void load({ page: preview.page - 1 })}>上一页</button>
          <span>第 {preview.page} / {preview.page_count} 页</span><button className={button} disabled={loading || preview.page >= preview.page_count} onClick={() => void load({ page: preview.page + 1 })}>下一页</button></div>
        <div className="rounded-lg bg-slate-100 p-2"><Image unoptimized src={preview.image} alt={`附件第 ${preview.page} 页预览`} width={1200} height={1700} className="mx-auto h-auto max-w-full rounded border bg-white" /></div>
      </div>}
      {preview?.kind === "text" && <pre className="max-h-[65dvh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-4 text-sm leading-7">{preview.text}</pre>}
      {preview?.kind === "table" && <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm"><label className="flex items-center gap-2">工作表<select value={preview.sheet} disabled={loading} className="max-w-60 rounded border p-2" onChange={(event) => void load({ sheet: Number(event.target.value), offset: 0 })}>
          {preview.sheets.map((name, index) => <option value={index} key={index}>{name}</option>)}</select></label>
          <p>共 {preview.total_rows} 行 · {preview.total_columns} 列</p></div>
        {preview.columns_truncated && <p className="text-xs text-amber-800">预览显示前 50 列，完整内容可下载原文件查看。</p>}
        <div className="max-h-[55dvh] overflow-auto rounded border"><table className="w-full text-left text-xs"><thead className="sticky top-0 bg-slate-100"><tr><th className="border-b p-2">行</th>
          {Array.from({ length: Math.min(50, preview.total_columns) }, (_, index) => <th key={index} className="border-b p-2">{columnLabel(index)}</th>)}</tr></thead>
          <tbody>{preview.rows.map((row, index) => <tr key={index} className="border-b"><th className="bg-slate-50 p-2 font-normal">{preview.offset + index + 1}</th>
            {row.map((cell, column) => <td key={column} className="max-w-80 whitespace-pre-wrap break-words border-l p-2">{cell == null ? "" : String(cell)}</td>)}</tr>)}</tbody></table>
          {!preview.rows.length && <p className="p-4 text-sm text-slate-500">此工作表没有数据。</p>}</div>
        <div className="flex flex-wrap items-center justify-center gap-3 text-sm"><button className={button} disabled={loading || preview.offset <= 0} onClick={() => void load({ sheet: preview.sheet, offset: Math.max(0, preview.offset - 100) })}>上一页数据</button>
          <span>{preview.total_rows ? `第 ${preview.offset + 1}–${preview.offset + preview.rows.length} 行` : "0 行"}</span>
          <button className={button} disabled={loading || preview.offset + preview.rows.length >= preview.total_rows} onClick={() => void load({ sheet: preview.sheet, offset: preview.offset + 100 })}>下一页数据</button></div>
      </div>}
    </dialog>
  </>;
}
