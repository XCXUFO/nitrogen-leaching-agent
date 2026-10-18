"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { evaluationRequest } from "@/lib/evaluation-api";
import { ratioLabel, type OnlineMetrics } from "@/lib/online-metrics";
import { useEvaluationSession } from "./evaluation-shell";

const input = "w-full rounded-lg border bg-white px-3 py-2 text-sm";
const button = "rounded-lg border bg-white px-3 py-2 text-sm disabled:opacity-50";
const filterKeys = ["source", "mode", "status", "skill", "task_type", "config_version", "from", "to"];
const statusLabels: Record<string, string> = { succeeded: "正常结束", failed: "失败", cancelled: "取消", interrupted: "中断", unknown: "未知", accepted: "已受理", running: "执行中", expired: "恢复已过期" };
const sessionStatusLabels: Record<string, string> = { normal: "截至当前全轮正常", abnormal: "含异常轮次", running: "存在执行中轮次", unknown: "状态待确认" };
const taskLabels: Record<string, string> = { knowledge: "专业问答", explanation: "内容解释", comparison: "比较", case_search: "案例查找", file_calculation: "文件计算", capability: "能力咨询", uncollected: "历史未采集" };
const dateInput = (value: string | undefined) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset()*60_000).toISOString().slice(0,16);
};

export function OnlineEffects({ query = "" }: { query?: string }) {
  const { token, user } = useEvaluationSession();
  const router = useRouter();
  const [filters, setFilters] = useState(() => Object.fromEntries(
    [...new URLSearchParams(query)].filter(([key]) => filterKeys.includes(key)),
  ));
  const [metrics, setMetrics] = useState<OnlineMetrics | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    evaluationRequest<OnlineMetrics>(token, `/online-metrics?${query}`)
      .then((value) => { if (active) setMetrics(value); })
      .catch((problem) => { if (active) setError(problem instanceof Error ? problem.message : "读取失败。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token, query, reload]);

  function apply(event: FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => !!value));
    router.push(`/evaluation/online-effects?${params}`);
  }
  const filterHref = (extra: Record<string, string>) => {
    const selected = Object.fromEntries([...new URLSearchParams(query)].filter(([key]) => filterKeys.includes(key)));
    return `/evaluation/online-effects?${new URLSearchParams({ ...selected, ...extra })}`;
  };

  return <div className="space-y-4">
    <div className="space-y-1"><h2 className="font-semibold">会话运行概览</h2><p className="text-sm text-slate-600">以完整会话观察多轮交互，再查看每轮执行与能力调用。</p></div>
    <form onSubmit={apply} className="grid gap-3 rounded-xl border bg-white p-4 sm:grid-cols-3 lg:grid-cols-4">
      <label className="space-y-1 text-sm">来源<select className={input} value={filters.source ?? "formal"} onChange={(e) => setFilters({ ...filters, source: e.target.value })}><option value="formal">前台会话</option><option value="test">Skill 测试</option><option value="evaluation">评测</option><option value="legacy">历史未完整关联</option></select></label>
      <label className="space-y-1 text-sm">执行模式<select className={input} value={filters.mode ?? ""} onChange={(e) => setFilters({ ...filters, mode: e.target.value })}><option value="">全部模式</option><option value="auto">自动</option><option value="specified">指定能力</option></select></label>
      <label className="space-y-1 text-sm">会话状态<select className={input} value={filters.status ?? ""} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">全部</option>{Object.entries(sessionStatusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="space-y-1 text-sm">实际 Skill<input className={input} value={filters.skill ?? ""} onChange={(e) => setFilters({ ...filters, skill: e.target.value })} /></label>
      <label className="space-y-1 text-sm">配置版本<input className={input} value={filters.config_version ?? ""} onChange={(e) => setFilters({ ...filters, config_version: e.target.value })} /></label>
      <label className="space-y-1 text-sm">任务类型<select className={input} value={filters.task_type ?? ""} onChange={(e) => setFilters({ ...filters, task_type: e.target.value })}><option value="">全部</option>{Object.entries(taskLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="space-y-1 text-sm">会话创建起始时间<input className={input} type="datetime-local" value={dateInput(filters.from)} onChange={(e) => setFilters({ ...filters, from: e.target.value ? new Date(e.target.value).toISOString() : "" })} /></label>
      <label className="space-y-1 text-sm">会话创建结束时间<input className={input} type="datetime-local" value={dateInput(filters.to)} onChange={(e) => setFilters({ ...filters, to: e.target.value ? new Date(e.target.value).toISOString() : "" })} /></label>
      <div className="flex items-end gap-2"><button type="submit" className={button}>应用筛选</button><button type="button" className={button} onClick={() => { setError(""); setLoading(true); setReload((n) => n+1); }}>刷新数据</button></div>
    </form>
    {user.role === "developer" && <Link className="text-sm text-emerald-800 underline" href="/evaluation/runs">查看会话运行记录</Link>}
    {loading && <p role="status">正在读取…</p>}{error && <p role="alert" className="text-sm text-amber-900">{error}</p>}
    {metrics && <>
      <p className="text-xs leading-6 text-slate-500">按会话首次受理时间选取范围。模式、版本、Skill 与任务条件须在同一轮命中，选中后保留该来源下的完整会话轮次。跨日追问仍归属原会话。缺运行明细 {metrics.trace_missing} 轮。</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border bg-white p-4"><p className="text-sm">会话数</p><strong className="mt-2 block text-2xl">{metrics.sessions}</strong><p className="mt-2 text-xs text-slate-500">包含 {metrics.questions} 轮提问</p></div>
        <div className="rounded-xl border bg-white p-4"><p className="text-sm">多轮会话占比</p><strong className="mt-2 block text-lg">{ratioLabel(metrics.multi_turn)}</strong><p className="mt-2 text-xs text-slate-500">至少包含两轮提问的会话</p></div>
        <div className="rounded-xl border bg-white p-4"><p className="text-sm">平均会话轮数</p><strong className="mt-2 block text-2xl">{metrics.mean_turns ?? "—"}</strong></div>
        <div className="rounded-xl border bg-white p-4"><p className="text-sm">含异常轮次的会话</p><strong className="mt-2 block text-2xl">{metrics.session_states.abnormal ?? 0}</strong><p className="mt-2 text-xs text-slate-500">运行状态不代表回答质量或上下文理解正确性</p></div>
      </div>
      <section className="rounded-xl border bg-white p-4"><h3 className="text-sm font-semibold">会话状态分布</h3><ul className="mt-2 flex flex-wrap gap-3 text-sm">{Object.entries(metrics.session_states).map(([key, count]) => <li key={key}><Link href={filterHref({ status: key })} className="text-emerald-800 underline">{sessionStatusLabels[key] ?? key}：{count}</Link></li>)}</ul><p className="mt-2 text-xs text-slate-500">任一轮失败、取消或中断即归为含异常轮次；其余会话按执行中、待确认或全轮正常展示。会话可以继续追问。</p></section>
      <section className="rounded-xl border bg-white p-4"><h3 className="font-semibold">会话轮数分布</h3><ul className="mt-2 flex flex-wrap gap-3 text-sm">{metrics.turn_distribution.map((item) => <li key={item.turns}>{item.turns} 轮：{item.sessions} 个会话</li>)}</ul>{!metrics.sessions && <p className="mt-2 text-sm text-slate-500">暂无符合条件的会话。</p>}</section>
      <section className="rounded-xl border bg-white p-4"><h3 className="font-semibold">每日新建会话（北京时间）</h3><table className="mt-2 w-full text-left text-sm"><thead><tr><th>创建日期</th><th>会话</th><th>含异常轮次</th><th>累计提问轮数</th></tr></thead><tbody>{metrics.daily.map((day) => <tr key={day.date} className="border-t"><td className="py-2">{day.date}</td><td>{day.sessions}</td><td>{day.abnormal_sessions}</td><td>{day.turns}</td></tr>)}</tbody></table></section>
      {user.role === "developer" && !!metrics.recent_sessions.length && <section className="overflow-auto rounded-xl border bg-white p-4"><h3 className="font-semibold">当前范围的会话</h3><p className="mt-1 text-xs text-slate-500">展示最近创建的 {metrics.recent_sessions.length} 个会话，打开后可查看连续问答和每轮上下文。</p><table className="mt-3 w-full min-w-[550px] text-left text-sm"><thead><tr><th>会话主题</th><th>轮数</th><th>会话状态</th><th>缺失明细轮数</th><th>运行记录</th></tr></thead><tbody>{metrics.recent_sessions.map((session, index) => <tr className="border-t" key={`${session.session_id}:${index}`}><td className="max-w-64 break-words py-2">{session.topic}</td><td>{session.turns}</td><td>{sessionStatusLabels[session.status] ?? session.status}</td><td>{session.trace_missing}</td><td>{session.run_id ? <Link href={`/evaluation/runs/${encodeURIComponent(session.run_id)}`} className="text-emerald-800 underline">查看完整会话</Link> : "运行明细未采集"}</td></tr>)}</tbody></table></section>}
      <section className="rounded-xl border bg-white p-4"><h3 className="font-semibold">会话任务类型分布</h3><ul className="mt-2 flex flex-wrap gap-3 text-sm">{Object.entries(metrics.by_task).map(([task, count]) => <li key={task}><Link href={filterHref({ task_type: task })} className="text-emerald-800 underline">{taskLabels[task] ?? task}：{count} 个会话</Link></li>)}</ul><p className="mt-2 text-xs text-slate-500">同一任务在一个会话内只计一次；一个会话可涉及多类任务，分组数量不可直接加总。</p></section>
      {!!metrics.by_skill.length && <section className="overflow-auto rounded-xl border bg-white p-4"><h3 className="font-semibold">实际 Skill 调用与耗时</h3><table className="mt-3 w-full min-w-[650px] text-left text-sm"><thead><tr><th>能力</th><th>涉及会话数</th><th>调用轮数</th><th>调用数</th><th>失败调用</th><th>平均调用耗时</th></tr></thead><tbody>{metrics.by_skill.map((item) => <tr className="border-t" key={item.skill}><td className="py-2"><Link className="text-emerald-800 underline" href={filterHref({ skill: item.skill })}>{item.skill}</Link></td><td>{item.sessions}</td><td>{item.runs}</td><td>{item.calls}</td><td>{item.failures}</td><td>{item.mean_latency_ms} ms</td></tr>)}</tbody></table><p className="mt-2 text-xs text-slate-500">会话可使用多个 Skill，分组会话数不可相加；点击能力后保留命中会话中的全部轮次。</p></section>}
      <section className="space-y-3 rounded-xl border bg-white p-4"><h3 className="font-semibold">会话内每轮执行明细</h3><p className="text-xs text-slate-500">以下按每轮首次主运行及实际步骤统计，用于定位执行问题。</p><ul className="flex flex-wrap gap-3 text-sm">{Object.entries(metrics.states).map(([key, count]) => <li key={key}>{statusLabels[key] ?? key}：{count} 轮</li>)}</ul>{(["tool", "skill", "service"] as const).map((kind) => <div className="text-sm" key={kind}><p>{kind === "tool" ? "底层工具" : kind === "skill" ? "注册 Skill" : "前置服务"}：成功 {ratioLabel(metrics.steps[kind].success)}；尝试失败 {ratioLabel(metrics.steps[kind].attempt_failure)}；检索无结果 {ratioLabel(metrics.steps[kind].retrieval_no_result)}</p><p className="mt-1 text-xs text-slate-500">排除的步骤状态：{JSON.stringify(metrics.steps[kind].excluded)}</p></div>)}</section>
      <p className="rounded-xl border bg-white p-4 text-sm">这些会话中，{metrics.reruns.sessions} 个会话发生了 {metrics.reruns.attempts} 次主动重跑，其中 {metrics.reruns.succeeded} 次正常结束；{metrics.reruns.recovered_failed_primary} 个异常主运行在重跑后得到结果。重跑单独统计，保留原轮次与异常记录。</p>
    </>}
  </div>;
}
