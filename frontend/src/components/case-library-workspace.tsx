"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useEvaluationSession } from "./evaluation-shell";
import { apiBaseUrl } from "@/lib/api";
import { CaseBatchTagging } from "./case-batch-tagging";
import { CaseBodyEditor, type BodyFormat } from "./case-body-editor";
import { TagCascader, type TaxonomyNode } from "./literature-taxonomy";

type Form = { title: string; body: string; body_format: BodyFormat; explanation: string; supplementary: string; source: string; enabled: boolean; tag_ids: string[] };
type Case = Form & { id: string; revision: number; created_by: string; created_at: string; updated_by: string; updated_at: string };
type Row = Pick<Case, "id" | "title" | "enabled" | "revision" | "updated_by" | "updated_at" | "tag_ids"> & { summary: string; has_explanation: boolean };
type Listing = { items: Row[]; total: number; page: number; page_size: number };
const empty: Form = { title: "", body: "", body_format: "plain", explanation: "", supplementary: "", source: "", enabled: false, tag_ids: [] };
const base = "/evaluation/case-library";
const input = "wb-field";
const button = "wb-button";
const primary = "wb-button wb-button-primary";
const fmt = (date: string) => new Date(date).toLocaleString("zh-CN");
const json = (method: string, value: unknown) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) });
const fields = (record: Case): Form => ({ title: record.title, body: record.body, body_format: record.body_format || "plain", explanation: record.explanation, supplementary: record.supplementary, source: record.source, enabled: Boolean(record.enabled), tag_ids: record.tag_ids || [] });

type Taxonomy = { dimensions: { id: string; name: string; enabled: boolean | number; selection: string; required: boolean | number }[]; tags: TaxonomyNode[] };

export function CaseLibraryWorkspace({ detail = "", edit = false, tagId = "" }: { detail?: string; edit?: boolean; tagId?: string }) {
  const { token, user } = useEvaluationSession();
  const canEdit = user.role === "developer";
  const router = useRouter();
  const [record, setRecord] = useState<Case | null>(null);
  const [form, setForm] = useState<Form>(empty);
  const [saved, setSaved] = useState<Form>(empty);
  const [list, setList] = useState<Listing | null>(null);
  const [keyword, setKeyword] = useState("");
  const [search, setSearch] = useState("");
  const [availability, setAvailability] = useState("all");
  const [page, setPage] = useState(1);
  const [taxonomy, setTaxonomy] = useState<Taxonomy>({ dimensions: [], tags: [] });
  const [taxonomyError, setTaxonomyError] = useState("");
  const [taxonomyLoading, setTaxonomyLoading] = useState(true);
  const [taxonomyRefresh, setTaxonomyRefresh] = useState(0);
  const [tagFilter, setTagFilter] = useState<string[]>(tagId ? [tagId] : []);
  const [tagStatus, setTagStatus] = useState("all");
  const [selection, setSelection] = useState<{ key: string; ids: string[] }>({ key: "", ids: [] });
  const selectionKey = JSON.stringify([search, availability, page, tagFilter, tagStatus]);
  const selectedIds = selection.key === selectionKey ? selection.ids.filter((id) => list?.items.some((item) => item.id === id)) : [];
  const [listSelectionKey, setListSelectionKey] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [draft, setDraft] = useState<{ text: string; body: string; body_format: BodyFormat; supplementary: string } | null>(null);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [coverage, setCoverage] = useState<{ gaps: { fingerprint: string; question: string; context: string; occurrences: number }[]; duplicates: { id: string; title: string }[][] } | null>(null);
  const editing = canEdit && (detail === "new" || edit);
  const dirty = editing && (JSON.stringify(form) !== JSON.stringify(saved) || !!draft);
  const dirtyRef = useRef(dirty);
  const bodyHasText = useRef(true);
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
    request<Taxonomy>("/case-library/taxonomy").then((value) => {
      if (!cancelled) { setTaxonomy(value); setTaxonomyError(""); }
    }).catch((error) => { if (!cancelled) setTaxonomyError(error.message); })
      .finally(() => { if (!cancelled) setTaxonomyLoading(false); });
    return () => { cancelled = true; };
  }, [request, taxonomyRefresh]);
  useEffect(() => {
    let cancelled = false;
    if (detail === "new") return;
    const query = new URLSearchParams({ keyword: search, availability, page: String(page), tags: tagFilter.join(","), tag_status: tagStatus });
    const path = detail ? `/case-library/${detail}` : `/case-library?${query}`;
    request<Case | Listing>(path).then((value) => {
      if (cancelled) return;
      if ("items" in value) { setListSelectionKey(selectionKey); setList(value); }
      else { setRecord(value); setForm(fields(value)); setSaved(fields(value)); }
    }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [request, detail, availability, search, page, refresh, tagFilter, tagStatus, selectionKey]);
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
  function tagsView(ids: string[] = []) {
    if (!ids.length) return <span className="text-sm text-slate-500">未打标</span>;
    return <div className="flex flex-wrap gap-2">{ids.map((id) => {
      const tag = taxonomy.tags.find((item) => item.id === id);
      const dimension = taxonomy.dimensions.find((item) => item.id === tag?.dimension_id);
      const disabled = tag && (!tag.enabled || !dimension?.enabled);
      return <span key={id} className="rounded bg-emerald-50 px-2 py-1 text-xs text-emerald-900">
        {tag ? `${dimension?.name || ""}：${tag.path}` : taxonomyLoading ? "标签加载中…" : taxonomyError ? "标签暂不可用" : "已失效标签"}{disabled ? "（已停用）" : ""}
      </span>;
    })}</div>;
  }
  const caseDimensions = taxonomy.dimensions.map((dimension) => ({ ...dimension, required: false }));
  if (detail === "new" && !canEdit) return <div className="wb-panel"><p role="alert">新增案例需要开发者权限。</p><Link className="wb-button mt-3" href={base}>返回案例列表</Link></div>;

  return <section className={detail ? "mx-auto max-w-6xl space-y-6 p-4 md:p-8" : "min-w-0 space-y-3"}>
    {detail && <header><h2 className="text-lg font-semibold">{editing ? (record ? "编辑案例" : "新增案例") : record?.title || "案例详情"}</h2></header>}
    {taxonomyError && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{taxonomyError} <button type="button" className="underline" onClick={() => { setTaxonomyLoading(true); setTaxonomyRefresh((value) => value + 1); }}>重试加载标签</button></p>}
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {conflict && <p className="text-sm text-amber-900">请先在<Link target="_blank" className="underline" href={detail ? `${base}/${detail}` : base}>新窗口查看最新内容</Link>并复制需要保留的修改。{editing && record && <button type="button" className={`${button} ml-3`} disabled={busy || generating} onClick={reloadLatest}>加载最新版本</button>}</p>}
    {editing && (detail === "new" || record) ? <form onSubmit={save} className="wb-panel"><fieldset disabled={busy} className="space-y-5">
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
      <section aria-label="分类标签" className="space-y-3 rounded-lg border p-4">
        <h2 className="font-medium">分类标签（选填）</h2>
        <p className="text-xs text-slate-500">使用标签管理中的公共维度与标签，保存后生效。文献登记必填规则不适用于案例。</p>
        <fieldset disabled={taxonomyLoading || !!taxonomyError}>
          <TagCascader dimensions={caseDimensions} nodes={taxonomy.tags} value={form.tag_ids} onChange={(ids) => change("tag_ids", ids)} mode="assign" />
        </fieldset>
      </section>
      <label className="flex items-center gap-2"><input type="checkbox" checked={form.enabled} onChange={(e) => change("enabled", e.target.checked)} />开放给 Agent 使用</label>
      <div className="flex gap-3"><button className={primary} disabled={busy || generating}>{busy ? "正在保存…" : "保存"}</button><Link className={button} href={record ? `${base}/${record.id}` : base}>取消</Link></div>
    </fieldset></form> : detail ? record && <div className="space-y-5 wb-panel"><div className="flex flex-wrap items-center gap-3"><span className="text-sm">{record.enabled ? "已开放 · 已生效" : "未开放"}</span>{canEdit && <Link className={button} href={`${base}/${record.id}?edit=1`}>编辑</Link>}{canEdit && <button className={button} disabled={busy} onClick={toggle}>{record.enabled ? "关闭 Agent 使用" : "开放 Agent 使用"}</button>}{canEdit && <button className={button} disabled={busy} onClick={() => remove(record)}>删除</button>}</div><section aria-label="分类标签" className="space-y-2"><h2 className="font-medium">分类标签</h2>{tagsView(record.tag_ids)}</section><div className="grid min-w-0 gap-6 lg:grid-cols-2"><div className="min-w-0"><h2 className="mb-2 font-medium">案例与措施原文</h2><CaseBodyEditor body={record.body} format={record.body_format || "plain"} /></div><div className="min-w-0"><h2 className="mb-2 font-medium">解释与说明</h2><p className="whitespace-pre-wrap break-words text-sm leading-7">{record.explanation || "未填写"}</p></div></div>{([["原有补充信息", record.supplementary], ["来源说明／链接", record.source]]).filter(([, value]) => value).map(([label, value]) => <div key={label}><h2 className="mb-2 font-medium">{label}</h2><p className="whitespace-pre-wrap break-words text-sm leading-7">{value || "未填写"}</p></div>)}<p className="text-xs leading-6 text-slate-500">{record.id}<br />创建：{record.created_by} · {fmt(record.created_at)}<br />最近修改：{record.updated_by} · {fmt(record.updated_at)}</p></div> : <>
      <section aria-label="筛选案例" className="flex flex-wrap items-center gap-2">
        {canEdit && <Link className={`${primary} shrink-0`} href={`${base}/new`}>新增案例</Link>}
        <form className="flex min-w-0 flex-1 basis-56 items-center gap-2" onSubmit={(e) => { e.preventDefault(); setSelection({ key: "", ids: [] }); setSearch(keyword); setPage(1); }}><input aria-label="关键词搜索" placeholder="搜索案例" title="搜索标题、正文、解释、补充信息和来源" className={`${input} min-w-0`} value={keyword} onChange={(e) => setKeyword(e.target.value)} /><button className={`${button} shrink-0 whitespace-nowrap`}>搜索</button></form>
        <select aria-label="开放状态" className={`${button} shrink-0 !px-2`} value={availability} onChange={(e) => { setSelection({ key: "", ids: [] }); setAvailability(e.target.value); setPage(1); }}><option value="all">开放状态</option><option value="enabled">已开放</option><option value="disabled">未开放</option></select>
        <select aria-label="打标状态" className={`${button} shrink-0 !px-2`} value={tagStatus} onChange={(e) => { setSelection({ key: "", ids: [] }); setTagStatus(e.target.value); setPage(1); }}><option value="all">打标状态</option><option value="tagged">已打标</option><option value="untagged">未打标</option></select>
        <details className="relative shrink-0">
          <summary className={`${button} cursor-pointer list-none whitespace-nowrap`}>分类标签{tagFilter.length ? `（${tagFilter.length}）` : ""}<span aria-hidden="true" className="ml-1">⌄</span></summary>
          <div className="absolute right-0 top-full z-20 mt-1 w-80 rounded-lg border bg-white px-3 py-2 shadow-lg">
            <TagCascader dimensions={caseDimensions} nodes={taxonomy.tags} value={tagFilter} onChange={(ids) => { setSelection({ key: "", ids: [] }); setTagFilter(ids); setPage(1); }} mode="filter" includeDisabled compact />
          </div>
        </details>
      </section>
      {canEdit && <CaseBatchTagging token={token} selectedIds={listSelectionKey === selectionKey ? selectedIds : []} selectedRecords={list?.items.filter((item) => selectedIds.includes(item.id)) || []} onSubmitted={() => setSelection({ key: selectionKey, ids: [] })} onChanged={() => setRefresh((value) => value + 1)} />}
      <div className="overflow-x-auto rounded-xl border bg-white"><table className="wb-table"><thead className="bg-slate-50"><tr>{canEdit && <th className="px-3 py-2"><input type="checkbox" aria-label="全选本页案例" disabled={!list?.items.length || listSelectionKey !== selectionKey} checked={!!list?.items.length && selectedIds.length === list.items.length} ref={(node) => { if (node) node.indeterminate = selectedIds.length > 0 && selectedIds.length < (list?.items.length || 0); }} onChange={(event) => setSelection({ key: selectionKey, ids: event.target.checked ? list?.items.map((item) => item.id) || [] : [] })} /></th>}{["标题与正文摘要", "分类标签", "解释", "Agent 使用", "最近修改", "操作"].map((label) => <th className="px-3 py-2" key={label}>{label}</th>)}</tr></thead><tbody>{list?.items.map((item) => <tr className="border-t" key={item.id}>{canEdit && <td className="px-3 py-2"><input type="checkbox" aria-label={`选择案例 ${item.title}`} disabled={listSelectionKey !== selectionKey} checked={selectedIds.includes(item.id)} onChange={(event) => setSelection({ key: selectionKey, ids: event.target.checked ? [...selectedIds, item.id] : selectedIds.filter((id) => id !== item.id) })} /></td>}<td className="max-w-lg px-3 py-2"><Link className="font-medium text-emerald-800" href={`${base}/${item.id}`}>{item.title}</Link><p className="mt-1 line-clamp-2 whitespace-pre-wrap text-slate-500">{item.summary}</p></td><td className="min-w-48 px-3 py-2">{tagsView(item.tag_ids)}</td><td className="px-3 py-2 whitespace-nowrap">{item.has_explanation ? "已填写" : "未填写"}</td><td className="px-3 py-2 whitespace-nowrap">{item.enabled ? "已开放" : "未开放"}</td><td className="px-3 py-2 whitespace-nowrap">{item.updated_by}<br /><span className="text-xs text-slate-500">{fmt(item.updated_at)}</span></td><td className="px-3 py-2"><div className="flex gap-3 whitespace-nowrap"><Link href={`${base}/${item.id}`}>查看</Link>{canEdit && <Link href={`${base}/${item.id}?edit=1`}>编辑</Link>}{canEdit && <button disabled={busy} onClick={() => remove(item)}>删除</button>}</div></td></tr>)}</tbody></table>{(!list || !list.items.length) && <p className="p-8 text-center text-sm text-slate-500">{list ? "暂无符合条件的案例" : "正在加载案例…"}</p>}</div>
      {list && <div className="flex items-center justify-end flex-wrap gap-2 text-sm"><span>共 {list.total} 条 · 第 {page} 页</span><button className={button} disabled={page <= 1} onClick={() => { setSelection({ key: "", ids: [] }); setPage(page - 1); }}>上一页</button><button className={button} disabled={page * list.page_size >= list.total} onClick={() => { setSelection({ key: "", ids: [] }); setPage(page + 1); }}>下一页</button></div>}
    </>}
    {!editing && !detail && <div className="space-y-3 wb-panel"><button className={button} onClick={async () => { try { setCoverage(await request("/case-library/coverage")); } catch (e) { setError((e as Error).message); } }}>查看待补充需求与重复检查</button>{coverage && <><h2 className="font-medium">待补充案例需求</h2>{coverage.gaps.length ? coverage.gaps.map((gap) => <div key={gap.fingerprint} className="whitespace-pre-wrap break-words text-sm"><p>{gap.question} · 出现 {gap.occurrences} 次</p>{gap.context && <details className="text-slate-500"><summary>提问背景</summary>{gap.context}</details>}</div>) : <p className="text-sm text-slate-500">暂无记录</p>}<h2 className="font-medium">内容完全相同的案例</h2>{coverage.duplicates.length ? coverage.duplicates.map((group, index) => <div key={index} className="flex gap-3">{group.map((item) => <Link className="text-sm underline" key={item.id} href={`${base}/${item.id}`}>{item.title}</Link>)}</div>) : <p className="text-sm text-slate-500">未发现完全重复的案例。地区、正文或解释有差异的资料需要人工核对。</p>}</>}</div>}
  </section>;
}
