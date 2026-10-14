"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useEvaluationSession } from "./evaluation-shell";
import { apiBaseUrl } from "@/lib/api";
import { AnswerCard } from "./chat/answer-card";
import { CaseBodyEditor, type BodyFormat } from "./case-body-editor";
import type { ChatResponse } from "@/lib/types";

type Form = { title: string; body: string; body_format: BodyFormat; explanation: string; supplementary: string; source: string; enabled: boolean };
type Case = Form & { id: string; revision: number; created_by: string; created_at: string; updated_by: string; updated_at: string };
type Row = Pick<Case, "id" | "title" | "enabled" | "revision" | "updated_by" | "updated_at"> & { summary: string; has_explanation: boolean };
type Listing = { items: Row[]; total: number; page: number; page_size: number };
const empty: Form = { title: "", body: "", body_format: "plain", explanation: "", supplementary: "", source: "", enabled: false };
const base = "/evaluation/case-library";
const input = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-emerald-600";
const button = "rounded-lg border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50";
const primary = `${button} bg-emerald-700 text-white hover:bg-emerald-800`;
const fmt = (date: string) => new Date(date).toLocaleString("zh-CN");
const json = (method: string, value: unknown) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) });
const fields = (record: Case): Form => ({ title: record.title, body: record.body, body_format: record.body_format || "plain", explanation: record.explanation, supplementary: record.supplementary, source: record.source, enabled: Boolean(record.enabled) });

export function CaseLibraryWorkspace({ detail = "", edit = false }: { detail?: string; edit?: boolean }) {
  const { token } = useEvaluationSession();
  const router = useRouter();
  const [record, setRecord] = useState<Case | null>(null);
  const [form, setForm] = useState<Form>(empty);
  const [saved, setSaved] = useState<Form>(empty);
  const [list, setList] = useState<Listing | null>(null);
  const [keyword, setKeyword] = useState("");
  const [search, setSearch] = useState("");
  const [availability, setAvailability] = useState("all");
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [draft, setDraft] = useState<{ text: string; body: string; body_format: BodyFormat; supplementary: string } | null>(null);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [skill, setSkill] = useState("reference");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<ChatResponse | null>(null);
  const [testing, setTesting] = useState(false);
  const editing = detail === "new" || edit;
  const dirty = editing && (JSON.stringify(form) !== JSON.stringify(saved) || !!draft);
  const dirtyRef = useRef(dirty);
  const bodyHasText = useRef(true);
  const validationSession = useRef<string | null>(null);
  useEffect(() => { dirtyRef.current = dirty; }, [dirty]);
  const request = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const response = await fetch(`${apiBaseUrl}/api${path}`, { ...init, cache: "no-store", headers: { Authorization: `Bearer ${token}`, ...init.headers } });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new CustomEvent("evaluation-session-expired", { detail: { token } }));

      throw Object.assign(new Error(data?.detail?.message || (Array.isArray(data?.detail) ? "请检查字段是否为空或超过长度限制。" : "操作失败，请重试。")), { status: response.status, code: data?.detail?.code });
    }
    return data;
  }, [token]);
  useEffect(() => {
    let cancelled = false;
    if (detail === "new") return;
    const query = new URLSearchParams({ keyword: search, availability, page: String(page) });
    const path = detail ? `/case-library/${detail}` : `/case-library?${query}`;
    request<Case | Listing>(path).then((value) => {
      if (cancelled) return;
      if ("items" in value) setList(value);
      else { setRecord(value); setForm(fields(value)); setSaved(fields(value)); }
    }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [request, detail, availability, search, page, refresh]);
  useEffect(() => {
    const leave = (event: BeforeUnloadEvent) => { if (dirtyRef.current) { event.preventDefault(); event.returnValue = ""; } };
    const click = (event: MouseEvent) => {
      const link = (event.target as Element).closest?.("a[href]");
      if (!dirtyRef.current || !link || link.getAttribute("target") === "_blank" || event.ctrlKey || event.metaKey) return;
      if (!window.confirm("有未保存修改，确认离开？")) { event.preventDefault(); event.stopPropagation(); }
    };
    const navigation = (window as Window & { navigation?: EventTarget }).navigation;
    const navigate = (raw: Event) => {
      const event = raw as Event & { navigationType: string; destination: { sameDocument: boolean }; hashChange: boolean };
      if (dirtyRef.current && event.navigationType === "traverse" && event.destination.sameDocument && !event.hashChange && event.cancelable && !window.confirm("有未保存修改，确认离开？")) event.preventDefault();
    };
    const href = window.location.href, state = window.history.state;
    const pop = (event: PopStateEvent) => {
      if (dirtyRef.current && window.location.href !== href && !window.confirm("有未保存修改，确认离开？")) {
        event.stopImmediatePropagation(); window.history.pushState(state, "", href);
      }
    };
    window.addEventListener("beforeunload", leave);
    document.addEventListener("click", click, true);
    if (navigation) navigation.addEventListener("navigate", navigate);
    else window.addEventListener("popstate", pop, true);
    return () => {
      window.removeEventListener("beforeunload", leave); document.removeEventListener("click", click, true);
      if (navigation) navigation.removeEventListener("navigate", navigate);
      else window.removeEventListener("popstate", pop, true);
    };
  }, []);
  function change<K extends keyof Form>(key: K, value: Form[K]) { setForm((old) => ({ ...old, [key]: value })); }
  async function save(event: FormEvent) {
    event.preventDefault(); setError("");
    if (!bodyHasText.current) { setError("请填写案例与措施原文。"); document.getElementById("case-body")?.focus(); return; }
    for (const key of ["title", "body"] as const) if (!form[key].trim()) {
      setError(key === "title" ? "请填写标题。" : "请填写案例与措施原文。"); document.getElementById(`case-${key}`)?.focus(); return;
    }
    setBusy(true);
    try {
      const result = await request<Case>(`/case-library${record ? `/${record.id}` : ""}`, json(record ? "PUT" : "POST", { ...form, ...(record ? { expected_revision: record.revision } : {}) }));
      setSaved(fields(result)); setForm(fields(result)); setDraft(null); dirtyRef.current = false;
      router.push(`${base}/${result.id}`);
    } catch (e) { setError((e as Error).message); if ((e as { code?: string }).code === "case_conflict") setConflict(true); }
    finally { setBusy(false); }
  }
  async function reloadLatest() {
    if (!record || !window.confirm("加载最新版本将替换当前未保存的输入，请先复制需要保留的修改。确认继续？")) return;
    setBusy(true); setError("");
    try {
      const latest = await request<Case>(`/case-library/${record.id}`);
      bodyHasText.current = true; setRecord(latest); setForm(fields(latest)); setSaved(fields(latest)); setDraft(null); setConflict(false);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function generate() {
    if (!form.body.trim() || !bodyHasText.current) { setError("请先填写案例与措施原文。"); document.getElementById("case-body")?.focus(); return; }
    setGenerating(true); setError("");
    const current = { body: form.body, body_format: form.body_format, supplementary: form.supplementary };
    try { const result = await request<{ draft: string }>("/case-library/explanation-draft", json("POST", current)); setDraft({ text: result.draft, ...current }); }
    catch (e) { setError((e as Error).message); if ((e as { code?: string }).code === "case_conflict") setConflict(true); }
    finally { setGenerating(false); }
  }
  async function remove(item: Row | Case) {
    if (!window.confirm(`确认删除“${item.title}”？删除后 Agent 将不能继续调用。`)) return;
    setBusy(true); setError("");
    try { await request(`/case-library/${item.id}`, json("DELETE", { expected_revision: item.revision })); if (detail) router.push(base); else { setPage(1); setRefresh((v) => v + 1); } }
    catch (e) { setError((e as Error).message); if ((e as { code?: string }).code === "case_conflict") setConflict(true); }
    finally { setBusy(false); }
  }
  async function toggle() {
    if (!record) return;
    setBusy(true); setError("");
    try { const result = await request<Case>(`/case-library/${record.id}/availability`, json("PATCH", { enabled: !record.enabled, expected_revision: record.revision })); setRecord(result); }
    catch (e) { setError((e as Error).message); if ((e as { code?: string }).code === "case_conflict") setConflict(true); }
    finally { setBusy(false); }
  }
  async function test(event: FormEvent) {
    event.preventDefault(); if (!question.trim()) return;
    setTesting(true); setError(""); setAnswer(null);
    validationSession.current ??= globalThis.crypto?.randomUUID?.() ?? `case_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const sessionId = validationSession.current;
    try { setAnswer(await request<ChatResponse>("/chat", json("POST", { query: question, case_skill: skill, case_ids: record ? [record.id] : [], session_id: sessionId }))); }
    catch (e) { setError((e as Error).message); if ((e as { code?: string }).code === "case_conflict") setConflict(true); }
    finally { setTesting(false); }
  }
  return <section className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-2xl font-semibold">{editing ? (record ? "编辑案例" : "新增案例") : detail ? record?.title || "案例详情" : "案例与措施"}</h1><p className="mt-2 text-sm text-slate-500">录清案例与措施，保存解释，通过参考与解释验证效果。</p></div>{!detail && <Link className={primary} href={`${base}/new`}>新增案例</Link>}</header>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {conflict && <p className="text-sm text-amber-900">请先在<Link target="_blank" className="underline" href={detail ? `${base}/${detail}` : base}>新窗口查看最新内容</Link>并复制需要保留的修改。{editing && record && <button type="button" className={`${button} ml-3`} disabled={busy || generating} onClick={reloadLatest}>加载最新版本</button>}</p>}
    {editing && (detail === "new" || record) ? <form onSubmit={save} className="rounded-xl border bg-white p-5"><fieldset disabled={busy} className="space-y-5">
      <p className="text-sm text-slate-600">请尽量保留案例与措施的原意。材料中没有的信息无需补齐，可在后续使用中逐步完善。</p>
      <label className="block space-y-2" htmlFor="case-title"><span>标题 *</span><input id="case-title" className={input} required maxLength={500} value={form.title} onChange={(e) => change("title", e.target.value)} /></label>
      <div className="grid min-w-0 gap-6 lg:grid-cols-2">
      <div className="min-w-0 space-y-3"><label className="block" htmlFor="case-body">案例与措施原文 *</label>
        <CaseBodyEditor body={form.body} format={form.body_format} disabled={busy} onChange={(body, hasText) => { bodyHasText.current = hasText; setForm((old) => ({ ...old, body, body_format: "html" })); }} />
        <p id="case-body-help" className="text-xs leading-6 text-slate-500">可粘贴 Word 表格，支持小标题、列表及增删行列。建议保留地区背景、作物、不同模式和原材料说明；空白单元格无需补齐。</p>
        {(form.supplementary || saved.supplementary) && <div className="space-y-2 rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-600">此案例原有补充信息已保留，可编辑；新案例请将背景和条件写入正文。</p><label className="block space-y-2" htmlFor="case-supplementary"><span>原有补充信息</span><textarea id="case-supplementary" className={input} rows={4} maxLength={10000} value={form.supplementary} onChange={(e) => change("supplementary", e.target.value)} /></label></div>}
      </div>
      <div className="min-w-0 space-y-4">
      {form.explanation && (form.body !== saved.body || form.supplementary !== saved.supplementary) && <p role="status" className="text-sm text-amber-800">案例内容已修改，请检查解释是否仍与原文一致。</p>}
      <button type="button" className={button} disabled={generating || busy} onClick={generate}>{generating ? "正在生成解释…" : "AI 生成解释"}</button>
      {draft && <div className="space-y-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4"><h2 className="font-medium">AI 解释初稿 · 尚未采用或保存</h2><p className="whitespace-pre-wrap text-sm leading-7">{draft.text}</p>{(draft.body !== form.body || draft.supplementary !== form.supplementary) && <p className="text-sm text-amber-900">生成后案例内容已修改，请核对新稿。</p>}<div className="flex gap-3"><button type="button" className={button} onClick={() => { if (form.explanation && !window.confirm("确认用此初稿替换解释编辑区？保存后才会生效。")) return; change("explanation", draft.text); setDraft(null); }}>采用初稿</button><button type="button" className={button} onClick={() => setDraft(null)}>放弃初稿</button></div></div>}
      <label className="block space-y-2" htmlFor="case-explanation"><span>解释与说明（选填）</span><textarea id="case-explanation" className={input} rows={18} maxLength={30000} value={form.explanation} onChange={(e) => change("explanation", e.target.value)} /></label>
      </div></div>
      <label className="block space-y-2" htmlFor="case-source"><span>来源说明／链接（选填）</span><textarea id="case-source" className={input} rows={2} maxLength={4000} value={form.source} onChange={(e) => change("source", e.target.value)} /></label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={form.enabled} onChange={(e) => change("enabled", e.target.checked)} />开放给 Agent 使用</label>
      <div className="flex gap-3"><button className={primary} disabled={busy || generating}>{busy ? "正在保存…" : "保存"}</button><Link className={button} href={record ? `${base}/${record.id}` : base}>取消</Link></div>
    </fieldset></form> : detail ? record && <div className="space-y-5 rounded-xl border bg-white p-5"><div className="flex flex-wrap items-center gap-3"><span className="text-sm">{record.enabled ? "已开放 · 已生效" : "未开放"}</span><Link className={button} href={`${base}/${record.id}?edit=1`}>编辑</Link><button className={button} disabled={busy} onClick={toggle}>{record.enabled ? "关闭 Agent 使用" : "开放 Agent 使用"}</button><button className={button} disabled={busy} onClick={() => remove(record)}>删除</button></div><div className="grid min-w-0 gap-6 lg:grid-cols-2"><div className="min-w-0"><h2 className="mb-2 font-medium">案例与措施原文</h2><CaseBodyEditor body={record.body} format={record.body_format || "plain"} /></div><div className="min-w-0"><h2 className="mb-2 font-medium">解释与说明</h2><p className="whitespace-pre-wrap break-words text-sm leading-7">{record.explanation || "未填写"}</p></div></div>{([["原有补充信息", record.supplementary], ["来源说明／链接", record.source]]).filter(([, value]) => value).map(([label, value]) => <div key={label}><h2 className="mb-2 font-medium">{label}</h2><p className="whitespace-pre-wrap break-words text-sm leading-7">{value || "未填写"}</p></div>)}<p className="text-xs leading-6 text-slate-500">{record.id}<br />创建：{record.created_by} · {fmt(record.created_at)}<br />最近修改：{record.updated_by} · {fmt(record.updated_at)}</p></div> : <>
      <form className="flex flex-wrap gap-3" onSubmit={(e) => { e.preventDefault(); setSearch(keyword); setPage(1); }}><input aria-label="按标题搜索" placeholder="按标题关键词搜索" className={`${input} max-w-sm`} value={keyword} onChange={(e) => setKeyword(e.target.value)} /><button className={button}>搜索</button><select aria-label="开放状态" className={button} value={availability} onChange={(e) => { setAvailability(e.target.value); setPage(1); }}><option value="all">全部</option><option value="enabled">已开放</option><option value="disabled">未开放</option></select></form>
      <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-left text-sm"><thead className="bg-slate-50"><tr>{["标题与正文摘要", "解释", "Agent 使用", "最近修改", "操作"].map((label) => <th className="p-4" key={label}>{label}</th>)}</tr></thead><tbody>{list?.items.map((item) => <tr className="border-t" key={item.id}><td className="max-w-lg p-4"><Link className="font-medium text-emerald-800" href={`${base}/${item.id}`}>{item.title}</Link><p className="mt-2 line-clamp-2 whitespace-pre-wrap text-slate-500">{item.summary}</p></td><td className="p-4 whitespace-nowrap">{item.has_explanation ? "已填写" : "未填写"}</td><td className="p-4 whitespace-nowrap">{item.enabled ? "已开放" : "未开放"}</td><td className="p-4 whitespace-nowrap">{item.updated_by}<br /><span className="text-xs text-slate-500">{fmt(item.updated_at)}</span></td><td className="p-4"><div className="flex gap-3 whitespace-nowrap"><Link href={`${base}/${item.id}`}>查看</Link><Link href={`${base}/${item.id}?edit=1`}>编辑</Link><button disabled={busy} onClick={() => remove(item)}>删除</button></div></td></tr>)}</tbody></table>{(!list || !list.items.length) && <p className="p-8 text-center text-sm text-slate-500">{list ? "暂无符合条件的案例" : "正在加载案例…"}</p>}</div>
      {list && <div className="flex items-center justify-end gap-4 text-sm"><span>共 {list.total} 条 · 第 {page} 页</span><button className={button} disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><button className={button} disabled={page * list.page_size >= list.total} onClick={() => setPage(page + 1)}>下一页</button></div>}
    </>}
    {!editing && <div className="space-y-4 rounded-xl border bg-white p-5"><h2 className="font-medium">Skill 效果验证</h2><p className="text-sm text-slate-500">{record ? "使用本案例的已保存、已开放内容。" : "参考已开放案例，或直接解释粘贴的专业文字。"}本次输入与回答不会自动入库。</p><form onSubmit={test} className="space-y-3"><select aria-label="选择 Skill" className={button} value={skill} onChange={(e) => setSkill(e.target.value)}><option value="reference">案例与措施参考</option><option value="explain">案例与措施解释</option></select><textarea aria-label="验证问题或专业文字" required maxLength={24000} className={input} rows={4} placeholder="输入场景、问题或需要解释的文字" value={question} onChange={(e) => setQuestion(e.target.value)} /><button className={primary} disabled={testing || (!!detail && !record)}>{testing ? "正在回答…" : "验证效果"}</button></form>{answer && <AnswerCard response={answer} scope="case-validation" />}</div>}
  </section>;
}
