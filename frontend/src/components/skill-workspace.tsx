"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, CircleHelp, RefreshCw, Search, TriangleAlert } from "lucide-react";
import { evaluationRequest } from "@/lib/evaluation-api";
import { evaluationHref } from "@/lib/evaluation-navigation";
import { availabilityLabels, generationLabels, type SkillAvailability, type SkillDetail, type SkillSummary } from "@/lib/skill-catalog";
import { useEvaluationSession } from "./evaluation-shell";
import { SkillExpressionEditor } from "./skill-expression-editor";

const button = "wb-button";

function Availability({ value, dependency = false }: { value: SkillAvailability; dependency?: boolean }) {
  const Icon = value === "available" ? CheckCircle2 : value === "unavailable" ? TriangleAlert : CircleHelp;
  const color = value === "available" ? "bg-emerald-50 text-emerald-800" : value === "unavailable" ? "bg-amber-50 text-amber-900" : "bg-slate-100 text-slate-600";
  const label = dependency ? { available: "本地检查通过", unavailable: "不可用", unknown: "未验证" }[value] : availabilityLabels[value];
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${color}`}><Icon size={13} aria-hidden="true" />{label}</span>;
}

function DescriptionList({ title, items }: { title: string; items: string[] }) {
  return <section className="min-w-0 wb-panel">
    <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
    {items.length ? <ul className="mt-2 space-y-1.5 pl-4 text-sm leading-6 text-slate-600 list-disc">{items.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="mt-2 text-sm text-slate-500">说明待补充。</p>}
  </section>;
}

export function SkillWorkspace({ detail = "" }: { detail?: string }) {
  const { token } = useEvaluationSession();
  const [items, setItems] = useState<SkillSummary[]>([]);
  const [skill, setSkill] = useState<SkillDetail | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    const request = detail
      ? evaluationRequest<SkillDetail>(token, `/skills/${encodeURIComponent(detail)}`).then((value) => { if (active) setSkill(value); })
      : evaluationRequest<SkillSummary[]>(token, "/skills").then((value) => { if (active) setItems(value); });
    request.catch((problem) => { if (active) setError(problem instanceof Error ? problem.message : "读取能力失败，请重试。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token, detail, reload]);

  function refresh() { setLoading(true); setError(""); setReload((value) => value + 1); }
  const term = search.trim().toLocaleLowerCase();
  const visible = items.filter((item) => `${item.title} ${item.name}`.toLocaleLowerCase().includes(term));

  return <div className="min-w-0 space-y-3" aria-label={detail ? "Skill 能力详情" : "Skill 能力列表"}>
    <div className="flex justify-end">
      <button type="button" onClick={refresh} disabled={loading} className={button}><RefreshCw size={14} aria-hidden="true" />{loading ? "读取中…" : "刷新状态"}</button>
    </div>
    {error && <div role="alert" className="rounded-xl border border-amber-200 bg-white p-4 text-sm text-amber-900"><p>{error}</p><button type="button" onClick={refresh} className={`${button} mt-3`}>重试</button></div>}
    {loading ? <p role="status" className="wb-panel text-sm text-slate-500">正在读取能力…</p> : !error && (detail ? skill && <>
      <section className="space-y-3 wb-panel">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold text-slate-900">{skill.title}</h2><Availability value={skill.availability} /></div>
        <p className="text-sm leading-6 text-slate-600">{skill.description}</p>
        {skill.alias_of && <p className="text-sm">此标识保留用于旧入口和历史记录。<Link className="text-emerald-800 underline" href={evaluationHref("skills", skill.alias_of)}>查看统一案例能力</Link></p>}
        <div className="flex flex-wrap gap-2 text-xs text-slate-500"><span>已注册</span><span aria-hidden="true">·</span><span>{generationLabels[skill.generation]}</span><span aria-hidden="true">·</span><span>{skill.configuration === "limited" ? "可调整默认表达" : "配置只读"}</span></div>
      </section>
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <DescriptionList title="适用场景" items={skill.scenarios} /><DescriptionList title="提问示例" items={skill.examples} />
        <DescriptionList title="输入要求" items={skill.inputs} /><DescriptionList title="返回内容" items={skill.outputs} />
      </div>
      <DescriptionList title="使用边界" items={skill.limitations} />
      {skill.configuration === "limited" && <SkillExpressionEditor token={token} skill={skill.name} />}
      <section className="space-y-3 wb-panel" aria-label="依赖状态">
        <h3 className="text-sm font-semibold">依赖与可用性</h3><p className="text-sm leading-6 text-slate-600">{skill.availability_note}</p>
        <ul className="divide-y">{skill.dependencies.map((dependency) => <li key={dependency.name} className="py-3 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium">{dependency.name}<span className="ml-2 text-xs font-normal text-slate-500">{dependency.required ? "必要依赖" : "按输入使用"}</span></p><Availability value={dependency.status} dependency /></div>
          <p className="mt-1.5 text-sm leading-6 text-slate-600">{dependency.message}</p>
        </li>)}</ul>
        <p className="text-xs leading-5 text-slate-500">读取页面仅检查本地就绪信息，不发送付费模型请求。刷新会重新读取当前状态，实际任务仍需校验输入和材料。</p>
      </section>
      <details className="min-w-0 wb-panel">
        <summary className="cursor-pointer text-sm font-medium">技术信息与输入输出</summary>
        <dl className="mt-4 space-y-3 text-sm">
          {[["注册标识", skill.name], ["注册描述", skill.registry_description], ["Harness 版本", skill.harness_version],
            ["独立 Skill 版本", skill.skill_version ?? "未采集"], ["当前运行配置版本", skill.runtime_config_version ?? "未采集"],
            ["当前代码指纹", skill.code_sha256 ?? "未采集"], ["状态读取时间", skill.checked_at]].map(([label, value]) =>
              <div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-all text-slate-800">{value}</dd></div>)}
        </dl>
        <p className="mt-4 text-xs leading-5 text-slate-500">以上是当前服务的信息。历史调用以其运行记录为准，不能用当前配置补写历史版本。</p>
        {[["输入 Schema", skill.input_schema], ["输出 Schema", skill.output_schema]].map(([label, schema]) => <details key={String(label)} className="mt-3 rounded-lg border p-3">
          <summary className="cursor-pointer text-sm">{String(label)}</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs leading-5">{JSON.stringify(schema, null, 2)}</pre>
        </details>)}
      </details>
    </> : <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="relative block w-full sm:max-w-sm"><span className="sr-only">查找能力</span><Search size={16} aria-hidden="true" className="absolute left-3 top-3 text-slate-400" /><input type="search" maxLength={100} placeholder="输入能力名称或标识" value={search} onChange={(event) => setSearch(event.target.value)} className="min-h-10 w-full rounded-lg border bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100" /></label>
        <p role="status" className="text-xs text-slate-500">已注册 {items.length} 项能力{term ? `，找到 ${visible.length} 项` : ""}</p>
      </div>
      {visible.length ? <ul className="divide-y overflow-hidden rounded-xl border bg-white">{visible.map((item) => <li key={item.name} className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-2"><h2 className="font-semibold"><Link href={evaluationHref("skills", item.name)} className="text-slate-900 hover:text-emerald-800 hover:underline">{item.title}</Link></h2><Availability value={item.availability} /></div>
        <p className="mt-2 text-sm leading-6 text-slate-600">{item.description}</p>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">已注册 · {generationLabels[item.generation]} · {item.configuration === "limited" ? "可调整默认表达" : "配置只读"}</p><Link aria-label={`查看${item.title}详情`} href={evaluationHref("skills", item.name)} className="inline-flex items-center gap-1 text-sm font-medium text-emerald-800 hover:underline">查看详情<ArrowRight size={14} aria-hidden="true" /></Link></div>
      </li>)}</ul> : <div className="wb-panel text-center text-sm text-slate-500"><p>{items.length ? "没有找到匹配的能力。" : "当前没有已注册能力。"}</p>{term && <button type="button" onClick={() => setSearch("")} className={`${button} mt-3`}>清除搜索</button>}</div>}
    </>)}
  </div>;
}
