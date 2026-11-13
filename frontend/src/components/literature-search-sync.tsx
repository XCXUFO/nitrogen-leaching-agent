"use client";

import { useEffect, useState } from "react";
import { apiBaseUrl } from "@/lib/api";

export type SearchSync = { status: string; reason?: string; indexed_at?: string; version?: string; mode?: string };
export const searchStatusLabel = (value?: SearchSync) => ({ not_prepared: "未准备", processing: "同步中", ready: "已就绪", stale: "更新待同步", failed: "同步失败", excluded: "不参与检索" }[value?.status ?? ""] ?? "未采集");

export function LiteratureSearchSync({ token, paperId, value, canSync = true }: { token: string; paperId: string; value?: SearchSync; canSync?: boolean }) {
  const [state, setState] = useState(value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (state?.status !== "processing" || busy) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await fetch(`${apiBaseUrl}/api/literature/papers/${encodeURIComponent(paperId)}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
        if (!response.ok) throw new Error("状态刷新失败，可稍后重新打开资料查看。");
        const paper = await response.json();
        if (!active) return;
        if (paper.search_sync) setState(paper.search_sync);
        if (paper.search_sync?.status === "processing") timer = setTimeout(poll, 2000);
      } catch (problem) { if (active) setError(problem instanceof Error ? problem.message : "状态读取失败。"); }
    }
    timer = setTimeout(poll, 1000);
    return () => { active = false; clearTimeout(timer); };
  }, [paperId, token, state?.status, busy]);
  async function sync() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/literature/papers/${encodeURIComponent(paperId)}/search-sync`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail?.message ?? "同步失败，请重试。");
      setState(data);
    } catch (problem) { setError(problem instanceof Error ? problem.message : "同步失败，请重试。"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-xl border bg-white p-5" aria-label="全文检索同步">
    <h3 className="font-semibold">全文检索状态 · {busy ? "同步中" : searchStatusLabel(state)}</h3>
    <p className="text-sm text-slate-600">{state?.reason || "保存后自动同步正文，也可立即同步或重试。"}</p>
    <p className="text-sm text-slate-600">{state?.status === "ready" ? "正文已同步，可供问答检索。" : state?.status === "excluded" ? "这篇文献当前不参与问答。" : "保存的资料会自动同步；同步完成后可供问答检索。"}</p>
    <details className="text-xs text-slate-500"><summary className="cursor-pointer">同步详情</summary>
      {state?.indexed_at && <p className="mt-2 break-all">最近同步：{state.indexed_at} · {state.mode === "vector_and_text" || state.mode === "legacy_vector_and_text" ? "正文与向量索引" : "正文文本索引"}<br />内容版本：{state.version ?? "未知"}</p>}
      <p className="mt-2 leading-5">已保存且启用的 PDF 会自动同步正文，题录草稿也可参与检索。停用或删除会立即排除新检索证据。扫描件无可读正文时需要补充可检索的原文。</p>
    </details>
    {canSync && <button type="button" disabled={busy || state?.status === "excluded"} onClick={() => void sync()} className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50">{busy ? "正在同步…" : state?.status === "failed" ? "重试同步" : "同步全文索引"}</button>}
    {error && <p role="alert" className="text-sm text-amber-900">{error}</p>}
  </section>;
}
