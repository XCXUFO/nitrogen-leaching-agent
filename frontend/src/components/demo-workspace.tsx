"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, FlaskConical, LockKeyhole, Search } from "lucide-react";
import { apiBaseUrl } from "@/lib/api";
import { MarkdownAnswer } from "@/components/chat/markdown-answer";

type Run = { run_id: string; started_at: string; input: string; answer: string; latency_ms: number; route: string;
  citations: { index: number; title: string; excerpt: string }[];
  tools: { skill: string; status: string }[]; evidence: { value: number; unit: string; cell: string; day_cell: string; model_day: number }[] };
type Case = { id: string; title: string; category: string; summary: string; expected: string[]; status: string;
  review: string; runs: Run[]; source: string; stages?: string[]; comparison?: { label: string; overall: string; execution_id: string }[] };
type Catalog = { version: string; published_on: string; notice: string; cases: Case[];
  assets: { filename: string; sha256: string; description: string }[]; sources: { name: string; sha256: string }[] };
const modules = [["overview", "工作台总览"], ["tasks", "评测任务"], ["cases", "用例库"], ["executions", "执行记录"],
  ["issues", "问题管理"], ["regressions", "回归对比"], ["reviews", "审核状态"], ["assets", "资料与证据"], ["runs", "运行记录"]];

export function DemoWorkspace({ section, detail }: { section: string; detail: string }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/demo/catalog`, { signal: controller.signal }).then(async (r) => {
      if (!r.ok) throw new Error("暂时无法读取展示案例。");
      setCatalog(await r.json()); setError("");
    }).catch((e) => { if (e.name !== "AbortError") setError("暂时无法读取展示案例，请稍后重试。"); });
    return () => controller.abort();
  }, [attempt]);
  const title = modules.find(([key]) => key === section)?.[1] ?? "工作台总览";
  const selected = catalog?.cases.find((c) => c.id === detail);
  const filtered = (catalog?.cases ?? []).filter((c) =>
    (!["issues", "regressions", "tasks"].includes(section) || c.id === "workflow") &&
    `${c.title} ${c.category} ${c.summary}`.includes(query));
  function cards(items: Case[]) {
    return <div className="grid gap-4 xl:grid-cols-2">{items.map((c) => <Link key={c.id} href={`/showcase/${section === "overview" ? "cases" : section}/${c.id}`}
      className="group rounded-2xl border bg-white p-5 transition hover:border-emerald-500 hover:shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs"><span className="font-medium text-emerald-800">{c.category}</span><span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">{c.status}</span></div>
      <h3 className="mt-4 text-lg font-semibold text-slate-950">{c.title}</h3><p className="mt-2 text-sm leading-6 text-slate-600">{c.summary}</p>
      <span className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-emerald-800">查看过程与依据 <ArrowRight size={15} /></span>
    </Link>)}</div>;
  }
  return <div className="min-h-dvh bg-slate-50 lg:pl-60">
    <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r bg-white lg:flex">
      <Link href="/showcase" className="flex h-20 items-center gap-3 border-b px-6 font-semibold text-emerald-900"><FlaskConical size={23} />评测工作台</Link>
      <nav aria-label="展示后台导航" className="flex-1 space-y-1 p-3">{modules.map(([key, label]) => <Link key={key} href={`/showcase/${key}`} aria-current={section === key ? "page" : undefined}
        className={`block rounded-lg px-4 py-3 text-sm ${section === key ? "bg-emerald-50 font-semibold text-emerald-900" : "text-slate-600 hover:bg-slate-100"}`}>{label}</Link>)}</nav>
      <p className="border-t p-5 text-xs leading-6 text-slate-500">公开案例快照<br />访客聊天不会出现在这里。</p>
    </aside>
    <header className="border-b bg-white px-5 py-4 sm:px-8"><div className="flex flex-wrap items-center justify-between gap-3">
      <Link href="/" className="inline-flex items-center gap-2 text-sm text-slate-600"><ArrowLeft size={16} />体验助手</Link>
      <div className="flex items-center gap-4"><span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1.5 text-xs text-emerald-900"><LockKeyhole size={13} />展示模式 · 仅供浏览</span><Link href="/evaluation" className="text-xs text-slate-500 hover:underline">管理登录</Link></div>
    </div><nav aria-label="移动端展示导航" className="mt-4 flex gap-2 overflow-x-auto pb-1 lg:hidden">{modules.map(([key, label]) => <Link className={`shrink-0 rounded-lg px-3 py-2 text-sm ${section === key ? "bg-emerald-50 text-emerald-900" : "bg-slate-50 text-slate-600"}`} key={key} href={`/showcase/${key}`}>{label}</Link>)}</nav></header>
    <main className="mx-auto max-w-6xl space-y-6 p-5 sm:p-8">
      <div><p className="text-xs font-medium text-emerald-800">农业模型助手 / 质量与证据</p><h1 className="mt-2 text-2xl font-semibold tracking-tight">{detail ? selected?.title ?? "案例详情" : title}</h1>
        <p className="mt-2 text-sm leading-6 text-slate-500">查看一个回答如何被测试、追踪与复核。</p></div>
      {error ? <div role="alert" className="rounded-xl border bg-white p-6">{error}<button onClick={() => setAttempt(attempt + 1)} className="ml-4 text-emerald-800 underline">重新加载</button><Link href="/" className="ml-4 underline">返回助手</Link></div> : !catalog ? <p role="status">正在读取公开案例…</p> : <>
        <p className="rounded-xl border border-emerald-100 bg-emerald-50/60 px-4 py-3 text-xs leading-6 text-emerald-950">{catalog.notice}</p>
        {detail ? selected ? <>
          <Link href={`/showcase/${section}`} className="inline-flex items-center gap-2 text-sm text-emerald-800"><ArrowLeft size={15} />返回{title}</Link>
          <section className="rounded-2xl border bg-white p-6"><div className="flex flex-wrap justify-between gap-3"><h2 className="font-semibold">验证目标与判断标准</h2><span className="text-xs text-slate-500">{selected.status}</span></div><p className="mt-3 text-sm leading-7 text-slate-600">{selected.summary}</p><ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6">{selected.expected.map((e) => <li key={e}>{e}</li>)}</ul><p className="mt-5 rounded-lg bg-amber-50 p-3 text-sm leading-6 text-amber-950">{selected.review}</p></section>
          {selected.stages && <section className="rounded-2xl border bg-white p-6"><h2 className="font-semibold">流程验证记录</h2><ol className="mt-4 grid gap-3 sm:grid-cols-2">{selected.stages.map((stage, i) => <li key={stage} className="flex items-start gap-3 rounded-xl bg-slate-50 p-4 text-sm leading-6"><span className="font-semibold text-emerald-800">{i + 1}.</span>{stage}</li>)}</ol></section>}
          {selected.comparison && <section className="rounded-2xl border bg-white p-6"><h2 className="font-semibold">原执行与复测记录</h2><p className="mt-2 text-xs text-amber-800">以下评分用于验证流程，不表示答案质量提升。</p><div className="mt-4 grid gap-4 sm:grid-cols-2">{selected.comparison.map((c) => <div key={c.label} className="rounded-xl border p-4"><h3 className="font-medium">{c.label}</h3><p className="mt-2 text-sm">{c.overall}</p><p className="mt-2 break-all text-xs text-slate-500">{c.execution_id}</p></div>)}</div></section>}
          <section className="space-y-4"><h2 className="font-semibold">已保存的运行回答</h2>{selected.runs.map((run, i) => <article key={`${run.run_id}-${i}`} className="min-w-0 rounded-2xl border bg-white p-5 sm:p-6"><div className="flex flex-wrap justify-between gap-2 text-xs text-slate-500"><span>历史记录 · {run.started_at.slice(0, 10)}</span><span>{run.latency_ms} ms</span></div><h3 className="mt-3 font-semibold">{i + 1}. {run.input}</h3><div className="mt-4 min-w-0"><MarkdownAnswer content={run.answer} /></div>
            {!!run.evidence.length && <div className="mt-4 space-y-2 rounded-xl bg-emerald-50 p-4">{run.evidence.map((e, j) => <p key={j} className="break-words text-sm leading-6">表格依据：{e.value} {e.unit} · 模型日序 {e.model_day}<br />数值单元格 {e.cell} / 日序单元格 {e.day_cell}</p>)}</div>}
            {!!run.citations.length && <div className="mt-4 space-y-3 rounded-xl bg-slate-50 p-4"><h4 className="text-sm font-medium">引用与原文摘录 · AI 辅助整理，待专家审核</h4>{run.citations.map((c) => <div key={c.index} className="text-sm leading-7"><p className="font-medium">[{c.index}] {c.title}</p><blockquote className="mt-1 whitespace-pre-wrap border-l-2 border-emerald-200 pl-3 text-slate-600">{c.excerpt}</blockquote></div>)}</div>}
            <details className="mt-4 border-t pt-3 text-xs text-slate-500"><summary className="cursor-pointer">查看运行追踪</summary><div className="mt-3 space-y-2 break-all"><p>Run：{run.run_id}</p><p>路由：{run.route}</p><p>工具：{run.tools.map((t) => `${t.skill} (${t.status})`).join(" → ") || "无工具调用"}</p></div></details>
          </article>)}</section>
          <details className="text-xs text-slate-500"><summary className="cursor-pointer">公开快照来源</summary><p className="mt-2 break-all">{selected.source}</p><p className="mt-2 break-all">SHA-256：{catalog.sources.find((s) => s.name === selected.source)?.sha256}</p></details>
        </> : <p>未找到公开案例。<Link href="/showcase" className="ml-2 underline">返回总览</Link></p> : section === "assets" ? <div className="space-y-4">{catalog.assets.map((a) => <article key={a.sha256} className="rounded-2xl border bg-white p-6"><h2 className="font-semibold">{a.filename}</h2><p className="mt-3 text-sm leading-7 text-slate-600">{a.description}</p><p className="mt-3 break-all text-xs text-slate-500">SHA-256：{a.sha256}</p><Link href="/" className="mt-5 inline-flex items-center gap-2 text-sm text-emerald-800">返回助手，使用示例文件 <ArrowRight size={15} /></Link></article>)}</div> : <>
          {section === "overview" && <>
            <section className="rounded-2xl bg-emerald-950 p-6 text-white sm:p-8"><h2 className="text-xl font-semibold">回答之外，还要能解释如何验证。</h2><p className="mt-3 max-w-2xl text-sm leading-7 text-emerald-100">这里展示文件计算、多轮对话与文献问答的历史运行，以及评测问题闭环。你可以沿着问题、回答、依据和复测逐步查看。</p><Link href="/showcase/cases/follow-up" className="mt-5 inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-medium text-emerald-950">从一个完整对话案例开始 <ArrowRight size={16} /></Link></section>
            <div className="grid grid-cols-3 gap-3">{[[String(catalog.cases.filter((c) => c.id !== "workflow").length), "历史能力案例"], ["1", "合成流程演示"], ["待完成", "独立专业审核"]].map(([value, label]) => <div key={label} className="rounded-xl border bg-white p-4"><p className="text-xl font-semibold text-emerald-900">{value}</p><p className="mt-2 text-xs text-slate-500">{label}</p></div>)}</div>
          </>}
          {section === "tasks" && <p className="text-sm leading-7 text-slate-600">展示批次：公开快照 {catalog.version}。下方保留隔离测试任务的完整流程，供查看任务与执行、评分、问题的关联。</p>}
          {section === "reviews" && <p className="text-sm leading-7 text-slate-600">本批没有专家通过结论。查看各案例的证据和审核边界；合成评分不纳入专业准确率。</p>}
          {section !== "overview" && <label className="flex max-w-lg items-center gap-2 rounded-lg border bg-white px-3 py-2.5"><Search size={16} className="text-slate-400" /><input aria-label="搜索公开案例" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} placeholder="搜索标题、类别或说明" className="min-w-0 flex-1 bg-transparent text-sm outline-none" /></label>}
          {cards(filtered.slice(page * 4, page * 4 + 4))}
          {!filtered.length && <p className="text-sm text-slate-500">没有匹配的公开案例。</p>}
          {filtered.length > 4 && <div className="flex items-center justify-end gap-4 text-sm"><button className="rounded-lg border bg-white px-3 py-2 disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>{page + 1} / {Math.ceil(filtered.length / 4)}</span><button className="rounded-lg border bg-white px-3 py-2 disabled:opacity-40" disabled={(page + 1) * 4 >= filtered.length} onClick={() => setPage(page + 1)}>下一页</button></div>}
        </>}
        <p className="border-t pt-4 text-xs text-slate-400">公开快照 {catalog.version} · 整理于 {catalog.published_on} · 仅统计上述展示案例</p>
      </>}
    </main>
  </div>;
}
