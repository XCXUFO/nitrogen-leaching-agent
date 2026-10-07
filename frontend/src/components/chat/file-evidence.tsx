import type { FileEvidence } from "@/lib/types";

export function FileEvidenceList({ evidence }: { evidence: FileEvidence[] }) {
  if (!evidence.length) return null;
  return (
    <details className="bg-muted/40 rounded border px-4 py-2 text-xs">
      <summary className="cursor-pointer">文件依据</summary>
      <ul className="mt-2 space-y-3">
        {evidence.map((item, index) => (
          <li key={`${item.sha256}-${item.field}-${item.operation}-${index}`} className="space-y-1 break-words">
            <p>{item.filename} · {item.field}</p>
            <p>{item.operation === "max" ? "最大值" : "最小值"}：{item.value} {item.unit} · {item.cell}</p>
            <p>模型日序：{item.model_day} · {item.day_cell}</p>
            <p>计算范围：{item.data_range}；并列 {item.occurrences} 条，展示首次出现。</p>
            <details className="text-muted-foreground">
              <summary className="cursor-pointer">复核信息</summary>
              <p className="break-all">SHA-256：{item.sha256}</p>
              <p>读取器 {item.tool_version} · 规则 {item.schema_id}</p>
            </details>
          </li>
        ))}
      </ul>
    </details>
  );
}
