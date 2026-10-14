"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { ArrowRight, BookOpen, Check, FileText, RotateCcw, Tags } from "lucide-react";
import { TagCascader, TaxonomyTree, type TaxonomyNode } from "./literature-taxonomy";
import { useShowcaseLiterature } from "@/components/showcase-literature-provider";
import { blankDemoPaper, demoDimensions, includesTag, tagPath, type DemoPaper } from "@/lib/showcase-literature";

const primary = "inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-800 px-4 py-2.5 text-sm font-medium text-white hover:bg-emerald-900 disabled:opacity-40";
const button = "inline-flex items-center justify-center gap-2 rounded-lg border bg-white px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40";
const input = "mt-2 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm";
const card = "rounded-2xl border bg-white p-5 sm:p-6";
const base = "/showcase/literature";
const toNodes = (tags: import("@/lib/showcase-literature").DemoTag[]): TaxonomyNode[] => tags.map((tag) => ({ id: tag.id, name: tag.name, dimension_id: tag.dimension, parent_id: tag.parent, path: tagPath(tag, tags) }));

export function ShowcaseLiterature({ section, detail }: { section: string; detail: string }) {
  const { reset } = useShowcaseLiterature();
  const router = useRouter();
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
      <p className="max-w-2xl text-sm leading-6 text-emerald-950">这是独立的流程示例。操作仅在本次体验中生效，刷新后重置，不会修改正式文献库。未打标文献默认属于全局。</p>
      <button className={button} onClick={() => { if (window.confirm("重置本次示例操作？")) { reset(); router.push(base); } }}><RotateCcw size={15} />重置示例</button>
    </div>
    {section === "literature-tags" ? <DemoTaxonomy /> : detail === "new" ? <DemoEditor /> : detail ? <DemoDetail id={detail} /> : <DemoLibrary />}
  </div>;
}

function DemoLibrary() {
  const { papers, tags } = useShowcaseLiterature();
  const params = useSearchParams();
  const [query, setQuery] = useState("");
  const [registration, setRegistration] = useState("all");
  const [usage, setUsage] = useState(params.has("tag") ? "all" : "normal");
  const [selectedTags, setSelectedTags] = useState<string[]>(params.has("tag") ? [params.get("tag")!] : []);
  const filtered = papers.filter((paper) => (usage === "all" || paper.disabled === (usage === "disabled")) &&
    (registration === "all" || paper.registration === registration) &&
    `${paper.title} ${paper.authors} ${paper.venue} ${paper.id}`.toLowerCase().includes(query.trim().toLowerCase()) &&
    demoDimensions.every((dim) => { const selected = selectedTags.filter((id) => tags.some((t) => t.id === id && t.dimension === dim.id)); return !selected.length || selected.some((id) => paper.tags.some((tag) => includesTag(id, tag, tags))); }));
  function clear() { setQuery(""); setRegistration("all"); setUsage("normal"); setSelectedTags([]); }
  return <>
    <section className="rounded-2xl bg-emerald-950 p-6 text-white sm:p-8">
      <div className="flex flex-wrap items-start justify-between gap-5"><div><p className="text-xs text-emerald-200">从收集到整理</p><h2 className="mt-2 text-xl font-semibold">让每篇论文都有位置，也能持续完善。</h2><p className="mt-3 max-w-xl text-sm leading-7 text-emerald-100">先保存文件，进入全局文献库；再逐篇补充信息、分类打标，完成登记。完成登记表示信息完整。</p></div><BookOpen size={32} className="text-emerald-200" /></div>
      <ol className="my-5 grid gap-3 text-sm sm:grid-cols-4">{["载入示例 PDF", "保存草稿", "补充信息与打标", "完成登记"].map((text, index) => <li key={text} className="rounded-lg bg-white/10 p-3"><span className="mr-2 text-emerald-200">0{index + 1}</span>{text}</li>)}</ol>
      <Link className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-medium text-emerald-950" href={`${base}/new`}>体验登记流程 <ArrowRight size={16} /></Link>
    </section>
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{[
      { label: "示例文献", count: papers.length, reg: "all", use: "all" },
      { label: "草稿", count: papers.filter((p) => p.registration === "draft").length, reg: "draft", use: "all" },
      { label: "已登记", count: papers.filter((p) => p.registration === "registered").length, reg: "registered", use: "all" },
      { label: "已停用", count: papers.filter((p) => p.disabled).length, reg: "all", use: "disabled" },
    ].map((stat) => <button key={stat.label} className="rounded-xl border bg-white p-4 text-left hover:border-emerald-500" onClick={() => { clear(); setRegistration(stat.reg); setUsage(stat.use); }}><span className="text-sm text-slate-500">{stat.label}</span><strong className="mt-2 block text-2xl">{stat.count}</strong></button>)}</div>
    <section className={card}>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><label className="text-sm">搜索示例文献<input className={input} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="标题、作者或编号" /></label>
        <label className="text-sm">登记状态<select className={input} value={registration} onChange={(e) => setRegistration(e.target.value)}><option value="all">全部</option><option value="draft">草稿</option><option value="registered">已登记</option></select></label>
        <label className="text-sm">使用状态<select className={input} value={usage} onChange={(e) => setUsage(e.target.value)}><option value="normal">正常</option><option value="all">全部</option><option value="disabled">已停用</option></select></label>
      </div><div className="mt-3"><TagCascader dimensions={demoDimensions} nodes={toNodes(tags)} value={selectedTags} onChange={setSelectedTags} /></div><div className="mt-4 flex items-center justify-between gap-3"><p role="status" className="text-sm text-slate-500">共 {filtered.length} 条示例文献</p><button className="text-sm text-emerald-800 underline" onClick={clear}>重置筛选</button></div>
      <div className="mt-4 space-y-3">{filtered.map((paper) => <article key={paper.id} className="rounded-xl border p-4"><div className="flex flex-wrap items-center justify-between gap-3"><Link className="min-w-0 break-words font-medium text-emerald-900 hover:underline" href={`${base}/${paper.id}`}>{paper.title}</Link><span className="rounded-full bg-slate-100 px-3 py-1 text-xs">{paper.registration === "draft" ? "草稿" : "已登记"} · {paper.disabled ? "已停用" : "正常"}</span></div><p className="mt-2 text-xs text-slate-500">{paper.id} · {paper.authors || "作者未填写"} · {paper.year || "年份未填写"}</p><div className="mt-3 flex flex-wrap gap-2 text-xs">{paper.tags.length ? paper.tags.map((id) => <span key={id} className="rounded bg-emerald-50 px-2 py-1 text-emerald-800">{tagPath(tags.find((tag) => tag.id === id)!, tags)}</span>) : <span className="rounded bg-slate-100 px-2 py-1 text-slate-600">未打标（全局）</span>}</div></article>)}</div>
      {!filtered.length && <p className="py-8 text-center text-sm text-slate-500">没有匹配的示例文献。可重置筛选后重新查找。</p>}
    </section>
  </>;
}

function DemoDetail({ id }: { id: string }) {
  const { papers, tags, setPapers } = useShowcaseLiterature();
  const [editing, setEditing] = useState(false);
  const paper = papers.find((item) => item.id === id);
  if (!paper) return <section className={card}><h2 className="font-semibold">示例不存在或已重置</h2><Link className="mt-4 inline-block text-emerald-800 underline" href={base}>返回文献管理</Link></section>;
  if (editing) return <DemoEditor existing={paper} onDone={() => setEditing(false)} />;
  function toggleUsage() {
    const reason = paper!.disabled ? "" : window.prompt("请输入示例停用原因");
    if (!paper!.disabled && !reason?.trim()) return;
    setPapers((items) => items.map((item) => item.id === id ? { ...item, disabled: !item.disabled, events: [`体验操作 · ${item.disabled ? "恢复为正常" : `停用：${reason!.trim()}`}`, ...item.events] } : item));
  }
  return <>
    <div className="flex flex-wrap justify-between gap-3"><Link className={button} href={base}>返回文献管理</Link><button className={primary} onClick={() => setEditing(true)}>继续整理与打标</button></div>
    <section className={card}><div className="flex flex-wrap gap-2 text-xs"><span className="rounded bg-blue-50 px-3 py-1">{paper.registration === "draft" ? "草稿" : "已登记"}</span><span className="rounded bg-slate-100 px-3 py-1">{paper.disabled ? "已停用" : "正常"}</span></div><h2 className="mt-4 text-xl font-semibold">{paper.title}</h2><p className="mt-2 text-xs text-slate-500">{paper.id} · 合成示例资料</p><dl className="mt-5 grid gap-4 text-sm sm:grid-cols-2">{[["作者", paper.authors], ["发表载体", paper.venue], ["年份", paper.year], ["语言", paper.language], ["出处说明", paper.source]].map(([label, value]) => <div key={label}><dt className="text-slate-500">{label}</dt><dd className="mt-1 break-words">{value || "未填写"}</dd></div>)}</dl><p className="mt-5 text-xs text-slate-500">完成登记只表示信息满足登记要求，不代表质量评价或审核结论。</p></section>
    <section className={card}><h3 className="font-semibold">分类标签</h3><div className="mt-3 flex flex-wrap gap-2">{paper.tags.length ? paper.tags.map((id) => <Link key={id} className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 underline" href={`${base}?tag=${encodeURIComponent(id)}`}>{tagPath(tags.find((tag) => tag.id === id)!, tags)}</Link>) : <p className="text-sm text-slate-500">未打标（全局）。可逐篇补充分类，不影响默认列表可见性。</p>}</div></section>
    <section className={card}><h3 className="font-semibold">示例 PDF</h3><p className="my-3 text-sm text-slate-500">统一使用一页流程说明文件，供体验预览与下载。</p><SamplePdf /></section>
    <section className={card}><h3 className="font-semibold">本次示例操作记录</h3><ol className="mt-4 space-y-3 text-sm text-slate-600">{paper.events.map((event, index) => <li className="border-l-2 border-emerald-200 pl-3" key={`${index}-${event}`}>{event}</li>)}</ol><button className={`${button} mt-5`} onClick={toggleUsage}>{paper.disabled ? "恢复示例文献" : "停用示例文献"}</button></section>
  </>;
}

function SamplePdf() {
  const dialog = useRef<HTMLDialogElement>(null);
  return <><div className="flex flex-wrap gap-3"><button className={button} onClick={() => dialog.current?.showModal()}>预览示例 PDF</button><a className={button} href="/showcase-assets/literature-workflow-sample.pdf" download>下载示例 PDF</a></div><dialog ref={dialog} className="m-auto w-[min(900px,94vw)] rounded-xl border p-4 backdrop:bg-black/40"><div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-medium">流程说明 PDF · 合成示例</h3><button className={button} onClick={() => dialog.current?.close()}>关闭预览</button></div><iframe title="示例 PDF 预览" src="/showcase-assets/literature-workflow-sample.pdf" className="h-[65vh] w-full" /><p className="mt-3 text-xs text-slate-500">浏览器无法预览时，可关闭窗口并下载示例 PDF。</p></dialog></>;
}

function DemoEditor({ existing, onDone }: { existing?: DemoPaper; onDone?: () => void }) {
  const { tags, setPapers } = useShowcaseLiterature();
  const router = useRouter();
  const [form, setForm] = useState<DemoPaper>(existing ?? blankDemoPaper());
  const [loaded, setLoaded] = useState(!!existing);
  const [step, setStep] = useState(existing ? 1 : 0);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  function patch(key: keyof DemoPaper, value: string | string[]) { setForm((old) => ({ ...old, [key]: value })); setDirty(true); setError(""); }
  function save(register: boolean) {
    if (!loaded) { setError("请先载入示例 PDF。"); return; }
    if (register && (!form.title.trim() || !form.authors.trim() || !form.venue.trim() || !form.source.trim() || !/^\d{4}$/.test(form.year) || Number(form.year) < 1000 || Number(form.year) > 3000)) {
      setError("请补充标题、作者、发表载体、有效年份及出处说明。"); setStep(1); return;
    }
    const saved = { ...form, id: existing?.id ?? `SAMPLE-${crypto.randomUUID().slice(0, 8).toUpperCase()}`, title: form.title.trim() || "文献流程示例（待整理）", registration: register ? "registered" as const : "draft" as const,
      events: [`体验操作 · ${register ? existing?.registration === "registered" ? "保存修改" : "完成登记" : existing ? "保存草稿修改" : "保存草稿"} · ${form.tags.length ? `已选 ${form.tags.length} 个标签` : "未打标（全局）"}`, ...form.events] };
    setPapers((items) => existing ? items.map((paper) => paper.id === saved.id ? saved : paper) : [saved, ...items]);
    setDirty(false);
    if (onDone) onDone(); else router.push(`${base}/${saved.id}`);
  }
  return <>
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">{existing ? "整理示例文献" : "体验新增文献"}</h2><button className={button} onClick={() => { if (!dirty || window.confirm("放弃尚未保存的示例修改？")) { if (onDone) onDone(); else router.push(base); } }}>取消整理</button></div>
    <ol className="grid grid-cols-3 gap-2">{["原始文件", "登记信息", "分类标签"].map((title, index) => <li key={title} aria-current={step === index ? "step" : undefined} className={`rounded-xl border p-3 text-sm ${step === index ? "border-emerald-500 bg-emerald-50 text-emerald-900" : "bg-white text-slate-500"}`}>{index + 1}. {title}</li>)}</ol>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-800">{error}</p>}
    {step === 0 && <section className={`${card} text-center`}><FileText size={40} className="mx-auto text-emerald-700" /><h3 className="mt-4 font-semibold">使用一份准备好的示例文件</h3><p className="mx-auto my-4 max-w-xl text-sm leading-7 text-slate-500">正式后台支持单篇 PDF 上传。这里提供流程说明 PDF，载入后可先存为草稿，稍后继续填写。</p>{!loaded ? <button className={primary} onClick={() => { setLoaded(true); setDirty(true); setForm({ ...form, title: "文献流程示例（待整理）" }); }}>载入示例 PDF</button> : <><p role="status" className="mb-4 flex items-center justify-center gap-2 text-sm text-emerald-800"><Check size={17} />示例文件已载入，可保存草稿</p><div className="flex justify-center"><SamplePdf /></div></>}</section>}
    {step === 1 && <section className={card}><div className="mb-5 flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">补充论文基本信息</h3><button className="text-sm text-emerald-800 underline" onClick={() => { setForm({ ...form, title: "农田水氮管理研究（流程示例）", authors: "示例作者甲；示例研究团队", venue: "示例学术期刊", year: "2025", language: "中文", source: "为演示登记流程而合成的资料，不对应真实研究论文。" }); setDirty(true); setError(""); }}>填入示例信息</button></div><div className="grid gap-4 sm:grid-cols-2">{([ ["title", "论文标题", 500], ["authors", "作者（按署名顺序）", 500], ["venue", "发表载体", 500], ["year", "发表年份", 4] ] as const).map(([key, label, maxLength]) => <label key={key} className="text-sm">{label}<input className={input} maxLength={maxLength} value={form[key]} onChange={(e) => patch(key, e.target.value)} /></label>)}<label className="text-sm">论文语言<select className={input} value={form.language} onChange={(e) => patch("language", e.target.value)}><option>中文</option><option>英文</option></select></label><p className="self-end rounded-lg bg-slate-50 p-3 text-sm text-slate-500">本流程以期刊论文为例。</p><label className="text-sm sm:col-span-2">出处说明<textarea className={input} maxLength={2000} rows={3} value={form.source} onChange={(e) => patch("source", e.target.value)} /></label></div></section>}
    {step === 2 && <section className={card}><h3 className="font-semibold">从不同角度组织文献</h3><p className="mt-2 text-sm leading-6 text-slate-500">示例维度均为选填，可保持“未打标（全局）”。同一维度不同时保留祖先与后代标签。</p><div className="mt-5"><TagCascader dimensions={demoDimensions} nodes={toNodes(tags)} value={form.tags} onChange={(ids) => patch("tags", ids)} mode="assign" /></div><p className="mt-5 text-sm text-emerald-800">{form.tags.length ? `已选择 ${form.tags.length} 个标签` : "当前：未打标（全局）"}</p></section>}
    <div className="flex flex-wrap justify-between gap-3 rounded-xl border bg-white p-4"><div className="flex gap-2">{step > 0 && <button className={button} onClick={() => setStep(step - 1)}>上一步</button>}{step < 2 && <button className={primary} disabled={!loaded} onClick={() => setStep(step + 1)}>下一步</button>}</div><div className="flex flex-wrap gap-2">{existing?.registration !== "registered" && <button className={button} disabled={!loaded} onClick={() => save(false)}>保存示例草稿</button>}{step === 2 && <button className={primary} onClick={() => save(true)}>{existing?.registration === "registered" ? "保存示例修改" : "完成示例登记"}</button>}</div></div>
  </>;
}

function DemoTaxonomy() {
  const { tags, setTags, papers } = useShowcaseLiterature();
  const [dimension, setDimension] = useState("topic");
  const [message, setMessage] = useState("");
  const nodes = toNodes(tags);
  return <>
    <section className={card}><Tags className="text-emerald-700" size={28} /><h2 className="mt-3 text-lg font-semibold">维度表达角度，层级表达关系。</h2><p className="mt-3 text-sm leading-7 text-slate-500">展开标签查看父子关系，在节点旁逐级新增。按父标签查找时包含全部下级。地区示例可体验“广西 → 南宁 → 示范县”的三级分类。</p></section>
    <div className="grid gap-5 xl:grid-cols-[13rem_minmax(0,1fr)]"><section className={card}><h2 className="mb-4 font-semibold">标签维度</h2><div className="space-y-2">{demoDimensions.map((dim) => <button key={dim.id} aria-pressed={dimension === dim.id} className={`w-full rounded-lg p-3 text-left text-sm ${dimension === dim.id ? "bg-emerald-50 text-emerald-900" : "bg-slate-50"}`} onClick={() => { setDimension(dim.id); setMessage(""); }}>{dim.name}<span className="mt-1 block text-xs text-slate-500">多选 · 非必填</span></button>)}</div></section>
      <section className={`${card} min-w-0`}><h2 className="mb-4 font-semibold">{demoDimensions.find((dim) => dim.id === dimension)?.name}</h2>
        <TaxonomyTree key={dimension} nodes={nodes.filter((node) => node.dimension_id === dimension)} onAdd={async (parent, name) => { if (tags.some((tag) => tag.dimension === dimension && tag.parent === parent && tag.name.toLocaleLowerCase() === name.toLocaleLowerCase())) throw new Error("同一父节点下不能有重名标签。"); setTags((items) => [...items, { id: `tag-${crypto.randomUUID()}`, dimension, parent, name }]); setMessage("示例标签已添加，可在文献整理流程中选择。"); }} actions={(node) => <Link className="text-emerald-800 underline" href={`${base}?tag=${encodeURIComponent(node.id)}`}>关联文献 {papers.filter((paper) => paper.tags.some((id) => includesTag(node.id, id, tags))).length} 篇</Link>} />
        <p className="mt-3 text-xs text-slate-500">关联数量包含下级标签及已停用示例文献。</p>{message && <p role="status" className="mt-3 text-sm text-emerald-800">{message}</p>}<Link className={`${button} mt-4`} href={base}>返回文献并打标</Link>
      </section></div>
  </>;
}
