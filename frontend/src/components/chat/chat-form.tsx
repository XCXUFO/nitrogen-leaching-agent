"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { Paperclip, Send, X, FileSpreadsheet, FileText } from "lucide-react";
import type { SessionFile } from "@/lib/types";

interface Props {
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: (query: string) => void;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
  files: SessionFile[];
  onRemoveFile: (id: string) => void;
}

export function ChatForm({ value, onValueChange: setValue, onSubmit, disabled, onFiles, files, onRemoveFile }: Props) {
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const question = useRef<HTMLTextAreaElement>(null);
  const dragDepth = useRef(0);
  const canSubmit = !disabled && value.trim().length > 0 && value.length <= 24000;
  useLayoutEffect(() => {
    const textarea = question.current;
    if (!textarea) return;
    const resize = () => {
      textarea.style.height = "24px";
      const height = textarea.value ? Math.min(textarea.scrollHeight, 160) : 24;
      textarea.style.height = `${height}px`;
      textarea.style.overflowY = textarea.scrollHeight > 160 ? "auto" : "hidden";
    };
    resize();
    let width = textarea.clientWidth;
    const observer = new ResizeObserver(() => {
      if (textarea.clientWidth === width) return;
      width = textarea.clientWidth;
      resize();
    });
    observer.observe(textarea);
    return () => observer.disconnect();
  }, [value]);
  function submit() { if (canSubmit) { onSubmit(value.trim()); setValue(""); } }
  function select(list: FileList | null) {
    if (disabled || !list?.length) return;
    onFiles(Array.from(list));
  }
  return <form aria-label="聊天输入区" className={`space-y-3 rounded-2xl border bg-background p-3 shadow-sm transition sm:p-4 ${dragging ? "border-emerald-500 ring-2 ring-emerald-200" : "border-input"}`}
    onSubmit={(event) => { event.preventDefault(); submit(); }}
    onDragEnter={(event) => { event.preventDefault(); if (event.dataTransfer.types.includes("Files")) { dragDepth.current++; if (!disabled) setDragging(true); } }}
    onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = disabled ? "none" : "copy"; }}
    onDragLeave={(event) => { event.preventDefault(); dragDepth.current--; if (dragDepth.current <= 0) setDragging(false); }}
    onDrop={(event) => { event.preventDefault(); dragDepth.current = 0; setDragging(false); select(event.dataTransfer.files); }}>
    {files.length > 0 && <div className="flex max-w-full gap-2 overflow-x-auto pb-1" aria-label="会话文件列表">{files.map((file) => {
        const ready = file.phase === "stored" && !!file.receipt;
        const removeLabel = file.used ? `收起文件：${file.filename}（仍可在本会话引用）` : `移除附件：${file.filename}`;
        const Icon = /\.xlsx?$/i.test(file.filename) ? FileSpreadsheet : FileText;
        return <div key={file.clientId} className={`flex w-44 shrink-0 items-start gap-2 rounded-xl border p-2 text-xs ${file.phase === "error" ? "border-destructive/50 bg-destructive/5" : "bg-muted/20"}`}>
          <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <p className="break-all font-medium">{file.filename}</p>
            {ready && <p className="text-emerald-700">已上传</p>}
            {file.phase === "uploading" && <div role="status"><p>正在上传附件 {file.progress}%</p><progress max={100} value={file.progress} aria-label={`${file.filename} 上传进度`} className="h-1.5 w-full accent-emerald-600" /></div>}
            {file.phase === "error" && <p role="alert" className="text-destructive">{file.error}</p>}
          </div>
          <button type="button" title={removeLabel} aria-label={removeLabel} disabled={disabled} onClick={() => onRemoveFile(file.clientId)} className="rounded p-1 hover:bg-muted disabled:opacity-40"><X className="size-4" /></button>
        </div>;
      })}</div>}
    <textarea ref={question} rows={1} aria-label="问题输入" disabled={disabled} value={value} onChange={(event) => setValue(event.target.value)}
      onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); } }}
      placeholder={dragging ? "松开上传文件" : "输入问题，或拖入文件…"}
      className="block max-h-40 min-h-6 w-full resize-none border-0 bg-transparent text-sm leading-6 outline-none disabled:opacity-50" />
    <div className="flex items-center justify-between gap-2">
      <div className="flex shrink-0 items-center gap-2"><input ref={input} type="file" multiple accept=".xls,.xlsx,.txt,.md,.pdf,.doc,.docx" aria-label="选择会话文件" className="sr-only" tabIndex={-1} disabled={disabled} onChange={(event) => { select(event.target.files); event.target.value = ""; }} />
        <button type="button" disabled={disabled} className="flex items-center gap-1 rounded-lg border px-2 py-2 text-xs hover:bg-muted disabled:opacity-40 sm:px-3" onClick={() => input.current?.click()}><Paperclip className="size-4" />附加文件</button>
        <span className={`text-xs ${value.length > 24000 ? "text-destructive" : "text-muted-foreground"}`}>{value.length}/24000</span>
      </div>
      <div className="flex min-w-0 items-center justify-end gap-2">
        <span className="whitespace-nowrap text-[10px] text-muted-foreground sm:text-[11px]"><span className="hidden sm:inline">Enter 换行 · Ctrl / ⌘ + Enter 发送</span><span className="sm:hidden">Ctrl/⌘+↵</span></span>
        <button type="submit" disabled={!canSubmit} className="flex shrink-0 items-center gap-1 rounded-xl bg-emerald-800 px-3 py-2 text-sm text-white hover:bg-emerald-900 disabled:opacity-40 sm:gap-2 sm:px-4"><Send className="size-4" />发送</button>
      </div>
    </div>
  </form>;
}
