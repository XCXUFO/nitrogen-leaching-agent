"use client";

import Link from "next/link";
import { evaluationHref } from "@/lib/evaluation-navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { evaluationJson, evaluationRequest as request } from "@/lib/evaluation-api";
import type { EvaluationCase } from "@/lib/evaluation-api";
import { EvaluationCaseEditor } from "@/components/evaluation-case-editor";

type Draft = { draft_id: string; revision: number; status: "draft" | "published"; case: EvaluationCase["case"]; notes: string };

const field = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
const button = "rounded-md border border-input px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
export function EvaluationCatalog({ token, role, cases, currentCase, onSelectCase, onPublished, showDrafts = false }: {
  token: string; role: "developer" | "reviewer" | "tester"; showDrafts?: boolean; cases: EvaluationCase[]; currentCase?: EvaluationCase;
  onSelectCase: (id: string) => void;
  onPublished: () => Promise<void>;
}) {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [batchJson, setBatchJson] = useState("");
  const [selectedDraft, setSelectedDraft] = useState("");
  const [activeDraft, setActiveDraft] = useState<Draft | null>(null);
  const [draftText, setDraftText] = useState("");
  const [draftNotes, setDraftNotes] = useState("");
  const [caseSearch, setCaseSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [reviewFilter, setReviewFilter] = useState("");
  const [history, setHistory] = useState<Draft[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  let draftDirty = false;
  if (activeDraft) {
    try {
      draftDirty = JSON.stringify(JSON.parse(draftText)) !== JSON.stringify(activeDraft.case)
        || draftNotes !== activeDraft.notes;
    } catch { draftDirty = true; }
  }
  const visibleCases = cases.filter((item) =>
    `${item.case.case_id} ${item.case.version} ${item.case.title}`.toLowerCase().includes(caseSearch.toLowerCase())
    && (!categoryFilter || item.case.category === categoryFilter)
    && (!reviewFilter || item.professional_review === reviewFilter));

  const refresh = useCallback(async () => {
    setDrafts(role === "developer" ? await request<Draft[]>(token, "/case-drafts") : []);
  }, [token, role]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh().catch((err) => setError(err instanceof Error ? err.message : "用例草稿读取失败。"));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); }
    catch (err) { setError(err instanceof Error ? err.message : "操作失败。" ); }
    finally { setBusy(false); }
  }

  function selectDraft(id: string) {
    const draft = drafts.find((item) => item.draft_id === id);
    openDraft(draft ?? null);
  }

  function openDraft(draft: Draft | null) {
    setSelectedDraft(draft?.draft_id ?? ""); setActiveDraft(draft); setHistory([]);
    setDraftText(draft ? JSON.stringify(draft.case, null, 2) : "");
    setDraftNotes(draft?.notes ?? "");
  }

  function copyCurrentCase() {
    if (!currentCase) return;
    setSelectedDraft(""); setActiveDraft(null); setHistory([]);
    setDraftText(JSON.stringify({ ...currentCase.case, version: currentCase.case.version + 1 }, null, 2));
    setDraftNotes("");
    setNotice("已复制用例标准为草稿内容；请核对版本、步骤和附件要求后保存。");
  }

  async function saveDraft(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      let parsed: unknown;
      try { parsed = JSON.parse(draftText); }
      catch { throw new Error("用例 JSON 格式不正确，请检查引号与逗号。"); }
      const body = { case: parsed, notes: draftNotes };
      const record = activeDraft
        ? await request<Draft>(token, `/case-drafts/${activeDraft.draft_id}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, expected_revision: activeDraft.revision }),
        })
        : await request<Draft>(token, "/case-drafts", evaluationJson(body));
      await refresh(); setHistory([]);
      setSelectedDraft(record.draft_id); setActiveDraft(record); setDraftText(JSON.stringify(record.case, null, 2));
      setDraftNotes(record.notes);
      setNotice(`草稿已保存：修订 ${record.revision}；尚未发布，不影响已有评分。`);
    });
  }

  return <fieldset disabled={busy} className={`min-w-0 rounded-lg border ${showDrafts || currentCase ? "space-y-4 p-5" : "space-y-3 p-3"}`}>
    <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-semibold">{showDrafts ? "用例草稿与发布" : "用例版本目录"}</h2></div>
      <div className="flex gap-2">{role === "developer" && !showDrafts && <Link href={evaluationHref("cases", "drafts")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white">管理草稿</Link>}<button className={button} disabled={busy} onClick={() => void run(refresh)}>刷新目录</button></div></div>
    {error && <p role="alert" className="rounded border border-destructive/40 p-2 text-sm">{error}</p>}
    {notice && <p role="status" className="rounded border border-green-600/30 p-2 text-sm">{notice}</p>}
    {!showDrafts && <section className="space-y-3"><h3 className="text-sm font-medium">已发布 Case：检索与筛选（{cases.length} 个版本）</h3>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <input aria-label="检索已发布用例" className={field} value={caseSearch} placeholder="编号、版本或标题" onChange={(e) => setCaseSearch(e.target.value)} />
        <select aria-label="筛选用例类别" className={field} value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}><option value="">全部类别</option>
          {["A", "K", "F", "B", "X", "O", "NEW"].map((item) => <option key={item}>{item}</option>)}</select>
        <select aria-label="筛选专业审核" className={field} value={reviewFilter} onChange={(e) => setReviewFilter(e.target.value)}><option value="">全部审核状态</option>
          <option value="pending">待专业审核</option><option value="domain_expert_reviewed">已有专家审核</option></select>
      </div>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr>{["用例", "版本", "类别", "优先级", "专业审核", "操作"].map((label) => <th key={label} className="whitespace-nowrap px-3 py-2 font-medium">{label}</th>)}</tr></thead><tbody>
        {visibleCases.map((item) => <tr key={`${item.case.case_id}@${item.case.version}`} className="border-t"><td className="px-3 py-2"><span className="font-medium">{item.case.case_id}</span><p className="mt-1 text-xs text-slate-500">{item.case.title}</p></td><td className="px-3 py-2">v{item.case.version}</td><td className="px-3 py-2">{item.case.category}</td><td className="px-3 py-2">{item.case.priority}</td><td className="whitespace-nowrap px-3 py-2 text-xs">{item.professional_review === "domain_expert_reviewed" ? "已有专家审核" : "待专业审核"}</td><td className="px-3 py-2"><button type="button" className="whitespace-nowrap text-emerald-700 underline" onClick={() => onSelectCase(`${item.case.case_id}@${item.case.version}`)}>查看用例</button></td></tr>)}
      </tbody></table>{!visibleCases.length && <p className="py-6 text-center text-sm text-muted-foreground">没有匹配的用例。</p>}</div>
    </section>}
    {role === "developer" && <div className="grid gap-3 xl:grid-cols-2">
      <details className="rounded-lg border p-4"><summary className="cursor-pointer text-sm font-medium">批量导入草稿</summary><form className="space-y-2 rounded border p-3" onSubmit={(event) => { event.preventDefault(); void run(async () => {
        let parsed: unknown;
        try { parsed = JSON.parse(batchJson); } catch { throw new Error("批量导入 JSON 格式不正确。"); }
        const values = Array.isArray(parsed) ? parsed : (parsed as { drafts?: unknown[] })?.drafts;
        if (!Array.isArray(values) || values.length < 1 || values.length > 50) throw new Error("一次导入 1 至 50 个用例草稿。");
        const drafts = values.map((value: unknown) => {
          const item = value as Record<string, unknown>;
          return "case" in item ? item : { case: item };
        });
        const saved = await request<Draft[]>(token, "/case-drafts/import", evaluationJson({ drafts }));
        await refresh(); setBatchJson(""); setNotice(`已导入 ${saved.length} 份草稿，尚未发布；请逐份核对再发布。`);
      }); }}>
        <h3 className="font-medium">批量导入 Case 草稿</h3>
        <p className="text-xs text-muted-foreground">粘贴 1–50 个 EvalCase 对象组成的 JSON 数组，或包含 drafts 数组的对象。整批校验后保存为独立草稿，不发布、不评分。</p>
        <textarea aria-label="批量导入用例 JSON" className={`${field} font-mono text-xs`} rows={4} required value={batchJson} onChange={(e) => setBatchJson(e.target.value)} />
        <button className={button} disabled={busy}>导入草稿</button>
      </form></details>
    </div>}
    {showDrafts && role === "developer" && <div className="space-y-3 border-t pt-4">
      <h3 className="font-medium">用例草稿与发布</h3>
      <p className="text-xs text-muted-foreground">创建空白用例或复制当前版本后填写表单。草稿每次保存保留修订，发布后新增冻结版本。</p>
      <div className="flex flex-wrap gap-2"><button className={button} disabled={!currentCase || busy} onClick={copyCurrentCase}>复制当前用例为新草稿</button>
        <button className={button} disabled={busy} onClick={() => { openDraft(null); setDraftText(JSON.stringify({ case_id: "", version: 1, title: "", category: "NEW", priority: "P1", source: "人工编写", preconditions: "", expected: [], attachment_requirements: [], steps: [{ action: "query", instruction: "", input: "" }] }, null, 2)); }}>新建空白用例</button>
        <button className={button} disabled={busy} onClick={() => selectDraft("")}>清空编辑区</button></div>
      <select aria-label="已有用例草稿" className={field} value={selectedDraft} onChange={(e) => selectDraft(e.target.value)}><option value="">新草稿</option>{drafts.map((item) => <option key={item.draft_id} value={item.draft_id}>{item.case.case_id} v{item.case.version} · 修订 {item.revision} · {item.status}</option>)}</select>
      <form className="space-y-2" onSubmit={(event) => void saveDraft(event)}>
        <EvaluationCaseEditor text={draftText} onChange={setDraftText} />
        <details><summary className="cursor-pointer text-xs text-muted-foreground">高级：用例 JSON</summary><textarea aria-label="用例 JSON" className={`${field} font-mono text-xs`} rows={13} value={draftText} onChange={(e) => setDraftText(e.target.value)} placeholder="复制现有用例，或填写 EvalCase JSON" /></details>
        <p className="text-xs text-muted-foreground">附件要求按文件名使用已有评测样例。</p>
        <input aria-label="草稿备注" className={field} value={draftNotes} onChange={(e) => setDraftNotes(e.target.value)} placeholder="草稿修订说明" />
        <button className={button} disabled={busy || !!activeDraft && activeDraft.status !== "draft"}>{activeDraft ? "保存新修订" : "创建草稿"}</button>
      </form>
      {activeDraft && <div className="flex flex-wrap gap-2"><button className={button} disabled={busy} onClick={() => void run(async () => {
        setHistory(await request<Draft[]>(token, `/case-drafts/${activeDraft.draft_id}/history`));
      })}>查看修订历史</button>
        <button className={button} disabled={busy} onClick={() => void run(async () => {
          openDraft(await request<Draft>(token, `/case-drafts/${activeDraft.draft_id}`));
        })}>重新打开已保存修订（丢弃本地修改）</button>
        <button className={button} disabled={busy || draftDirty || activeDraft.status !== "draft"} onClick={() => void run(async () => {
          if (draftDirty) throw new Error("请先保存当前修改，再发布冻结版本。");
          await request(token, `/case-drafts/${activeDraft.draft_id}/publish`, evaluationJson({ expected_revision: activeDraft.revision }));
          setActiveDraft(await request<Draft>(token, `/case-drafts/${activeDraft.draft_id}`));
          await refresh(); await onPublished(); setNotice(`${activeDraft.case.case_id} v${activeDraft.case.version} 已发布；旧用例和评分保留。`);
        })}>发布冻结版本</button></div>}
      {activeDraft?.status === "draft" && draftDirty && <p role="status" className="text-sm text-amber-800">有未保存的修改，请先保存新修订再发布。</p>}
      {activeDraft && <p className="text-xs text-muted-foreground">当前打开的是修订 {activeDraft.revision}；发布仅冻结此修订。其他人保存新修订后，需重新打开并核对。</p>}
      {history.length > 0 && <ol className="list-decimal space-y-1 pl-5 text-xs">{history.map((item) => <li key={item.revision}>修订 {item.revision} · {item.status} · {item.notes || "无备注"}</li>)}</ol>}
    </div>}
  </fieldset>;
}
