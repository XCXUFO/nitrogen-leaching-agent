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
    }
    else groups.set(key, { citation, indices: [citation.index] });
  }
  return [...groups.values()];
}

export function CitationList({ citations, scope = "sources", activeIndex }: {
  citations: Citation[]; scope?: string; activeIndex?: number | null;
}) {
  const documents = groupCitations(citations);
  if (!documents.length) return null;
  const hasSessionFile = documents.some(({ citation }) => citation.source.startsWith("session://") || citation.source_type === "web");
  const heading = hasSessionFile ? "参考依据" : "文献依据";
  return <details className="rounded-lg border bg-muted/10 px-3 py-2 text-xs">
    <summary className="cursor-pointer text-xs leading-5 font-normal text-muted-foreground">{heading} · {documents.length} {hasSessionFile ? "份" : "篇"}</summary>
    <ul className="mt-3 space-y-3">{documents.map(({ citation: c, indices }) => (
      <li id={`${scope}-citation-${c.index}`} tabIndex={-1} key={c.index} className={`scroll-mt-24 space-y-2 rounded-lg border p-3 outline-none focus:ring-2 focus:ring-ring ${activeIndex != null && indices.includes(activeIndex) ? "border-emerald-500 bg-emerald-50/40" : "bg-background"}`}>
        <p className="break-words font-medium">{indices.map((index) => `[${index}]`).join(" ")} {c.title?.trim() || "文献标题暂缺"}</p>
        {c.source_type === "web" && <p className="text-muted-foreground">网页依据 · {c.publisher || "来源机构未记录"} · {c.evidence_level === "page_text" ? "已读取页面文本" : "搜索摘要"}</p>}
        {c.source_type !== "web" && !c.source.startsWith("session://") && <p className="break-words text-muted-foreground">作者：{c.author_hint?.trim() || "暂缺"} · 年份：{c.year?.trim() || "暂缺"}</p>}
        {c.source_type === "web" && <><p className="whitespace-pre-wrap break-words text-muted-foreground">{c.snippet}</p>{c.retrieved_at && <p className="text-muted-foreground">获取时间：{c.retrieved_at}</p>}</>}
        <DocumentActions citation={c} />
      </li>
    ))}</ul>
  </details>;
}
