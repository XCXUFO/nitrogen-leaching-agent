"use client";

import { Children, isValidElement, useMemo, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Node = { type: string; value?: string; url?: string; children?: Node[] };
function textOf(value: ReactNode): string {
  return Children.toArray(value).map((item) => typeof item === "string" || typeof item === "number" ? String(item)
    : isValidElement<{ children?: ReactNode }>(item) ? textOf(item.props.children) : "").join("");
}
function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState("");
  return <div className="my-3 overflow-hidden rounded-lg border bg-slate-950 text-slate-100">
    <div className="flex justify-end border-b border-white/10 px-3 py-1"><button type="button" className="text-xs" onClick={async () => {
      try { await navigator.clipboard.writeText(textOf(children).replace(/\n$/, "")); setCopied("已复制"); }
      catch { setCopied("复制失败，请手动选择"); }
    }}>{copied || "复制代码"}</button></div><pre className="overflow-x-auto p-4 text-xs leading-relaxed">{children}</pre>
  </div>;
}
export function MarkdownAnswer({ content, indices = [], onCitation }: { content: string; indices?: number[]; onCitation?: (index: number) => void }) {
  const citationPlugin = useMemo(() => function citations() {
    const allowed = new Set(indices);
    return (root: unknown) => {
      function walk(node: Node) {
        if (["code", "inlineCode", "link", "linkReference", "image", "html"].includes(node.type) || !node.children) return;
        node.children = node.children.flatMap((child): Node[] => {
          if (child.type !== "text" || !child.value) { walk(child); return [child]; }
          const pieces: Node[] = []; let previous = 0;
          for (const match of child.value.matchAll(/\[(\d{1,3})\]/g)) {
            if (!allowed.has(Number(match[1]))) continue;
            pieces.push({ type: "text", value: child.value.slice(previous, match.index) },
              { type: "link", url: `#evidence-${match[1]}`, children: [{ type: "text", value: match[0] }] });
            previous = match.index! + match[0].length;
          }
          return pieces.length ? [...pieces, { type: "text", value: child.value.slice(previous) }] : [child];
        });
      }
      walk(root as Node);
    };
  }, [indices]);
  return <div className="markdown-answer min-w-0 break-words">
    <Markdown remarkPlugins={[remarkGfm, citationPlugin]} skipHtml disallowedElements={["img"]} components={{
      a({ href, children }) {
        const index = /^#evidence-(\d+)$/.exec(href ?? "")?.[1];
        if (index && indices.includes(Number(index)) && onCitation) return <button type="button" className="citation-mark" aria-label={`查看引用 ${index}`} onClick={() => onCitation(Number(index))}>{children}</button>;
        return /^https?:\/\//i.test(href ?? "") ? <a href={href} target="_blank" rel="noopener noreferrer" className="underline">{children}</a> : <span>{children}</span>;
      },
      pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
      table: ({ children }) => <div className="my-3 max-w-full overflow-x-auto"><table>{children}</table></div>,
    }}>{content}</Markdown>
  </div>;
}
