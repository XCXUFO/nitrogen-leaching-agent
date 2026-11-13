"use client";

import { useEffect, useRef, useState } from "react";
import { RotateCw } from "lucide-react";
import type { ChatResponse } from "@/lib/types";
import { CitationList, groupCitations } from "./citation-list";
import { FileEvidenceList } from "./file-evidence";
import { MarkdownAnswer } from "./markdown-answer";
import { submitAnswerFeedback } from '@/lib/api';

export function AnswerCard({ response, scope, onRegenerate, regenerateDisabled, regenerating, regenerateHint }: {
  response: ChatResponse; scope: string; onRegenerate?: () => void;
  regenerateDisabled?: boolean; regenerating?: boolean; regenerateHint?: string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const [copyStatus, setCopyStatus] = useState("");
  const [copying, setCopying] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackMessage, setFeedbackMessage] = useState('');
  const feedbackId = useRef('');
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (copyTimer.current) clearTimeout(copyTimer.current); }, []);
  function showCitation(index: number) {
    setActive(index);
    const documentIndex = groupCitations(response.citations).find((group) => group.indices.includes(index))?.citation.index;
    const target = document.getElementById(`${scope}-citation-${documentIndex}`);
    if (!target) return;
    let parent = target.parentElement;
    while (parent) { if (parent instanceof HTMLDetailsElement) parent.open = true; parent = parent.parentElement; }
    target.scrollIntoView({ behavior: "smooth", block: "nearest" }); target.focus({ preventScroll: true });
  }
  return <article className="space-y-3 rounded-2xl border bg-background p-4 shadow-sm sm:p-6">
    <div className="flex flex-wrap items-center justify-end gap-3">
      {response.run_id && <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setFeedbackOpen(!feedbackOpen)}>反馈问题</button>}
      {onRegenerate && <button type="button" onClick={onRegenerate}
        disabled={regenerateDisabled || regenerating} title={regenerateHint} aria-busy={regenerating || undefined}
        className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-emerald-700 disabled:cursor-not-allowed disabled:opacity-50">
        <RotateCw aria-hidden="true" className={`size-3 ${regenerating ? "animate-spin" : ""}`} />
        {regenerating ? "正在重新回答…" : "重新回答"}
      </button>}
      <button type="button" aria-live="polite" disabled={copying} className="shrink-0 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50" onClick={async () => {
      setCopying(true);
      if (copyTimer.current) clearTimeout(copyTimer.current);
      try {
        await navigator.clipboard.writeText(response.answer);
        setCopyStatus("已复制");
      } catch { setCopyStatus("复制失败，请手动选择复制"); }
      setCopying(false);
      copyTimer.current = setTimeout(() => setCopyStatus(""), 1000);
    }}>{copying ? "正在复制…" : copyStatus || "复制回答"}</button></div>
    {response.outcome === "partial" && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">部分完成：已保留可用结果，尚未完成的部分见说明。</p>}
    {feedbackOpen && <form className="space-y-2 rounded-lg border bg-slate-50 p-3" onSubmit={async (event) => {
      event.preventDefault(); if (!response.run_id) return; setFeedbackBusy(true); setFeedbackMessage('');
      if (!feedbackId.current) feedbackId.current = crypto.randomUUID();
      try { await submitAnswerFeedback(response.run_id, feedback, feedbackId.current); setFeedbackOpen(false); setFeedbackMessage('问题已提交，会连同原会话交给团队处理。'); }
      catch (error) { setFeedbackMessage(error instanceof Error ? error.message : '提交失败，请重试。'); }
      finally { setFeedbackBusy(false); }
    }}><label className="block text-sm">哪里有问题，希望怎么改<textarea className="mt-2 w-full rounded-lg border bg-white p-2" maxLength={5000} required rows={3} value={feedback} onChange={(e) => { setFeedback(e.target.value); feedbackId.current = ''; }} /></label><button disabled={feedbackBusy || !feedback.trim()} className="rounded-lg border bg-white px-3 py-2 text-sm disabled:opacity-50">提交反馈</button></form>}
    {feedbackMessage && <p role="status" className="text-xs text-slate-600">{feedbackMessage}</p>}
    <div className="text-sm leading-7"><MarkdownAnswer content={response.answer.replace(/^(表中观察|为何目前不能归因|文献中的事件尺度线索|下一步核查|文献支持的可能机制|适用边界与下一步)$/gm, "### $1")} indices={response.citations.map((c) => c.index)} onCitation={showCitation} /></div>
    <CitationList citations={response.citations} scope={scope} activeIndex={active} />
    {!!response.case_references?.length && <div className="space-y-2 rounded-lg border p-3 text-sm"><h3 className="font-medium">参考案例</h3>{response.case_references.map((item) => <div key={item.id}><p>{item.title}</p>{item.source && <p className="whitespace-pre-wrap break-words text-xs text-muted-foreground">来源：{item.source}</p>}</div>)}</div>}
    <FileEvidenceList evidence={response.file_evidence ?? []} />
    {onRegenerate && regenerateHint && <p className="text-xs text-muted-foreground">{regenerateHint}</p>}
  </article>;
}
