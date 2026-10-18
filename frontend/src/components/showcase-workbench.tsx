"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { useShowcaseLiterature } from "./showcase-literature-provider";
import { ShowcaseExperienceNotice, ShowcaseReceipts, demoButton as button, demoPrimary as primary, demoInput as input, demoCard as card } from "./showcase-experience";
import { CaseBodyEditor } from "./case-body-editor";
import { TagCascader } from "./literature-taxonomy";
import { demoDimensions, includesTag, tagPath } from "@/lib/showcase-literature";
import { demoSuggestedTags, type DemoCase, type DemoQuestion } from "@/lib/showcase-workbench";

const base = "/showcase/case-library";

export function ShowcaseCases({ detail }: { detail: string }) {
  const { cases } = useShowcaseLiterature();
  const record = cases.find((item) => item.id === detail);
  return <div className="space-y-4"><ShowcaseExperienceNotice href={base} />
    {detail === "new" ? <CaseEditor /> : detail ? record ? <CaseDetail record={record} /> : <section className={card}><p>示例不存在或已重置。</p><Link className={button} href={base}>返回案例与措施</Link></section> : <CaseLibrary />}
  </div>;
}

function CaseLibrary() {
  const { cases, setCases, tags, setReceipts } = useShowcaseLiterature();
  const params = useSearchParams();
  const [query, setQuery] = useState("");
  const [availability, setAvailability] = useState("all");
  const [filters, setFilters] = useState<string[]>(params.get("tag") ? [params.get("tag")!] : []);
  const [untagged, setUntagged] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const all = useRef<HTMLInputElement>(null);
  const filtered = cases.filter((item) => item.title.toLowerCase().includes(query.trim().toLowerCase()) &&
    (availability === "all" || item.enabled === (availability === "open")) && (!untagged || !item.tags.length) &&
    demoDimensions.every((dim) => { const ids = filters.filter((id) => tags.some((tag) => tag.id === id && tag.dimension === dim.id)); return !ids.length || ids.some((id) => item.tags.some((tag) => includesTag(id, tag, tags))); }));
  function batch(action: "tag" | "open" | "close") {
    setCases((items) => items.map((item) => selected.includes(item.id) ? action === "tag" ? { ...item, tags: demoSuggestedTags(item.title) } : { ...item, enabled: action === "open" } : item));
    if (action === "tag") setReceipts((items) => [{ id: crypto.randomUUID(), kind: "案例 AI 打标", items: filtered.filter((item) => selected.includes(item.id)).map((item) => ({ id: item.id, title: item.title, status: "已采用预置标签建议", href: `${base}/${item.id}` })) }, ...items]);
    setMessage(action === "tag" ? "已更新所选示例标签，请逐项审核。原文、解释和开放状态保持原值。" : `已${action === "open" ? "开放" : "关闭"}所选示例。`);
    setSelected([]);
  }
  return <>
    <section className={card}><div className="flex flex-wrap justify-between gap-3"><div><h2 className="font-semibold">整理案例与措施，保留适用条件和来源</h2><p className="mt-2 text-sm leading-6 text-slate-500">支持富文本与表格、解释初稿、共享标签和开放控制。仅已保存且开放的案例可用于后续案例问答。</p></div><Link className={primary} href={`${base}/new`}>新增案例示例</Link></div></section>
    <section className={`${card} space-y-4`}>
      <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">搜索案例<input className={input} value={query} onChange={(e) => { setQuery(e.target.value); setSelected([]); }} /></label><label className="text-sm">开放状态<select className={input} value={availability} onChange={(e) => { setAvailability(e.target.value); setSelected([]); }}><option value="all">全部</option><option value="open">已开放</option><option value="closed">未开放</option></select></label></div>
      <TagCascader dimensions={demoDimensions} nodes={tags.map((tag) => ({ id: tag.id, name: tag.name, dimension_id: tag.dimension, parent_id: tag.parent, path: tagPath(tag, tags) }))} value={filters} onChange={(ids) => { setFilters(ids); setSelected([]); }} />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={untagged} onChange={(e) => { setUntagged(e.target.checked); setSelected([]); }} />仅看未打标</label>
      <div className="flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-sm"><input ref={(node) => { all.current = node; if (node) node.indeterminate = selected.length > 0 && selected.length < filtered.length; }} type="checkbox" aria-label="全选本页案例" checked={filtered.length > 0 && selected.length === filtered.length} disabled={!filtered.length} onChange={(e) => setSelected(e.target.checked ? filtered.map((item) => item.id) : [])} />本页全选</label><button className={button} disabled={!selected.length} onClick={() => batch("tag")}>AI 一键打标（{selected.length}）</button><button className={button} disabled={!selected.length} onClick={() => batch("open")}>批量开放</button><button className={button} disabled={!selected.length} onClick={() => batch("close")}>批量关闭</button></div>
      {message && <p role="status" className="text-sm text-emerald-800">{message}</p>}
      <p className="text-sm text-slate-500">共 {filtered.length} 条合成案例</p>
      {filtered.map((item) => <article className="rounded-lg border p-4" key={item.id}><div className="flex items-start gap-3"><input aria-label={`选择案例 ${item.title}`} className="mt-1" type="checkbox" checked={selected.includes(item.id)} onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} /><div className="min-w-0 flex-1"><Link className="break-words font-medium text-emerald-900 underline" href={`${base}/${item.id}`}>{item.title}</Link><p className="mt-2 text-xs text-slate-500">{item.enabled ? "已开放" : "未开放"}</p><p className="mt-2 text-sm text-slate-600">{item.tags.map((id) => tagPath(tags.find((tag) => tag.id === id)!, tags)).join(" · ") || "未打标（全局）"}</p></div></div></article>)}
      {!filtered.length && <p className="text-sm text-slate-500">没有匹配的案例。</p>}
    </section>
    <ShowcaseReceipts kind="case" />
    <CaseConversation />
    <details className={card}><summary className="cursor-pointer text-sm font-medium">待补充需求与重复检查</summary><p className="mt-3 text-sm leading-6 text-slate-500">正式工作台保存未匹配问题，按问题和背景聚合，供人工补充；完全重复材料在问答时合并。此展示使用两条不同的合成案例，不读取正式需求或重复记录。</p></details>
  </>;
}

function CaseDetail({ record }: { record: DemoCase }) {
  const { tags, setCases } = useShowcaseLiterature();
  const [editing, setEditing] = useState(false);
  if (editing) return <CaseEditor record={record} onDone={() => setEditing(false)} />;
  return <>
    <div className="flex flex-wrap gap-3"><Link className={button} href={base}>返回案例与措施</Link><button className={primary} onClick={() => setEditing(true)}>编辑案例示例</button><button className={button} onClick={() => setCases((items) => items.map((item) => item.id === record.id ? { ...item, enabled: !item.enabled } : item))}>{record.enabled ? "关闭案例" : "开放案例"}</button></div>
    <section className={`${card} space-y-4`}><p className="text-xs text-slate-500">{record.enabled ? "已开放" : "未开放"} · 合成示例</p><h2 className="text-lg font-semibold">{record.title}</h2><CaseBodyEditor body={record.body} format={record.body_format ?? "plain"} /><h3 className="font-medium">解释与适用条件</h3><p className="whitespace-pre-wrap text-sm leading-7">{record.explanation || "尚未填写"}</p><p className="text-sm text-slate-500">来源：{record.source || "尚未填写"}</p><div className="flex flex-wrap gap-2">{record.tags.map((id) => <Link key={id} className="rounded bg-emerald-50 px-2 py-1 text-xs text-emerald-800 underline" href={`${base}?tag=${id}`}>{tagPath(tags.find((tag) => tag.id === id)!, tags)}</Link>)}</div></section>
  </>;
}

function CaseEditor({ record, onDone }: { record?: DemoCase; onDone?: () => void }) {
  const { tags, setCases } = useShowcaseLiterature();
  const router = useRouter();
  const [form, setForm] = useState<DemoCase>(record ?? { id: "", title: "", body: "", explanation: "", source: "", enabled: false, tags: [] });
  const [suggestion, setSuggestion] = useState("");
  const [error, setError] = useState("");
  const hasBody = useRef(!!record?.body.trim());
  return <form className={`${card} space-y-4`} onSubmit={(event) => {
    event.preventDefault();
    if (!form.title.trim() || !hasBody.current) { setError("请填写标题和案例原文。"); return; }
    const saved = { ...form, title: form.title.trim(), id: record?.id ?? `CASE-${crypto.randomUUID()}` };
    setCases((items) => record ? items.map((item) => item.id === record.id ? saved : item) : [saved, ...items]);
    if (onDone) onDone(); else router.push(`${base}/${saved.id}`);
  }}>
    <h2 className="font-semibold">{record ? "编辑案例示例" : "新增案例示例"}</h2>
    <label className="block text-sm">案例标题<input required maxLength={500} className={input} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
    <p id="case-body-help" className="text-sm text-slate-500">案例与措施原文：可插入表格、列表并保留结构。</p><CaseBodyEditor body={form.body} format={form.body_format ?? "plain"} onChange={(html, hasText) => { hasBody.current = hasText; setForm((old) => ({ ...old, body: html, body_format: "html" })); setSuggestion(""); }} />
    <button className={button} type="button" disabled={!form.body.trim()} onClick={() => setSuggestion("【预置解释初稿】请先核对原文中的地区、作物与措施，再判断当地是否适用；材料缺少效果数据时，不推断改善幅度。")}>AI 解释初稿示例</button>
    {suggestion && <div className="space-y-3 rounded-lg bg-amber-50 p-4"><p className="text-sm leading-6">{suggestion}</p><button type="button" className={button} onClick={() => { setForm({ ...form, explanation: suggestion }); setSuggestion(""); }}>采用解释初稿</button><button type="button" className={`${button} ml-2`} onClick={() => setSuggestion("")}>放弃初稿</button></div>}
    <label className="block text-sm">解释与适用条件<textarea aria-label="解释与适用条件" className={input} rows={4} maxLength={20000} value={form.explanation} onChange={(e) => setForm({ ...form, explanation: e.target.value })} /></label>
    <label className="block text-sm">来源说明<textarea aria-label="来源说明" className={input} rows={2} maxLength={2000} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></label>
    <TagCascader dimensions={demoDimensions} nodes={tags.map((tag) => ({ id: tag.id, name: tag.name, dimension_id: tag.dimension, parent_id: tag.parent, path: tagPath(tag, tags) }))} value={form.tags} onChange={(ids) => setForm({ ...form, tags: ids })} mode="assign" />
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />开放给案例问答</label>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <div className="flex gap-3"><button className={primary}>保存案例示例</button><button type="button" className={button} onClick={() => { if (window.confirm("放弃尚未保存的案例修改？")) { if (onDone) onDone(); else router.push(base); } }}>取消</button></div>
  </form>;
}

function CaseConversation() {
  const { cases } = useShowcaseLiterature();
  const [skill, setSkill] = useState("auto");
  const [turns, setTurns] = useState<{ question: string; answer: string; sources: string[]; route: string }[]>([]);
  const [scope, setScope] = useState<string[]>([]);
  function ask(followUp: boolean) {
    const available = cases.filter((item) => item.enabled && (!followUp || scope.includes(item.id)));
    const chosen = followUp ? available.slice(0, 1) : available.slice(0, 2);
    const question = followUp ? "第一个案例的措施需要注意什么？" : skill === "explain" ? "解释开放案例的适用条件" : "找两个开放案例并比较措施差异";
    const route = chosen.length ? skill === "reference" ? "case_reference" : followUp || skill === "explain" ? "case_explanation" : "case_reference → case_explanation" : "case_reference · 无匹配";
    const answer = chosen.length ? `【预置问答演示】本轮可用材料：${chosen.map((item) => item.title).join("、")}。${chosen.length < 2 && !followUp && skill !== "explain" ? "目前只有一个开放案例，不能据此进行两案例比较。" : "比较时应核对作物、地区和措施的差异。"}需依据原文和当地条件判断适用性，合成材料不支持实际效果结论。` : "当前范围内没有仍开放的案例。请补充材料或开放示例后重试；这里不生成缺少依据的解释。";
    setTurns((items) => [...items, { question, answer, sources: chosen.map((item) => item.title), route }]);
    if (!followUp) setScope(chosen.map((item) => item.id));
  }
  return <section className={`${card} space-y-4`} aria-label="案例问答演示"><h2 className="font-semibold">案例参考、解释与多轮追问</h2><p className="text-sm leading-6 text-slate-500">用固定问题体验路由与引用范围，回答为预置演示文案。每次操作重新检查开放状态。</p>
    <label className="block text-sm">验证能力<select className={input} value={skill} onChange={(e) => { setSkill(e.target.value); setTurns([]); setScope([]); }}><option value="auto">自动识别</option><option value="reference">案例与措施参考</option><option value="explain">案例与措施解释</option></select></label>
    <div className="flex flex-wrap gap-2"><button className={primary} onClick={() => ask(false)}>运行固定问题示例</button><button className={button} disabled={!scope.length} onClick={() => ask(true)}>追问第一个案例</button><button className={button} onClick={() => { setTurns([]); setScope([]); }}>新对话</button></div>
    {turns.map((turn, index) => <article key={index} className="space-y-2 rounded-lg border p-4"><h3 className="text-sm font-medium">{index + 1}. {turn.question}</h3><p className="text-sm leading-7">{turn.answer}</p><p className="text-xs text-slate-500">演示路由：{turn.route}</p><p className="text-xs text-slate-500">合成来源：{turn.sources.join("；") || "无"}</p></article>)}
  </section>;
}

export function ShowcaseQuestions() {
  const { questions, setQuestions } = useShowcaseLiterature();
  const [draft, setDraft] = useState<DemoQuestion | null>(null);
  return <div className="space-y-4"><ShowcaseExperienceNotice href="/showcase/starred-questions" />
    <section className={card}><div className="flex flex-wrap justify-between gap-3"><div><h2 className="font-semibold">集中记录专业问题和人工答案</h2><p className="mt-2 text-sm leading-6 text-slate-500">正式工作台对所有登录角色共享保存，编辑有版本冲突保护。星标不会自动提问，也不自动进入检索材料或评测。</p></div><button className={primary} onClick={() => setDraft({ id: "", question: "", answer: "" })}>新增问题</button></div></section>
    {draft && <form aria-label="星标问题编辑" className={`${card} space-y-4`} onSubmit={(event) => {
      event.preventDefault(); if (!draft.question.trim()) return;
      const saved = { ...draft, question: draft.question.trim(), id: draft.id || `STAR-${crypto.randomUUID()}` };
      setQuestions((items) => draft.id ? items.map((item) => item.id === draft.id ? saved : item) : [...items, saved]); setDraft(null);
    }}><label className="block text-sm">问题<textarea aria-label="问题" className={input} required rows={3} maxLength={20000} value={draft.question} onChange={(e) => setDraft({ ...draft, question: e.target.value })} /></label><label className="block text-sm">对应答案（选填）<textarea aria-label="对应答案（选填）" className={input} rows={5} maxLength={100000} value={draft.answer} onChange={(e) => setDraft({ ...draft, answer: e.target.value })} /></label><div className="flex gap-3"><button className={primary} disabled={!draft.question.trim()}>保存问题示例</button><button type="button" className={button} onClick={() => setDraft(null)}>取消</button></div></form>}
    <p className="text-sm text-slate-500">共 {questions.length} 条示例问题</p>
    {questions.map((item, index) => <article key={item.id} className={`${card} space-y-3`}><div className="flex justify-between"><h2 className="text-sm font-semibold">问题 {index + 1}</h2><button className="text-sm text-emerald-800 underline" onClick={() => setDraft({ ...item })}>编辑</button></div><p className="whitespace-pre-wrap break-words text-sm leading-7">{item.question}</p><h3 className="border-t pt-3 text-xs text-slate-500">人工整理答案 · 体验数据</h3><p className="whitespace-pre-wrap break-words text-sm leading-7">{item.answer || "暂无答案"}</p></article>)}
  </div>;
}
