import type { Citation } from "@/lib/types";
import { DocumentActions } from "./document-actions";

// Preserve every original citation anchor while presenting one entry per paper.
export function groupCitations(citations: Citation[]) {
  const groups = new Map<string, { citation: Citation; indices: number[] }>();
  for (const citation of citations) {
    const key = citation.document_id || citation.source.replaceAll("\\", "/") || `citation-${citation.index}`;
    const existing = groups.get(key);
    if (existing) {
      existing.indices.push(citation.index);
      if (citation.snippet && !existing.citation.snippet.includes(citation.snippet)) existing.citation.snippet += "\n…\n" + citation.snippet;
    }
    else groups.set(key, { citation: { ...citation }, indices: [citation.index] });
  }
  return [...groups.values()];
}

export function CitationList({ citations, scope = "sources", activeIndex, onBack }: {
  citations: Citation[]; scope?: string; activeIndex?: number | null; onBack?: () => void;
}) {
  const documents = groupCitations(citations);
  if (!documents.length) return null;
  return <details className="rounded-xl border bg-muted/20 px-4 py-3 text-xs">
    <summary className="cursor-pointer font-medium">文献依据 · {documents.length} 篇</summary>
    <ul className="mt-3 space-y-3">{documents.map(({ citation: c, indices }) => (
      <li id={`${scope}-citation-${c.index}`} tabIndex={-1} key={c.index} className={`scroll-mt-24 space-y-2 rounded-lg border p-3 outline-none focus:ring-2 focus:ring-ring ${activeIndex != null && indices.includes(activeIndex) ? "border-emerald-500 bg-emerald-50/40" : "bg-background"}`}>
        <p className="break-words font-medium">{indices.map((index) => `[${index}]`).join(" ")} {c.title?.trim() || "文献标题暂缺"}</p>
        <p className="break-words text-muted-foreground">作者：{c.author_hint?.trim() || "暂缺"} · 年份：{c.year?.trim() || "暂缺"}</p>
        <blockquote className="whitespace-pre-wrap break-words border-l-2 border-emerald-200 pl-3 leading-6 text-muted-foreground">{c.snippet}</blockquote>
        <DocumentActions citation={c} />
        {onBack && <button type="button" className="underline" onClick={onBack}>返回回答</button>}
      </li>
    ))}</ul>
  </details>;
}
