"use client";

import { useCallback, useEffect, useState } from "react";

import { evaluationRequest as request } from "@/lib/evaluation-api";

type Counts = { executions: number; pending: number; scored_denominator: number;
  pass: number; partial: number; fail: number; blocked: number };
type Dashboard = {
  task: { task_id: string; title: string; build_version: string; knowledge_version: string; runtime_config_version: string };
  summary: Counts;
  by_case_version: Array<Counts & { case_id: string; case_version: number }>;
  assessment_counts: { ai_assisted: number; domain_expert: number };
  issues: { total: number; unresolved: number };
  severe_regressions: Array<{ replay_id: string; baseline_execution_id: string;
    candidate_execution_id: string; reasons: string[] }>;
};

const headers = ["用例版本", "执行", "通过", "部分", "不通过", "受阻", "待评分", "有效评分分母"];
const cell = "border-t px-3 py-2 text-left text-sm";

export function EvaluationDashboard({ token, taskId, reviewId, onOpenExecution }: {
  token: string; taskId: string; reviewId?: string; onOpenExecution: (id: string) => void;
}) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    if (!taskId) { setData(null); return; }
    try { setData(await request<Dashboard>(token, `/tasks/${taskId}/dashboard`)); setError(""); }
    catch (problem) { setError(problem instanceof Error ? problem.message : "无法读取任务看板。"); }
  }, [token, taskId]);
  useEffect(() => {
    const timer = window.setTimeout(() => { void reload(); }, 0);
    return () => window.clearTimeout(timer);
  }, [reload, reviewId]);

  return <section className="space-y-3 rounded-lg border p-5">
    <div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">冻结任务看板</h2>
      <p className="text-xs text-muted-foreground">统计当前任务的执行；每次执行计一次，同一用例的多次复测分别计数。</p></div>
      <button className="rounded border px-3 py-1.5 text-sm" onClick={() => void reload()}>刷新</button></div>
    {!taskId && <p className="text-sm text-muted-foreground">先选择一个 Task；跨构建的执行不混入同一分母。</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {data && <>
      <p className="text-sm font-medium">{data.task.title} · 构建 {data.task.build_version} · 知识库 {data.task.knowledge_version}</p>
      <p className="break-all text-xs text-muted-foreground">运行配置：{data.task.runtime_config_version}</p>
      <div className="overflow-x-auto"><table className="w-full min-w-[42rem] text-left"><thead><tr>{headers.map((name) => <th key={name} className="px-3 py-2 text-xs font-medium">{name}</th>)}</tr></thead>
        <tbody>{[{ ...data.summary, case_id: "合计", case_version: 0 }, ...data.by_case_version].map((row) =>
          <tr key={`${row.case_id}@${row.case_version}`}><td className={cell}>{row.case_version ? `${row.case_id} v${row.case_version}` : row.case_id}</td>
            {[row.executions, row.pass, row.partial, row.fail, row.blocked, row.pending, row.scored_denominator].map((value, index) =>
              <td key={index} className={cell}>{value}</td>)}</tr>)}</tbody></table></div>
      <p className="text-xs text-muted-foreground">有效评分分母只含开发试评的通过、部分和不通过；受阻、待评分另列。这里不计算专业准确率。</p>
      <div className="grid gap-2 text-sm sm:grid-cols-3"><p>问题：{data.issues.total} 项，待解决 {data.issues.unresolved} 项</p>
        <p>AI 辅助复核：{data.assessment_counts.ai_assisted} 条</p><p>领域专家审核：{data.assessment_counts.domain_expert} 条</p></div>
      <p className="text-xs text-muted-foreground">问题仅在最近一次复测通过且实际版本已核验时计为已解决；旧复测不回填核验状态。</p>
      <div className="space-y-2"><h3 className="font-medium">严重回归 · {data.severe_regressions.length}</h3>
        <p className="text-xs text-muted-foreground">仅在基线和候选都提交开发试评后，按“通过→不通过”或证据/答案“是→否”标记；需要人工解释原因。</p>
        {data.severe_regressions.map((item) => <div key={item.replay_id} className="rounded border border-destructive/30 p-3 text-xs">
          <p>{item.reasons.join("、")}</p><p className="break-all text-muted-foreground">Replay {item.replay_id}</p>
          <button className="underline" onClick={() => onOpenExecution(item.candidate_execution_id)}>打开候选执行与评分</button></div>)}
      </div>
    </>}
  </section>;
}
