"use client";

import { useEffect, useRef, useState } from "react";
import { apiBaseUrl } from "@/lib/api";
import type { Citation } from "@/lib/types";

export function DocumentActions({ citation }: { citation: Citation }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const request = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [downloadStatus, setDownloadStatus] = useState("");
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  function closePreview() {
    request.current?.abort();
    dialog.current?.close();
    setPreviewUrl(""); setPreviewOpen(false); setBusy(false); setError("");
  }
  async function openDocument(download: boolean) {
    const controller = new AbortController();
    request.current?.abort(); request.current = controller;
    setBusy(true); setError(""); setDownloadStatus("");
    if (!download) { setPreviewOpen(true); dialog.current?.showModal(); }
    try {
      const response = await fetch(`${apiBaseUrl}/api/documents/${encodeURIComponent(citation.document_id!)}?download=${download}`, {
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]),
      });
      if (!response.ok || !response.headers.get("content-type")?.includes("application/pdf")) throw new Error("unavailable");
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      if (download) {
        const link = document.createElement("a");
        link.href = url; link.download = `${citation.title?.trim() || "文献原文"}.pdf`;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        setDownloadStatus("已开始下载");
      } else setPreviewUrl(url);
    } catch {
      if (!controller.signal.aborted) setError("文献原文暂时无法获取，请稍后重试。");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  if (!citation.document_id || !citation.document_available) return <p className="text-muted-foreground">原文暂不可用</p>;
  return <>
    <div className="flex flex-wrap items-center gap-4">
      <button type="button" className="underline disabled:opacity-50" disabled={busy} onClick={() => openDocument(false)}>预览文献</button>
      <button type="button" className="underline disabled:opacity-50" disabled={busy} onClick={() => openDocument(true)}>下载文献</button>
      <span role="status" className="text-muted-foreground">{busy ? "正在获取原文…" : downloadStatus}</span>
    </div>
    {error && !previewOpen && <p role="alert" className="text-destructive">{error}</p>}
    <dialog ref={dialog} aria-label="文献预览" onCancel={closePreview} className="fixed inset-0 m-auto w-[calc(100%-2rem)] max-w-5xl rounded-xl border bg-background p-4 text-foreground shadow-xl backdrop:bg-black/50">
      <div className="mb-3 flex items-start justify-between gap-4">
        <p className="break-words font-medium">{previewOpen ? citation.title?.trim() || "文献标题暂缺" : ""}</p>
        <button type="button" className="shrink-0 underline" onClick={closePreview}>关闭预览</button>
      </div>
      {busy && <p role="status">正在加载文献…</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {previewUrl && <>
        <p className="mb-3 text-muted-foreground">若浏览器无法显示预览，可关闭后下载文献查看。</p>
        <iframe title="文献原文" src={previewUrl} className="h-[70dvh] w-full rounded border" />
      </>}
    </dialog>
  </>;
}
