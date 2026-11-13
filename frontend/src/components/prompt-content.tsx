"use client";

import { useState } from "react";
import { MarkdownAnswer } from "./chat/markdown-answer";
import { promptButton as button, promptField as field } from "@/lib/prompt-types";

export function PromptContent({ label, value, readOnly = false, onChange }: { label: string; value: string; readOnly?: boolean; onChange?: (text: string) => void }) {
  const [preview, setPreview] = useState(true);
  return <div className="space-y-2">
    <div className="flex items-center justify-between gap-2"><p className="text-xs">Prompt 内容</p><div role="group" aria-label={`${label} 展示方式`} className="flex gap-1"><button type="button" className={button} aria-pressed={preview} onClick={() => setPreview(true)}>Markdown</button><button type="button" className={button} aria-pressed={!preview} onClick={() => setPreview(false)}>{readOnly ? "原文" : "编辑"}</button></div></div>
    {preview ? <div role="region" aria-label={`${label} Markdown 预览`} className="max-h-96 min-h-36 overflow-auto rounded-lg border bg-slate-50 p-3 text-sm leading-6"><MarkdownAnswer content={value || "暂无内容"} /></div> : <textarea aria-label={label} readOnly={readOnly} className={`${field} min-h-64 resize-y font-mono leading-6`} maxLength={24000} value={value} onChange={e => onChange?.(e.target.value)} />}
  </div>;
}
