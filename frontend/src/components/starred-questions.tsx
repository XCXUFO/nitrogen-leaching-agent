"use client";

import { useEffect, useState, type FormEvent } from "react";
import { evaluationRequest } from "@/lib/evaluation-api";
import { useEvaluationSession } from "./evaluation-shell";

type Question = { question_id: string; question: string; answer: string; created_at: string; updated_at: string; revision: number };
type Draft = { question: string; answer: string };
const emptyDraft = (): Draft => ({ question: "", answer: "" });
const field = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-6 outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100";

export function StarredQuestions() {
  const { token } = useEvaluationSession();
  const [items, setItems] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingRevision, setEditingRevision] = useState<number | null>(null);
  const [conflict, setConflict] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState("");

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
    setDraft({ question: item.question, answer: item.answer });
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
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-white p-3">
      <p className="text-sm text-slate-600">共 {items.length} 条</p>
      <button type="button" onClick={startNew} disabled={busy} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800 disabled:opacity-50">新增问题</button>
    </div>
    {editingId && <form onSubmit={save} className="space-y-4 rounded-xl border border-emerald-200 bg-white p-5" aria-label={editingId === "new" ? "新增问题" : "编辑问题"}>
      <h2 className="font-semibold">{editingId === "new" ? "新增问题" : "编辑问题及对应答案"}</h2>
      <label className="block space-y-1.5 text-sm font-medium">问题 <span className="text-red-600">*</span>
        <textarea className={field} rows={4} maxLength={20000} required value={draft.question} onChange={(event) => setDraft({ ...draft, question: event.target.value })} />
      </label>
      <label className="block space-y-1.5 text-sm font-medium">对应答案（选填）
        <textarea className={field} rows={7} maxLength={100000} value={draft.answer} onChange={(event) => setDraft({ ...draft, answer: event.target.value })} />
      </label>
      {saveError && <p role="alert" className="text-sm text-red-700">{saveError}</p>}
      {conflict && <button type="button" disabled={busy} onClick={() => void loadLatest()} className="text-sm text-emerald-700 underline disabled:opacity-50">载入最新版本</button>}
      <div className="flex gap-2">
        <button disabled={busy || conflict} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-800 disabled:opacity-50">{busy ? "保存中…" : "保存"}</button>
        <button type="button" disabled={busy} onClick={() => { setEditingId(null); setSaveError(""); }} className="rounded-lg border px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50">取消</button>
      </div>
    </form>}
    {loadError && <div role="alert" className="rounded-xl border bg-white p-3 text-sm text-red-700">{loadError} <button type="button" onClick={() => void retryLoad()} className="ml-2 underline">重试</button></div>}
    {loading ? <p role="status" className="rounded-xl border bg-white p-3 text-sm text-slate-500">正在读取问题…</p> : !loadError && (items.length ? <div className="space-y-3">{items.map((item, index) => <article key={item.question_id} className="rounded-xl border bg-white p-3">
      <div className="flex items-start justify-between gap-2"><h2 className="text-sm font-semibold text-slate-900">问题 {index + 1}</h2><button type="button" onClick={() => startEdit(item)} disabled={busy} className="shrink-0 text-sm font-medium text-emerald-700 hover:underline disabled:opacity-50">编辑</button></div>
      <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-900">{item.question}</p>
      <div className="mt-2 border-t pt-2"><h3 className="text-xs font-medium text-slate-500">对应答案</h3><p className={`mt-2 whitespace-pre-wrap break-words text-sm leading-6 ${item.answer ? "text-slate-800" : "text-slate-400"}`}>{item.answer || "暂无答案"}</p></div>
    </article>)}</div> : <p className="rounded-xl border bg-white p-5 text-center text-sm text-slate-500">暂无星标问题，点击“新增问题”开始录入。</p>)}
  </section>;
}
