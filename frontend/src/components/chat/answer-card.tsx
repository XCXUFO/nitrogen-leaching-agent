"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatResponse } from "@/lib/types";
import { CitationList, groupCitations } from "./citation-list";
import { FileEvidenceList } from "./file-evidence";
import { MarkdownAnswer } from "./markdown-answer";

export function AnswerCard({ response, scope }: { response: ChatResponse; scope: string }) {
  const [active, setActive] = useState<number | null>(null);
  const [copyStatus, setCopyStatus] = useState("");
  const [copying, setCopying] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const answer = useRef<HTMLDivElement>(null);
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
    <div className="flex flex-wrap items-center justify-between gap-3"><span className="text-sm font-semibold">农业模型助手</span><div className="flex items-center gap-2"><button type="button" aria-live="polite" disabled={copying} className="shrink-0 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50" onClick={async () => {
      setCopying(true);
      if (copyTimer.current) clearTimeout(copyTimer.current);
      try {
        await navigator.clipboard.writeText(response.answer);
        setCopyStatus("已复制");
      } catch { setCopyStatus("复制失败，请手动选择复制"); }
      setCopying(false);
      copyTimer.current = setTimeout(() => setCopyStatus(""), 1000);
    }}>{copying ? "正在复制…" : copyStatus || "复制回答"}</button></div></div>
    {response.outcome === "partial" && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">部分完成：已保留可用结果，尚未完成的部分见说明。</p>}
    <div ref={answer} tabIndex={-1} className="outline-none text-sm leading-7"><MarkdownAnswer content={response.answer.replace(/^(表中观察|为何目前不能归因|文献中的事件尺度线索|下一步核查|文献支持的可能机制|适用边界与下一步)$/gm, "### $1")} indices={response.citations.map((c) => c.index)} onCitation={showCitation} /></div>
    <CitationList citations={response.citations} scope={scope} activeIndex={active} onBack={() => { answer.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); answer.current?.focus({ preventScroll: true }); }} />
    <FileEvidenceList evidence={response.file_evidence ?? []} />
  </article>;
}
