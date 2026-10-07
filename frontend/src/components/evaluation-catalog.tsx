"use client";

import Link from "next/link";
import { evaluationHref } from "@/lib/evaluation-navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { evaluationJson, evaluationRequest as request } from "@/lib/evaluation-api";
import type { EvaluationCase } from "@/lib/evaluation-api";
import { EvaluationCaseEditor } from "@/components/evaluation-case-editor";

type Asset = { asset_id: string; kind: string; path: string; filename: string; sha256: string; source: string; created_at: string };
type Pair = { pair_id: string; status: "candidate" | "verified"; input_asset_id: string; output_asset_id: string; evidence_asset_id?: string | null; notes: string; created_by: string };
type Draft = { draft_id: string; revision: number; status: "draft" | "published"; case: EvaluationCase["case"]; fixture_asset_ids: string[]; notes: string };

const field = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
const button = "rounded-md border border-input px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const assetKinds = [
  ["paper", "论文"], ["model_input", "模型输入"], ["model_output", "模型输出"],
  ["result_fixture", "结果表附件"], ["evidence", "配对证据"],
] as const;

export function EvaluationCatalog({ token, role, cases, currentCase, onSelectCase, onPublished, mode = "cases", showDrafts = false }: {
  token: string; role: "developer" | "reviewer" | "tester"; mode?: "cases" | "assets"; showDrafts?: boolean; cases: EvaluationCase[]; currentCase?: EvaluationCase;
  onSelectCase: (id: string) => void;
  onPublished: () => Promise<void>;
}) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [assetKind, setAssetKind] = useState("result_fixture");
  const [assetPath, setAssetPath] = useState("");
  const [assetSource, setAssetSource] = useState("");
  const [assetNotes, setAssetNotes] = useState("");
  const [assetUpload, setAssetUpload] = useState<File | null>(null);
  const [batchJson, setBatchJson] = useState("");
  const [pairInput, setPairInput] = useState("");
  const [pairOutput, setPairOutput] = useState("");
  const [pairEvidence, setPairEvidence] = useState("");
  const [pairCandidate, setPairCandidate] = useState("");
  const [pairNotes, setPairNotes] = useState("");
  const [selectedDraft, setSelectedDraft] = useState("");
  const [activeDraft, setActiveDraft] = useState<Draft | null>(null);
  const [draftText, setDraftText] = useState("");
  const [draftNotes, setDraftNotes] = useState("");
  const [caseSearch, setCaseSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [reviewFilter, setReviewFilter] = useState("");
  const [fixtureIds, setFixtureIds] = useState<string[]>([]);
  const [history, setHistory] = useState<Draft[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  let draftDirty = false;
  if (activeDraft) {
    try {
      draftDirty = JSON.stringify(JSON.parse(draftText)) !== JSON.stringify(activeDraft.case)
        || draftNotes !== activeDraft.notes
        || JSON.stringify([...fixtureIds].sort()) !== JSON.stringify([...activeDraft.fixture_asset_ids].sort());
    } catch { draftDirty = true; }
  }
  const visibleCases = cases.filter((item) =>
    `${item.case.case_id} ${item.case.version} ${item.case.title}`.toLowerCase().includes(caseSearch.toLowerCase())
    && (!categoryFilter || item.case.category === categoryFilter)
    && (!reviewFilter || item.professional_review === reviewFilter));

  const refresh = useCallback(async () => {
    const [nextAssets, nextPairs, nextDrafts] = await Promise.all([
      role !== "tester" ? request<Asset[]>(token, "/assets") : Promise.resolve([]), mode === "assets" && role !== "tester" ? request<Pair[]>(token, "/asset-pairs") : Promise.resolve([]),
      role === "developer" ? request<Draft[]>(token, "/case-drafts") : Promise.resolve([]),
    ]);
    setAssets(nextAssets); setPairs(nextPairs); setDrafts(nextDrafts);
  }, [token, role, mode]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh().catch((err) => setError(err instanceof Error ? err.message : "资产目录读取失败。"));
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
    setFixtureIds(draft?.fixture_asset_ids ?? []); setDraftNotes(draft?.notes ?? "");
  }

  function copyCurrentCase() {
    if (!currentCase) return;
    setSelectedDraft(""); setActiveDraft(null); setHistory([]);
    setDraftText(JSON.stringify({ ...currentCase.case, version: currentCase.case.version + 1 }, null, 2));
    setFixtureIds([]); setDraftNotes("");
    setNotice("已复制用例标准为草稿内容；请核对版本、步骤和附件资产后保存。");
  }

  async function saveDraft(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      let parsed: unknown;
      try { parsed = JSON.parse(draftText); }
      catch { throw new Error("用例 JSON 格式不正确，请检查引号与逗号。"); }
      const body = { case: parsed, fixture_asset_ids: fixtureIds, notes: draftNotes };
      const record = activeDraft
        ? await request<Draft>(token, `/case-drafts/${activeDraft.draft_id}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, expected_revision: activeDraft.revision }),
        })
        : await request<Draft>(token, "/case-drafts", evaluationJson(body));
      await refresh(); setHistory([]);
      setSelectedDraft(record.draft_id); setActiveDraft(record); setDraftText(JSON.stringify(record.case, null, 2));
      setFixtureIds(record.fixture_asset_ids); setDraftNotes(record.notes);
      setNotice(`草稿已保存：修订 ${record.revision}；尚未发布，不影响已有评分。`);
    });
  }

  return <fieldset disabled={busy} className="min-w-0 space-y-4 rounded-lg border p-5">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-semibold">{mode === "assets" ? "数据资产" : showDrafts ? "用例草稿与发布" : "用例版本目录"}</h2>
      <p className="text-xs text-muted-foreground">{mode === "assets" ? "登记来源和文件指纹，核对模型输入输出的配对依据。" : "按类别与审核状态检索；发布新版本后保留历史标准与评分。"}</p></div>
      <div className="flex gap-2">{mode === "cases" && role === "developer" && !showDrafts && <Link href={evaluationHref("cases", "drafts")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white">管理草稿</Link>}<button className={button} disabled={busy} onClick={() => void run(refresh)}>刷新目录</button></div></div>
    {error && <p role="alert" className="rounded border border-destructive/40 p-2 text-sm">{error}</p>}
    {notice && <p role="status" className="rounded border border-green-600/30 p-2 text-sm">{notice}</p>}
    {mode === "cases" && !showDrafts && <section className="space-y-3"><h3 className="text-sm font-medium">已发布 Case：检索与筛选（{cases.length} 个版本）</h3>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <input aria-label="检索已发布用例" className={field} value={caseSearch} placeholder="编号、版本或标题" onChange={(e) => setCaseSearch(e.target.value)} />
        <select aria-label="筛选用例类别" className={field} value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}><option value="">全部类别</option>
          {["A", "K", "F", "B", "X", "O", "NEW"].map((item) => <option key={item}>{item}</option>)}</select>
        <select aria-label="筛选专业审核" className={field} value={reviewFilter} onChange={(e) => setReviewFilter(e.target.value)}><option value="">全部审核状态</option>
          <option value="pending">待专业审核</option><option value="domain_expert_reviewed">已有专家审核</option></select>
      </div>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs text-slate-500"><tr>{["用例", "版本", "类别", "优先级", "专业审核", "操作"].map((label) => <th key={label} className="whitespace-nowrap p-3 font-medium">{label}</th>)}</tr></thead><tbody>
        {visibleCases.map((item) => <tr key={`${item.case.case_id}@${item.case.version}`} className="border-t"><td className="p-3"><span className="font-medium">{item.case.case_id}</span><p className="mt-1 text-xs text-slate-500">{item.case.title}</p></td><td className="p-3">v{item.case.version}</td><td className="p-3">{item.case.category}</td><td className="p-3">{item.case.priority}</td><td className="whitespace-nowrap p-3 text-xs">{item.professional_review === "domain_expert_reviewed" ? "已有专家审核" : "待专业审核"}</td><td className="p-3"><button type="button" className="whitespace-nowrap text-emerald-700 underline" onClick={() => onSelectCase(`${item.case.case_id}@${item.case.version}`)}>查看用例</button></td></tr>)}
      </tbody></table>{!visibleCases.length && <p className="py-8 text-center text-sm text-muted-foreground">没有匹配的用例。</p>}</div>
    </section>}
    {mode === "assets" && <div className="grid gap-4 xl:grid-cols-2">
      {role === "developer" && <form className="space-y-2 rounded border p-3" onSubmit={(event) => { event.preventDefault(); void run(async () => {
        const added = await request<Asset>(token, "/assets", evaluationJson({ kind: assetKind, path: assetPath.trim(), source: assetSource.trim(), notes: assetNotes }));
        await refresh(); setAssetPath(""); setAssetNotes(""); setNotice(`已登记 ${added.filename} · SHA-256 ${added.sha256}`);
      }); }}>
        <h3 className="font-medium">登记本地资产</h3>
        <select aria-label="资产类型" className={field} value={assetKind} onChange={(e) => setAssetKind(e.target.value)}>{assetKinds.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <input aria-label="资产路径" className={field} required value={assetPath} onChange={(e) => setAssetPath(e.target.value)} placeholder="项目 data/ 或 docs/ 下的相对路径" />
        <input aria-label="资产来源" className={field} required value={assetSource} onChange={(e) => setAssetSource(e.target.value)} placeholder="来源、取得日期或提供者" />
        <input aria-label="资产备注" className={field} value={assetNotes} onChange={(e) => setAssetNotes(e.target.value)} placeholder="可选：作物、场景和资料限制" />
        <button className={button} disabled={busy}>登记资产</button>
      </form>}
      <form className="space-y-2 rounded border p-3" onSubmit={(event) => { event.preventDefault(); void run(async () => {
        const body = { input_asset_id: pairInput, output_asset_id: pairOutput,
          status: role === "reviewer" ? "verified" : "candidate", evidence_asset_id: role === "reviewer" ? pairEvidence : null,
          supersedes_pair_id: role === "reviewer" ? pairCandidate : null, notes: pairNotes };
        const added = await request<Pair>(token, "/asset-pairs", evaluationJson(body));
        await refresh(); setPairNotes(""); setNotice(`${added.status === "verified" ? "专家核实" : "候选"}配对已保存；记录 ID ${added.pair_id}`);
      }); }}>
        <h3 className="font-medium">{role === "reviewer" ? "核实输入输出配对" : "登记候选输入输出配对"}</h3>
        <select aria-label="模型输入资产" className={field} required value={pairInput} onChange={(e) => setPairInput(e.target.value)}><option value="">选择模型输入</option>{assets.filter((item) => item.kind === "model_input").map((item) => <option key={item.asset_id} value={item.asset_id}>{item.filename} · {item.sha256.slice(0, 10)}</option>)}</select>
        <select aria-label="模型输出资产" className={field} required value={pairOutput} onChange={(e) => setPairOutput(e.target.value)}><option value="">选择模型输出</option>{assets.filter((item) => ["model_output", "result_fixture"].includes(item.kind)).map((item) => <option key={item.asset_id} value={item.asset_id}>{item.filename} · {item.sha256.slice(0, 10)}</option>)}</select>
        {role === "reviewer" && <><select aria-label="候选配对" className={field} required value={pairCandidate} onChange={(e) => { const id = e.target.value; const pair = pairs.find((item) => item.pair_id === id); setPairCandidate(id); if (pair) { setPairInput(pair.input_asset_id); setPairOutput(pair.output_asset_id); } }}><option value="">选择待核实的候选配对</option>{pairs.filter((item) => item.status === "candidate").map((item) => <option key={item.pair_id} value={item.pair_id}>{item.pair_id.slice(0, 8)} · {assets.find((a) => a.asset_id === item.input_asset_id)?.filename} → {assets.find((a) => a.asset_id === item.output_asset_id)?.filename}</option>)}</select>
          <select aria-label="配对证据资产" className={field} required value={pairEvidence} onChange={(e) => setPairEvidence(e.target.value)}><option value="">选择可核对的证据资产</option>{assets.filter((item) => item.kind === "evidence").map((item) => <option key={item.asset_id} value={item.asset_id}>{item.filename} · {item.sha256.slice(0, 10)}</option>)}</select></>}
        <textarea aria-label="配对依据" className={field} required={role === "reviewer"} value={pairNotes} onChange={(e) => setPairNotes(e.target.value)} placeholder="记录配对依据和不能证实的范围" />
        <button className={button} disabled={busy}>保存{role === "reviewer" ? "核实" : "候选配对"}</button>
      </form>
    </div>}
    {role === "developer" && <div className="grid gap-4 xl:grid-cols-2">
      {mode === "assets" && <form className="space-y-2 rounded border p-3" onSubmit={(event) => { event.preventDefault(); void run(async () => {
        if (!assetUpload) throw new Error("请先选择资产文件。");
        const query = new URLSearchParams({ filename: assetUpload.name, kind: assetKind,
          source: assetSource.trim(), notes: assetNotes.trim() });
        const saved = await request<Asset>(token, `/assets/upload?${query}`, { method: "POST", body: assetUpload });
        await refresh(); setAssetUpload(null); setNotice(`已上传并登记 ${saved.filename} · SHA-256 ${saved.sha256}`);
      }); }}>
        <h3 className="font-medium">上传并登记资产</h3>
        <p className="text-xs text-muted-foreground">使用上方资产类型、来源和备注；单份上限 40 MiB。结果表仍须小于 10 MiB，原件另存且计算 SHA-256。</p>
        <input aria-label="上传资产文件" type="file" accept=".xls,.xlsx,.csv,.json,.txt,.md,.pdf,.docx,.zip" className="block max-w-full text-sm"
          onChange={(e) => setAssetUpload(e.target.files?.[0] ?? null)} />
        <button className={button} disabled={busy || !assetUpload || !assetSource.trim()}>上传资产</button>
      </form>}
      {mode === "cases" && <details className="rounded-lg border p-4"><summary className="cursor-pointer text-sm font-medium">批量导入草稿</summary><form className="space-y-2 rounded border p-3" onSubmit={(event) => { event.preventDefault(); void run(async () => {
        let parsed: unknown;
        try { parsed = JSON.parse(batchJson); } catch { throw new Error("批量导入 JSON 格式不正确。"); }
        const values = Array.isArray(parsed) ? parsed : (parsed as { drafts?: unknown[] })?.drafts;
        if (!Array.isArray(values) || values.length < 1 || values.length > 50) throw new Error("一次导入 1 至 50 个用例草稿。");
        const drafts = values.map((value: unknown) => {
          const item = value as Record<string, unknown>;
          return "case" in item ? item : { case: item, fixture_asset_ids: [] };
        });
        const saved = await request<Draft[]>(token, "/case-drafts/import", evaluationJson({ drafts }));
        await refresh(); setBatchJson(""); setNotice(`已导入 ${saved.length} 份草稿，尚未发布；请逐份核对再发布。`);
      }); }}>
        <h3 className="font-medium">批量导入 Case 草稿</h3>
        <p className="text-xs text-muted-foreground">粘贴 1–50 个 EvalCase 对象组成的 JSON 数组，或包含 drafts 数组的对象。整批校验后保存为独立草稿，不发布、不评分。</p>
        <textarea aria-label="批量导入用例 JSON" className={`${field} font-mono text-xs`} rows={4} required value={batchJson} onChange={(e) => setBatchJson(e.target.value)} />
        <button className={button} disabled={busy}>导入草稿</button>
      </form></details>}
    </div>}
    {mode === "assets" && <details open className="rounded border p-3"><summary className="cursor-pointer text-sm">已登记资产 {assets.length} 项、配对 {pairs.length} 项</summary>
      <div className="mt-3 max-h-72 space-y-2 overflow-y-auto text-xs">{assets.map((item) => <p key={item.asset_id} className="break-all rounded border p-2">{item.kind} · {item.path} · SHA-256 {item.sha256}<br />来源：{item.source}</p>)}
        {pairs.map((item) => <p key={item.pair_id} className="break-all rounded border p-2">{item.status === "verified" ? "专家核实" : "候选"} · {item.pair_id} · {item.created_by} · {item.notes}</p>)}</div>
    </details>}
    {mode === "cases" && showDrafts && role === "developer" && <div className="space-y-3 border-t pt-4">
      <h3 className="font-medium">用例草稿与发布</h3>
      <p className="text-xs text-muted-foreground">创建空白用例或复制当前版本后填写表单。草稿每次保存保留修订，发布后新增冻结版本。</p>
      <div className="flex flex-wrap gap-2"><button className={button} disabled={!currentCase || busy} onClick={copyCurrentCase}>复制当前用例为新草稿</button>
        <button className={button} disabled={busy} onClick={() => { openDraft(null); setDraftText(JSON.stringify({ case_id: "", version: 1, title: "", category: "NEW", priority: "P1", source: "人工编写", preconditions: "", expected: [], attachment_requirements: [], steps: [{ action: "query", instruction: "", input: "" }] }, null, 2)); }}>新建空白用例</button>
        <button className={button} disabled={busy} onClick={() => selectDraft("")}>清空编辑区</button></div>
      <select aria-label="已有用例草稿" className={field} value={selectedDraft} onChange={(e) => selectDraft(e.target.value)}><option value="">新草稿</option>{drafts.map((item) => <option key={item.draft_id} value={item.draft_id}>{item.case.case_id} v{item.case.version} · 修订 {item.revision} · {item.status}</option>)}</select>
      <form className="space-y-2" onSubmit={(event) => void saveDraft(event)}>
        <EvaluationCaseEditor text={draftText} onChange={setDraftText} />
        <details><summary className="cursor-pointer text-xs text-muted-foreground">高级：用例 JSON</summary><textarea aria-label="用例 JSON" className={`${field} font-mono text-xs`} rows={13} value={draftText} onChange={(e) => setDraftText(e.target.value)} placeholder="复制现有用例，或填写 EvalCase JSON" /></details>
        <fieldset className="space-y-1 rounded border p-3"><legend className="px-1 text-sm">关联结果表资产</legend>
          {assets.filter((item) => item.kind === "result_fixture").map((item) => <label key={item.asset_id} className="flex gap-2 text-xs"><input type="checkbox" checked={fixtureIds.includes(item.asset_id)} onChange={(e) => setFixtureIds(e.target.checked ? [...fixtureIds, item.asset_id] : fixtureIds.filter((id) => id !== item.asset_id))} />{item.filename} · {item.sha256.slice(0, 12)}</label>)}
          {!assets.some((item) => item.kind === "result_fixture") && <p className="text-xs text-muted-foreground">尚无结果表资产；无附件用例可直接保存。</p>}
        </fieldset>
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
