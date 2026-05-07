import type { Citation } from "@/lib/types";

const SNIPPET_LIMIT = 100;

interface Props {
  citations: Citation[];
  retrievedCount: number;
}

export function CitationList({ citations, retrievedCount }: Props) {
  if (citations.length === 0) {
    return (
      <p className="text-muted-foreground text-xs">
        本次回答未召回知识库资料（retrieved_count = {retrievedCount}）
      </p>
    );
  }

  return (
    <details className="bg-muted/40 rounded border px-4 py-2 text-xs">
      <summary className="text-muted-foreground cursor-pointer">
        引用来源（{citations.length}）
      </summary>
      <ol className="mt-2 space-y-2">
        {citations.map((c) => {
          const truncated = c.snippet.length >= SNIPPET_LIMIT;
          const snippet = truncated
            ? c.snippet.slice(0, SNIPPET_LIMIT)
            : c.snippet;
          return (
            <li key={c.chunk_id} className="space-y-0.5">
              <div className="text-muted-foreground font-mono text-[11px]">
                [{c.index}] {basename(c.source)} · score {c.score.toFixed(3)}
              </div>
              <p className="text-foreground">
                {snippet}
                {truncated ? "…" : ""}
              </p>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

function basename(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}
