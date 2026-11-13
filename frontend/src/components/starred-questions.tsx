"use client";

import { useEffect, useState, type FormEvent } from "react";
import { evaluationRequest } from "@/lib/evaluation-api";
import { useEvaluationSession } from "./evaluation-shell";

type Reuse = { reuse_status?: string; coverage_scope?: string; excluded_scope?: string; source_refs?: string[]; variants?: string[]; [key: string]: unknown };
type Question = { question_id: string; question: string; answer: string; created_at: string; updated_at: string; revision: number; reuse?: Reuse; source_sq_id?: string };
type Draft = { question: string; answer: string; reuse: Reuse };
const emptyDraft = (): Draft => ({ question: "", answer: "", reuse: {} });
const reuseLabels: Record<string, string> = { unknown: "范围状态未知", reference: "可复用参考答复", partial: "部分答复", pending: "待补充", conflict: "材料有冲突" };
const field = "wb-field";

export function StarredQuestions() {
  const { token, user } = useEvaluationSession();
  const canEdit = user.role === "developer";
  const [items, setItems] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingRevision, setEditingRevision] = useState<number | null>(null);
  const [conflict, setConflict] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [search, setSearch] = useState("");
  const keywords = search.normalize("NFKC").trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const visibleItems = items.map((item, index) => ({ item, number: index + 1 })).filter(({ item }) => {
    const text = [item.question, item.answer, item.source_sq_id, ...(item.reuse?.variants ?? [])]
      .join("\n").normalize("NFKC").toLocaleLowerCase();
    return keywords.every((keyword) => text.includes(keyword));
  });

  useEffect(() => {
    let active = true;
    evaluationRequest<Question[]>(token, "/starred-questions")
      .then((records) => { if (active) setItems(records); })
      .catch((error) => { if (active) setLoadError(error instanceof Error ? error.message : "读取失败，请重试。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);

  async function retryLoad() {
    setLoading(true); setLoadError("");
    try { setItems(await evaluationRequest<Question[]>(token, "/starred-questions")); }
    catch (error) { setLoadError(error instanceof Error ? error.message : "读取失败，请重试。"); }
    finally { setLoading(false); }
  }

  function startNew() { setEditingId("new"); setEditingRevision(null); setConflict(false); setDraft(emptyDraft()); setSaveError(""); }
  function startEdit(item: Question) {
    setEditingId(item.question_id);
    setEditingRevision(item.revision);
    setConflict(false);
    setDraft({ question: item.question, answer: item.answer, reuse: item.reuse ?? {} });
    setSaveError("");
  }

  async function loadLatest() {
    setBusy(true);
    try {
      const records = await evaluationRequest<Question[]>(token, "/starred-questions");
      const latest = records.find((item) => item.question_id === editingId);
      if (!latest) throw new Error("星标问题不存在，你的输入已保留。");
      setItems(records); startEdit(latest);
    } catch (error) { setSaveError(error instanceof Error ? error.message : "读取失败，你的输入已保留。"); }
    finally { setBusy(false); }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!canEdit) return;
    if (!draft.question.trim()) { setSaveError("问题不能为空。"); return; }
    if (!editingId) return;
    setBusy(true); setSaveError("");
    try {
      const path = editingId === "new" ? "/starred-questions" : `/starred-questions/${encodeURIComponent(editingId)}`;
      const result = await evaluationRequest<Question>(token, path, {
        method: editingId === "new" ? "POST" : "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editingId === "new" ? draft : { ...draft, expected_revision: editingRevision }),
      });
      setItems((current) => editingId === "new" ? [...current, result] : current.map((item) => item.question_id === result.question_id ? result : item));
      setEditingId(null); setDraft(emptyDraft());
    } catch (error) {
      if ((error as { code?: string }).code === "starred_question_conflict") {
        setConflict(true);
        setSaveError("内容已被其他人更新，你的输入已保留。请先复制需要保留的修改，再载入最新版本继续编辑。");
      } else setSaveError("保存失败，请重试。您填写的内容已保留。");
    }
    finally { setBusy(false); }
  }

  return <section className="space-y-3" aria-label="星标问题">
    <div className="flex flex-wrap items-center justify-between gap-2 wb-panel">
      <div className="flex min-w-0 flex-1 basis-72 items-center gap-2">
        <input type="search" aria-label="搜索星标问题" placeholder="搜索问题、答案、同义问法或编号" className={`${field} min-w-0 flex-1`} value={search} onChange={(event) => setSearch(event.target.value)} />
        {search && <button type="button" onClick={() => setSearch("")} className="shrink-0 whitespace-nowrap text-sm text-emerald-700 hover:underline">清除搜索</button>}
      </div>
      <p role="status" aria-live="polite" className="text-sm text-slate-600">{keywords.length ? `找到 ${visibleItems.length} 条，共 ${items.length} 条` : `共 ${items.length} 条`}</p>
      {canEdit && <button type="button" onClick={startNew} disabled={busy} className="wb-button wb-button-primary">新增问题</button>}
    </div>
    {canEdit && editingId && <form onSubmit={save} className="space-y-4 rounded-xl border border-emerald-200 bg-white p-5" aria-label={editingId === "new" ? "新增问题" : "编辑问题"}>
      <h2 className="font-semibold">{editingId === "new" ? "新增问题" : "编辑问题及对应答案"}</h2>
      <label className="block space-y-1.5 text-sm font-medium">问题 <span className="text-red-600">*</span>
        <textarea className={field} rows={4} maxLength={20000} required value={draft.question} onChange={(event) => setDraft({ ...draft, question: event.target.value })} />
      </label>
      <label className="block space-y-1.5 text-sm font-medium">对应答案（选填）
        <textarea className={field} rows={7} maxLength={100000} value={draft.answer} onChange={(event) => setDraft({ ...draft, answer: event.target.value })} />
      </label>
      <details className="space-y-3 rounded-lg border p-3" open={!!draft.reuse.reuse_status || undefined}><summary className="cursor-pointer text-sm font-medium">复用范围与来源</summary>
        <label className="mt-3 block space-y-1.5 text-sm">答复状态
          <select className={field} value={draft.reuse.reuse_status ?? "unknown"} onChange={(event) => setDraft({ ...draft, reuse: { ...draft.reuse, reuse_status: event.target.value } })}>{Object.entries(reuseLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </label>
        <label className="block space-y-1.5 text-sm">可覆盖范围<textarea className={field} rows={2} maxLength={10000} value={draft.reuse.coverage_scope ?? ""} onChange={(event) => setDraft({ ...draft, reuse: { ...draft.reuse, coverage_scope: event.target.value } })} /></label>
        <label className="block space-y-1.5 text-sm">未覆盖内容<textarea className={field} rows={2} maxLength={10000} value={draft.reuse.excluded_scope ?? ""} onChange={(event) => setDraft({ ...draft, reuse: { ...draft.reuse, excluded_scope: event.target.value } })} /></label>
        <label className="block space-y-1.5 text-sm">资料来源（每行一项）<textarea className={field} rows={3} value={(draft.reuse.source_refs ?? []).join("\n")} onChange={(event) => setDraft({ ...draft, reuse: { ...draft.reuse, source_refs: event.target.value.split("\n") } })} /></label>
        <label className="block space-y-1.5 text-sm">同义问法（每行一项）<textarea className={field} rows={3} value={(draft.reuse.variants ?? []).join("\n")} onChange={(event) => setDraft({ ...draft, reuse: { ...draft.reuse, variants: event.target.value.split("\n") } })} /></label>
        <p className="text-xs text-slate-500">同义问法应与可覆盖范围一致；较宽的原问题不应当作完整可答的同义问法。修改答案时也请检查范围与状态。</p>
      </details>
      {saveError && <p role="alert" className="text-sm text-red-700">{saveError}</p>}
      {conflict && <button type="button" disabled={busy} onClick={() => void loadLatest()} className="text-sm text-emerald-700 underline disabled:opacity-50">载入最新版本</button>}
      <div className="flex gap-2">
        <button disabled={busy || conflict} className="wb-button wb-button-primary">{busy ? "保存中…" : "保存"}</button>
        <button type="button" disabled={busy} onClick={() => { setEditingId(null); setSaveError(""); }} className="wb-button">取消</button>
      </div>
    </form>}
    {loadError && <div role="alert" className="wb-panel text-sm text-red-700">{loadError} <button type="button" onClick={() => void retryLoad()} className="ml-2 underline">重试</button></div>}
    {loading ? <p role="status" className="wb-panel text-sm text-slate-500">正在读取问题…</p> : !loadError && (visibleItems.length ? <div className="space-y-3">{visibleItems.map(({ item, number }) => <article key={item.question_id} aria-label={`星标问题 ${number}`} className="wb-panel">
      <div className="flex items-start justify-between gap-3"><p className="min-w-0 whitespace-pre-wrap break-words text-sm leading-6 text-slate-900">{item.question}</p>{canEdit && <button type="button" onClick={() => startEdit(item)} disabled={busy} className="shrink-0 text-sm font-medium text-emerald-700 hover:underline disabled:opacity-50">编辑</button>}</div>
      <p className="mt-2 text-xs text-slate-500">{item.source_sq_id ? `来源 ${item.source_sq_id} · ` : ""}{reuseLabels[item.reuse?.reuse_status ?? "unknown"] ?? "范围状态未知"} · 专业审核未知</p>
      <div className="mt-2 border-t pt-2"><p className={`mt-2 whitespace-pre-wrap break-words text-sm leading-6 ${item.answer ? "text-slate-800" : "text-slate-400"}`}>{item.answer || "暂无答案"}</p></div>
      {!!item.reuse && (item.reuse.coverage_scope || item.reuse.excluded_scope || item.reuse.source_refs?.length) && <details className="mt-3 border-t pt-2 text-xs leading-6 text-slate-600"><summary className="cursor-pointer">查看适用范围与资料来源</summary><p>可覆盖：{item.reuse.coverage_scope || "未知"}</p><p>未覆盖：{item.reuse.excluded_scope || "未知"}</p><p className="whitespace-pre-wrap break-words">来源：{item.reuse.source_refs?.filter(Boolean).join("\n") || "未知"}</p></details>}
    </article>)}</div> : <p className="wb-panel text-center text-sm text-slate-500">{items.length ? "未找到匹配的星标问题，请尝试其他关键词或清除搜索。" : "暂无星标问题，点击“新增问题”开始录入。"}</p>)}
  </section>;
}
