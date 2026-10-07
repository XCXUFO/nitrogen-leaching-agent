"use client";

import { useCallback, useEffect, useState } from "react";
import { evaluationJson, evaluationRequest as request } from "@/lib/evaluation-api";
import type { EvaluationExecution } from "@/lib/evaluation-api";
import { MarkdownAnswer } from "@/components/chat/markdown-answer";

type Replay = { replay_id: string; state: string; completed_steps: number; total_steps: number; message: string; created_at: string; execution_id: string | null; blocked_step?: { step: number; action: string; message: string } };
type Regression = { regression_id: string; title: string; case_id: string; case_version: number; baseline_versions: string[]; replays: Replay[] };
type Snapshot = { input: string; answer: string | null; route: string | null; outcome: string | null; error: { code: string } | null; config_version: string | null; model: string | null; latency_ms: number | null; file_evidence: unknown[]; citations: unknown[]; tools: unknown[]; trace_saved: boolean };
type Comparison = { title: string; case_id: string; case_version: number; replay: Replay; changed_turns: number; baseline_review: unknown; candidate_review: unknown; notes: string[]; pairs: { turn: number; baseline: Snapshot | null; candidate: Snapshot | null; changes: string[]; latency_delta_ms: number | null }[] };
const button = "rounded-lg border px-3 py-2 text-xs hover:bg-muted disabled:opacity-40";
const states: Record<string, string> = { queued: "排队", running: "重跑中", completed: "重跑结束", blocked: "受阻", failed: "中断", cancelled: "已取消", interrupted: "重启中断" };
const fields: Record<string, string> = { input: "问题", route: "路由", outcome: "完成情况", error: "错误", tools: "工具", file_evidence: "文件事实", citations: "引用", answer: "回答文字", model: "模型", config_version: "构建/配置" };
export function EvaluationRegressions({ token, execution, onOpenExecution }: { token: string; execution: EvaluationExecution | null; onOpenExecution: (id: string) => void }) {
  const [items, setItems] = useState<Regression[]>([]);
  const [offset, setOffset] = useState(0);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [comparisonLayout, setComparisonLayout] = useState<"stacked" | "columns">("stacked");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(() => request<Regression[]>(token, `/regressions?offset=${offset}`), [token, offset]);
  useEffect(() => {
    let cancelled = false;
    load().then((values) => { if (!cancelled) setItems(values); }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [load]);
  const running = items.some((i) => i.replays.some((r) => ["queued", "running"].includes(r.state)));
  useEffect(() => {
    if (!running) return;
    let cancelled = false; let inFlight = false;
    const timer = setInterval(async () => {
      if (inFlight) return; inFlight = true;
      try { const values = await load(); if (!cancelled) setItems(values); }
      catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : "状态读取失败"); }
      finally { inFlight = false; }
    }, 2500);
    return () => { cancelled = true; clearInterval(timer); };
  }, [running, load]);
  async function act(task: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await task(); setItems(await load()); }
    catch (e) { setError(e instanceof Error ? e.message : "操作失败"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-4 rounded-xl border p-4 sm:p-5">
    <h2 className="text-xl font-semibold">回归与版本比较</h2>
    <p className="text-sm text-muted-foreground">保存旧执行为基线，用当前代码按原顺序重跑；数值、引用和回答差异分别展示。重跑会实际调用工具，知识问题会使用当前模型服务。</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm text-emerald-700">{notice}</p>}
    <fieldset disabled={busy} className="min-w-0 space-y-4">
      <form className="space-y-2 rounded-lg bg-muted/30 p-3" onSubmit={(e) => { e.preventDefault(); if (!execution) return; void act(async () => {
        await request(token, "/regressions", evaluationJson({ execution_id: execution.execution_id, title: title.trim(), notes }));
        setTitle(""); setNotes(""); setNotice("已保存独立基线快照，原执行和评分保持不变。");
      }); }}>
        <p className="text-sm">{execution ? `当前执行：${execution.case_id} v${execution.case_version} · ${execution.execution_id}` : "在上方选择关联执行，或从执行详情进入，再保存回归基线。"}</p>
        <input required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} aria-label="回归基线标题" placeholder="回归标题，例如：玉米极值解释引用不充分" className="w-full rounded border bg-background px-3 py-2 text-sm" />
        <textarea maxLength={3000} value={notes} onChange={(e) => setNotes(e.target.value)} aria-label="回归说明" placeholder="记录问题现象和需要观察的变化，不必先给专业结论" rows={2} className="w-full rounded border bg-background px-3 py-2 text-sm" />
        <button className={button} disabled={!execution || !title.trim() || execution.automation_running}>保存为回归基线</button>
      </form>
      <div className="flex flex-wrap items-center gap-2"><button type="button" className={button} onClick={() => void act(async () => {})}>刷新回归列表</button><span className="text-xs text-muted-foreground">缺原附件、附件指纹变化或人工步骤无法复现时会停止，不自动跳过。</span></div>
      {!items.length && <p className="text-sm text-muted-foreground">还没有回归基线。不会自动创建或填入专业评分。</p>}
      {items.map((item) => <article className="space-y-3 rounded-lg border p-4" key={item.regression_id}>
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">{item.title} <span className="text-xs text-muted-foreground">{item.case_id} v{item.case_version}</span></h3><button type="button" className={button} disabled={item.replays.some((r) => ["queued", "running"].includes(r.state))} onClick={() => void act(async () => {
          const job = await request<Replay>(token, `/regressions/${item.regression_id}/replays`, { method: "POST" });
          setNotice(job.state === "blocked" ? job.message : "重跑已启动，可等待状态更新或取消。");
        })}>用当前版本重跑</button></div>
        <p className="break-all text-xs text-muted-foreground">基线构建：{item.baseline_versions.join("；") || "无已保存 Trace"}</p>
        {item.replays.map((job) => <div key={job.replay_id} className="space-y-2 border-t pt-3 text-sm"><p>{states[job.state] ?? job.state} · {job.completed_steps}/{job.total_steps} 步 · {new Date(job.created_at).toLocaleString()}</p><p className="text-xs text-muted-foreground">{job.message}</p>{job.blocked_step && <p role="status" className="rounded bg-amber-50 px-3 py-2 text-xs text-amber-950">第 {job.blocked_step.step} 步待人工：{job.blocked_step.message}。此前已完成的 Run 保存在新执行中。</p>}<div className="flex flex-wrap gap-2">
          {["queued", "running"].includes(job.state) ? <button type="button" className={button} onClick={() => void act(async () => { await request(token, `/replays/${job.replay_id}/cancel`, { method: "POST" }); setNotice("已请求取消。"); })}>取消重跑</button> : <button type="button" className={button} onClick={() => void act(async () => { setComparison(await request<Comparison>(token, `/replays/${job.replay_id}/comparison`)); })}>比较结果</button>}
          {job.execution_id && !["queued", "running"].includes(job.state) && <button type="button" className={button} onClick={() => onOpenExecution(job.execution_id!)}>打开新执行 / 人工评分</button>}
        </div></div>)}
      </article>)}
      <div className="flex gap-2"><button className={button} type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页</button><button className={button} type="button" disabled={items.length < 50} onClick={() => setOffset(offset + 50)}>下一页</button></div>
    </fieldset>
    {comparison && <section className="space-y-4 border-t pt-5" aria-label="版本比较结果">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{comparison.title} · 差异对照</h3><div className="flex gap-2"><button type="button" aria-pressed={comparisonLayout === "stacked"} className={button} onClick={() => setComparisonLayout("stacked")}>上下对比</button><button type="button" aria-pressed={comparisonLayout === "columns"} className={button} onClick={() => setComparisonLayout("columns")}>并排对比</button><button type="button" className={button} onClick={() => setComparison(null)}>收起比较</button></div></div>
      <p className="text-sm">{comparison.changed_turns} 轮存在内容或配置变化。{states[comparison.replay.state]}，{comparison.replay.completed_steps}/{comparison.replay.total_steps} 步。</p>
      {comparison.replay.blocked_step && <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-950">第 {comparison.replay.blocked_step.step} 步待人工：{comparison.replay.blocked_step.message}</p>}
      <ul className="list-disc pl-5 text-xs leading-6 text-muted-foreground">{comparison.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      {comparison.pairs.map((pair) => <article key={pair.turn} className="space-y-3 rounded-lg border p-3">
        <h4 className="font-medium">第 {pair.turn} 轮：{pair.baseline?.input ?? pair.candidate?.input}</h4>
        <p className="text-xs">变化：{pair.changes.map((k) => fields[k]).join("、") || "未发现内容/配置变化"} · 耗时差：{pair.latency_delta_ms === null ? "不可比较" : `${pair.latency_delta_ms > 0 ? "+" : ""}${pair.latency_delta_ms} ms`}</p>
        <div className={`grid gap-4 ${comparisonLayout === "columns" ? "xl:grid-cols-2" : "grid-cols-1"}`}>{([pair.baseline, pair.candidate] as const).map((snapshot, i) => <div key={i} className="min-w-0 space-y-2 rounded-lg bg-muted/20 p-3">
          <h5 className="text-sm font-semibold">{i === 0 ? "冻结基线" : "当前重跑"}</h5>{snapshot ? <><p className="break-all text-xs text-muted-foreground">{snapshot.config_version ?? "无构建记录"}</p><p className="text-xs">{snapshot.route ?? "未路由"} · {snapshot.outcome ?? snapshot.error?.code ?? "无结果"} · {snapshot.latency_ms ?? "—"} ms</p>
            <div className="max-h-96 overflow-auto text-sm"><MarkdownAnswer content={snapshot.answer ?? "本轮没有生成答案。"} /></div>
            {([['file_evidence', '文件数值与单元格'], ['citations', '引用与原文'], ['tools', '工具执行'], ['error', '错误']] as const).map(([key, label]) => <details key={key}><summary className="cursor-pointer text-xs">{label}</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(snapshot[key], null, 2)}</pre></details>)}
          </> : <p className="text-sm">本轮尚未执行或缺失，不能作为通过结果。</p>}
        </div>)}</div>
      </article>)}
      <details><summary className="cursor-pointer text-sm">查看已有人工作业评分</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ baseline: comparison.baseline_review, candidate: comparison.candidate_review }, null, 2)}</pre><p className="text-xs text-muted-foreground">null 表示尚未评分。系统不会自动填充专业结论。</p></details>
    </section>}
  </section>;
}
