"use client";

import { useRef, useState } from "react";
import { Paperclip, Send, X, FileSpreadsheet } from "lucide-react";
import type { SessionFile } from "@/lib/types";

interface Props {
  onSubmit: (query: string) => void;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
  files: SessionFile[];
  onRemoveFile: (id: string) => void;
}

export function ChatForm({ onSubmit, disabled, onFiles, files, onRemoveFile }: Props) {
  const [value, setValue] = useState("");
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const canSubmit = !disabled && value.trim().length > 0 && value.length <= 1000;
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
    {files.length > 0 && <div className="space-y-2" aria-label="会话文件列表">
      <p className="text-xs text-muted-foreground">会话文件 · 自动查找相关内容</p>
      <div className="max-h-48 space-y-2 overflow-y-auto">{files.map((file) => {
        const ready = file.phase === "stored" && !!file.receipt;
        const removeLabel = file.used ? `收起文件：${file.filename}（仍可在本会话引用）` : `移除附件：${file.filename}`;
        return <div key={file.clientId} className="flex items-start gap-2 rounded-xl border bg-muted/20 p-2 text-xs">
          <FileSpreadsheet aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <p className="break-all font-medium">{file.used ? `本会话可引用：${file.filename}` : file.filename}</p>
            {ready && <p className="text-muted-foreground">{file.receipt?.sha256.slice(0, 8)} · {file.used ? "本会话可继续引用" : "已上传 · 提问时自动分析"}</p>}
            {file.phase === "uploading" && <div role="status"><p>正在上传附件 {file.progress}%</p><progress max={100} value={file.progress} aria-label={`${file.filename} 上传进度`} className="h-1.5 w-full accent-emerald-600" /></div>}
            {file.phase === "error" && <p role="alert" className="text-destructive">{file.error}</p>}
          </div>
          <button type="button" title={removeLabel} aria-label={removeLabel} disabled={disabled} onClick={() => onRemoveFile(file.clientId)} className="rounded p-1 hover:bg-muted disabled:opacity-40"><X className="size-4" /></button>
        </div>;
      })}</div>
    </div>}
    <textarea rows={3} aria-label="问题输入" disabled={disabled} value={value} onChange={(event) => setValue(event.target.value)}
      onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); } }}
      placeholder={dragging ? "松开鼠标上传结果表" : "提出农业模型问题，或拖入 WHCNS 结果表…"}
      className="max-h-40 min-h-20 w-full resize-y border-0 bg-transparent text-sm leading-6 outline-none disabled:opacity-50" />
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-3"><input ref={input} type="file" multiple accept=".xls,.xlsx" aria-label="附加结果表" className="sr-only" tabIndex={-1} disabled={disabled} onChange={(event) => { select(event.target.files); event.target.value = ""; }} />
        <button type="button" disabled={disabled} className="flex items-center gap-1 rounded-lg border px-3 py-2 text-xs hover:bg-muted disabled:opacity-40" onClick={() => input.current?.click()}><Paperclip className="size-4" />附加文件</button>
        <span className={`text-xs ${value.length > 1000 ? "text-destructive" : "text-muted-foreground"}`}>{value.length}/1000</span>
      </div>
      <button type="submit" disabled={!canSubmit} className="flex items-center gap-2 rounded-xl bg-emerald-800 px-4 py-2 text-sm text-white hover:bg-emerald-900 disabled:opacity-40"><Send className="size-4" />发送</button>
    </div>
    <div className="flex flex-wrap justify-between gap-1 text-[11px] text-muted-foreground"><span>Enter 换行 · Ctrl / ⌘ + Enter 发送</span></div>
  </form>;
}
