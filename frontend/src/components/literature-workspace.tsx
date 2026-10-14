"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Download, FilePlus2, Pencil, Search, Trash2, UploadCloud } from "lucide-react";
import { apiBaseUrl } from "@/lib/api";
import { TagCascader, TaxonomyTree } from "./literature-taxonomy";
import { useEvaluationSession } from "./evaluation-shell";

type Dimension = { id: string; name: string; description: string; selection: "single" | "multiple"; required: number; enabled: number; sort_order: number };
type Tag = { id: string; dimension_id: string; parent_id: string | null; name: string; description: string; enabled: number; sort_order: number; paper_count: number; path: string };
type Event = { id: string; action: string; actor: string; at: string; before: unknown; after: unknown; reason: string; summary: string };
type Author = { name: string; kind: "person" | "institution" };
type Paper = { id: string; revision: number; title: string; authors: Author[]; authors_unknown: boolean; publication_type: string | null; venue: string; venue_unknown: boolean; year: number | null; year_unknown: boolean; language: string | null; language_note: string; doi: string; source_url: string; source_note: string; abstract: string; version_note: string; related_paper_ids: string[]; related_papers?: { id: string; title: string; deleted: boolean }[]; internal_note: string; tag_ids: string[]; registration: "draft" | "registered"; usage: "normal" | "disabled"; filename: string; sha256: string; created_by: string; created_at: string; updated_by: string; updated_at: string; registered_by: string | null; registered_at: string | null; events?: Event[]; warnings?: string[] };
type Form = Omit<Paper, "revision" | "id" | "registration" | "usage" | "filename" | "sha256" | "created_by" | "created_at" | "updated_by" | "updated_at" | "registered_by" | "registered_at" | "events" | "related_papers"> & { revision?: number; upload_id: string | null; action: "draft" | "register"; confirm_same_doi: boolean };
type ExtractedFields = Pick<Form, "title" | "authors" | "publication_type" | "venue" | "year" | "language" | "language_note" | "doi" | "source_url" | "source_note" | "abstract">;
type ListResult = { counts: { total: number; draft: number; registered: number; disabled: number }; total: number; page: number; page_size: number; items: Paper[] };
type Filters = { keyword: string; field: string; publication_type: string; year_from: string; year_to: string; year_unknown: boolean; language: string; registration: string; usage: string; creators: string; editors: string; created_from: string; created_to: string; updated_from: string; updated_to: string; tags: string[]; include_disabled_tags: boolean; sort: string; direction: string; page: number; page_size: number };
const emptyForm = (): Form => ({ upload_id: null, title: "", authors: [], authors_unknown: false, publication_type: null, venue: "", venue_unknown: false, year: null, year_unknown: false, language: null, language_note: "", doi: "", source_url: "", source_note: "", abstract: "", version_note: "", related_paper_ids: [], internal_note: "", tag_ids: [], action: "draft", confirm_same_doi: false });
const emptyFilters = (): Filters => ({ keyword: "", field: "all", publication_type: "", year_from: "", year_to: "", year_unknown: false, language: "", registration: "all", usage: "normal", creators: "", editors: "", created_from: "", created_to: "", updated_from: "", updated_to: "", tags: [], include_disabled_tags: false, sort: "updated", direction: "desc", page: 1, page_size: 20 });
const input = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-emerald-600 focus:outline-none";
const button = "whitespace-nowrap rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50";
const primary = "whitespace-nowrap rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800 disabled:opacity-50";
const fmt = (date: string | null) => date ? new Date(date).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : "—";
const authorNames = (authors: Author[]) => authors.map((a) => a.name).join("、");
const filterLabels: Record<string, string> = { keyword: "关键词", field: "搜索字段", publication_type: "发表形式", year_from: "起始年份", year_to: "结束年份", year_unknown: "年份未知", language: "语言", registration: "登记状态", usage: "使用状态", creators: "创建人", editors: "最近编辑人", created_from: "创建日期起", created_to: "创建日期止", updated_from: "更新日期起", updated_to: "更新日期止" };
const filterValues: Record<string, string> = { all: "全部", normal: "正常", disabled: "已停用", draft: "草稿", registered: "已登记", true: "是", title: "标题", authors: "作者", venue: "发表载体", id: "文献 ID", doi: "DOI" };
const fieldLabels: Record<string, string> = { title: "论文标题", authors: "作者（按论文署名顺序）", publication_type: "发表形式", venue: "发表载体", year: "发表年份", language: "论文语言", language_note: "论文语言", doi: "DOI", source_url: "来源链接", source_note: "出处说明", source: "出处说明", abstract: "摘要", version_note: "版本／差异说明", internal_note: "内部备注", related_paper_ids: "关联文献", tag_ids: "分类标签" };
const extractedKeys: (keyof ExtractedFields)[] = ["title", "authors", "publication_type", "venue", "year", "language", "language_note", "doi", "source_url", "source_note", "abstract"];
const hasSuggestion = (value: unknown) => Array.isArray(value) ? value.length > 0 : value !== null && value !== undefined && value !== "";
const suggestionText = (value: unknown) => Array.isArray(value) ? authorNames(value as Author[]) : String(value ?? "");

function errorMessage(value: unknown): string { return value instanceof Error ? value.message : "操作失败，请重试。"; }
class LiteratureRequestError extends Error {
  constructor(message: string, public field = "", public duplicate?: { id: string; usage?: string }, public code = "") { super(message); }
}

export function LiteratureWorkspace({ section, detail, tagId = "", edit = false }: { section: "literature" | "literature-tags"; detail: string; tagId?: string; edit?: boolean }) {
  const { token } = useEvaluationSession();
  const router = useRouter();
  const [taxonomy, setTaxonomy] = useState<{ dimensions: Dimension[]; tags: Tag[] }>({ dimensions: [], tags: [] });
  const [users, setUsers] = useState<{ id: string; name: string }[]>([]);
  const [maxPdfMb, setMaxPdfMb] = useState(100);
  const [list, setList] = useState<ListResult | null>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [appliedFilters, setAppliedFilters] = useState<Filters>(emptyFilters);
  const [paper, setPaper] = useState<Paper | null>(null);
  const [form, setForm] = useState<Form>(emptyForm);
  const [editing, setEditing] = useState(detail === "new" || edit);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [errorField, setErrorField] = useState("");
  const [notice, setNotice] = useState("");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadName, setUploadName] = useState("");
  const [duplicates, setDuplicates] = useState<{ id: string; title: string; usage: string }[]>([]);
  const [fileDuplicate, setFileDuplicate] = useState<{ id: string; usage?: string } | null>(null);
  const [pdfUrl, setPdfUrl] = useState("");
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfError, setPdfError] = useState("");
  const [localPreview, setLocalPreview] = useState("");
  const [extracting, setExtracting] = useState(false);
  const [suggestions, setSuggestions] = useState<ExtractedFields | null>(null);
  const [selectedSuggestions, setSelectedSuggestions] = useState<string[]>([]);
  const [selectedDimension, setSelectedDimension] = useState("");
  const uploadXhr = useRef<XMLHttpRequest | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const dropZone = useRef<HTMLDivElement | null>(null);
  const listRequest = useRef(0);
  const extractRequest = useRef(0);
  const listTop = useRef<HTMLElement | null>(null);

  const request = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const response = await fetch(`${apiBaseUrl}/api/literature${path}`, { ...init, cache: "no-store", headers: { Authorization: `Bearer ${token}`, ...init.headers } });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new CustomEvent("evaluation-session-expired", { detail: { token } }));
      const validation = Array.isArray(data?.detail) ? data.detail[0] : null;
      const code: string = data?.detail?.code || "";
      const key = validation?.loc?.[1] || (code.includes("tag") || code === "single_dimension" || code === "ancestor_conflict" ? "tag_ids" : code.replace(/^invalid_/, "").replace(/_(required|conflict)$/, ""));
      const label = fieldLabels[key] || (code === "doi_confirmation_required" ? "DOI" : "");
      throw new LiteratureRequestError(data?.detail?.message || (validation ? `${label || "字段"}格式或长度不符合要求，请检查。` : `请求失败（${response.status}）`), label, data?.detail?.paper_id ? { id: data.detail.paper_id, usage: data.detail.usage } : undefined, code);
    }
    return data as T;
  }, [token]);
  const json = (method: string, value: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) });
  const refreshTaxonomy = useCallback(async () => setTaxonomy(await request<{ dimensions: Dimension[]; tags: Tag[] }>("/taxonomy")), [request]);
  const refreshList = useCallback(async (next: Filters, scrollToTop = false) => {
    const version = ++listRequest.current;
    const params = new URLSearchParams();
    Object.entries(next).forEach(([key, value]) => { if (Array.isArray(value)) { if (value.length) params.set(key, value.join(",")); } else if (value !== "" && value !== false) params.set(key, String(value)); });
    const result = await request<ListResult>(`/papers?${params}`);
    if (version === listRequest.current) {
      setList(result);
      if (scrollToTop) requestAnimationFrame(() => listTop.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  }, [request]);
  useEffect(() => { void request<{ dimensions: Dimension[]; tags: Tag[] }>("/taxonomy").then(setTaxonomy).catch((e) => setError(errorMessage(e))); }, [request]);
  useEffect(() => { void request<{ id: string; name: string }[]>("/users").then(setUsers).catch((e) => setError(errorMessage(e))); }, [request]);
  useEffect(() => { void request<{ max_pdf_mb: number }>("/config").then((value) => setMaxPdfMb(value.max_pdf_mb)).catch((e) => setError(errorMessage(e))); }, [request]);
  useEffect(() => {
    if (section !== "literature") return;
    let cancelled = false;
    if (!detail) {
      let next = emptyFilters();
      try { next = { ...next, ...JSON.parse(sessionStorage.getItem("literature-filters") || "{}") }; } catch { /* default */ }
      if (tagId) { next = { ...emptyFilters(), tags: [tagId], usage: "all", include_disabled_tags: true }; sessionStorage.setItem("literature-filters", JSON.stringify(next)); }
      const params = new URLSearchParams();
      Object.entries(next).forEach(([key, value]) => { if (Array.isArray(value)) { if (value.length) params.set(key, value.join(",")); } else if (value !== "" && value !== false) params.set(key, String(value)); });
      void request<ListResult>(`/papers?${params}`).then((result) => { if (cancelled) return; setList(result); setFilters(next); setAppliedFilters(next); }).catch((e) => { if (!cancelled) setError(errorMessage(e)); });
    } else if (detail !== "new") {
      void request<Paper>(`/papers/${encodeURIComponent(detail)}`).then((record) => { if (cancelled) return; setPaper(record); setForm({ ...emptyForm(), ...record, upload_id: null, action: record.registration === "registered" ? "register" : "draft" }); }).catch((e) => { if (!cancelled) setError(errorMessage(e)); });
    }
    return () => { cancelled = true; };
  }, [section, detail, refreshList, request, tagId]);
  useEffect(() => { const leave = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); }; window.addEventListener("beforeunload", leave); return () => window.removeEventListener("beforeunload", leave); }, [dirty]);
  useEffect(() => {
    if (!dirty) return;
    const navigation = (window as Window & { navigation?: EventTarget }).navigation;
    if (navigation) {
      const guardNavigation = (raw: globalThis.Event) => {
        const event = raw as globalThis.Event & { navigationType: string; destination: { sameDocument: boolean }; hashChange: boolean };
        if (event.navigationType === "traverse" && event.destination.sameDocument && !event.hashChange && event.cancelable && !window.confirm("存在未保存内容，确认离开？")) event.preventDefault();
      };
      navigation.addEventListener("navigate", guardNavigation);
      return () => navigation.removeEventListener("navigate", guardNavigation);
    }
    const href = window.location.href;
    const state = window.history.state;
    const guardHistory = (event: PopStateEvent) => {
      if (window.location.href === href || window.confirm("存在未保存内容，确认离开？")) return;
      // popstate fires after the URL changes. Restore the current entry before
      // Next's router handles it, so declining navigation retains the form.
      event.stopImmediatePropagation();
      window.history.pushState(state, "", href);
    };
    window.addEventListener("popstate", guardHistory, true);
    return () => window.removeEventListener("popstate", guardHistory, true);
  }, [dirty]);
  useEffect(() => () => { uploadXhr.current?.abort(); }, []);
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);
  useEffect(() => () => { if (localPreview) URL.revokeObjectURL(localPreview); }, [localPreview]);
  useEffect(() => {
    if (!paper?.id) return;
    let cancelled = false;
    void (async () => {
      setPdfUrl(""); setPdfLoading(true); setPdfError("");
      try {
        const response = await fetch(`${apiBaseUrl}/api/literature/papers/${encodeURIComponent(paper.id)}/file`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
        if (response.status === 401) window.dispatchEvent(new CustomEvent("evaluation-session-expired", { detail: { token } }));
        if (!response.ok) throw new Error("PDF 无法打开。");
        const url = URL.createObjectURL(await response.blob());
        if (cancelled) URL.revokeObjectURL(url);
        else setPdfUrl(url);
      } catch (e) { if (!cancelled) setPdfError(errorMessage(e)); }
      finally { if (!cancelled) setPdfLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [paper?.id, paper?.sha256, token]);
  useEffect(() => {
    const intercept = (event: MouseEvent) => {
      if (!dirty) return;
      const anchor = (event.target as HTMLElement).closest<HTMLAnchorElement>("a[href]");
      if (!anchor || anchor.getAttribute("href")?.startsWith("#")) return;
      const target = new URL(anchor.href);
      if (target.origin === window.location.origin && target.href !== window.location.href && !window.confirm("存在未保存内容，确认离开？")) {
        event.preventDefault(); event.stopPropagation();
      }
    };
    document.addEventListener("click", intercept, true);
    return () => document.removeEventListener("click", intercept, true);
  }, [dirty]);
  function patch<K extends keyof Form>(key: K, value: Form[K]) { setForm((old) => ({ ...old, [key]: value })); setDirty(true); }
  function applyFilters(next: Filters) { const changedPage = next.page !== appliedFilters.page; setFilters(next); setAppliedFilters(next); sessionStorage.setItem("literature-filters", JSON.stringify(next)); void refreshList(next, changedPage).catch((e) => setError(errorMessage(e))); }
  function go(href: string) { if (dirty && !window.confirm("存在未保存内容，确认离开？")) return; setDirty(false); router.push(href); }
  function cancelEdit() {
    if (dirty && !window.confirm("放弃未保存的修改？")) return;
    uploadXhr.current?.abort(); uploadXhr.current = null;
    extractRequest.current++; setExtracting(false); setSuggestions(null);
    setDirty(false); setConflict(false);
    if (detail === "new") { router.push("/evaluation/literature"); return; }
    if (paper) setForm({ ...emptyForm(), ...paper, upload_id: null, action: paper.registration === "registered" ? "register" : "draft" });
    setEditing(false); setUploadName(""); setLocalPreview(""); setDuplicates([]); setError(""); setNotice("");
  }
  async function run(task: () => Promise<void>) {
    setBusy(true); setError(""); setErrorField(""); setNotice("");
    try { await task(); }
    catch (e) {
      setError(errorMessage(e));
      if (e instanceof LiteratureRequestError) {
        if (e.code === "paper_revision_conflict") setConflict(true);
        if (e.duplicate) setFileDuplicate(e.duplicate);
        setErrorField(e.field);
        if (e.field) {
          const target = document.querySelector<HTMLElement>(`[data-field="${e.field}"]`);
          const collapsed = target?.closest("details");
          if (collapsed) collapsed.open = true;
          target?.scrollIntoView({ block: "center" });
          (target?.querySelector<HTMLElement>("input:not(:disabled),select,textarea") || target)?.focus({ preventScroll: true });
        }
      }
    } finally { setBusy(false); }
  }
  async function uploadFile(file?: File) {
    if (!file) return;
    if (paper?.registration === "registered") { setError("已登记文献不能替换 PDF，请新增关联文献。"); return; }
    if (!file.name.toLowerCase().endsWith(".pdf")) { setError("仅支持 PDF 文件。"); return; }
    if (file.size > maxPdfMb * 1024 * 1024) { setError(`PDF 不能超过 ${maxPdfMb} MB。`); return; }
    if (uploadXhr.current && uploadProgress !== null) return;
    extractRequest.current++; setExtracting(false); setSuggestions(null);
    setError(""); setFileDuplicate(null); setUploadProgress(0); setDirty(true);
    const xhr = new XMLHttpRequest(); uploadXhr.current = xhr;
    xhr.open("POST", `${apiBaseUrl}/api/literature/uploads?filename=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) setUploadProgress(Math.round(event.loaded / event.total * 100)); };
    xhr.onload = () => {
      if (uploadXhr.current !== xhr) return;
      setUploadProgress(null);
      let data;
      try { data = JSON.parse(xhr.responseText || "{}"); }
      catch { setError("上传服务暂时不可用，请重试。"); return; }
      if (xhr.status >= 200 && xhr.status < 300) {
        setUploadName(file.name);
        setForm((latest) => ({ ...latest, upload_id: data.upload_id, title: !latest.title && detail === "new" ? file.name.replace(/\.pdf$/i, "") : latest.title }));
        setDirty(true);
        setLocalPreview(URL.createObjectURL(file));
        setNotice("文件已上传。保存草稿或完成登记后才会出现在文献列表中。");
        void extractPdf({ upload_id: data.upload_id }, true, file.name);
      } else { setError(data?.detail?.message || "上传失败，请重试。"); if (data?.detail?.paper_id) setFileDuplicate({ id: data.detail.paper_id, usage: data.detail.usage }); }
    };
    xhr.onerror = () => { setUploadProgress(null); setError("上传失败，请重试。"); };
    xhr.onabort = () => { setUploadProgress(null); setNotice("上传已取消。"); };
    xhr.send(file);
  }
  async function save(action: "draft" | "register") {
    await run(async () => {
      const payload = { ...form, action, expected_revision: form.revision };
      const saved = await request<Paper>(detail === "new" ? "/papers" : `/papers/${encodeURIComponent(detail)}`, json(detail === "new" ? "POST" : "PUT", payload));
      setConflict(false); setDirty(false); setPaper(saved); setForm({ ...emptyForm(), ...saved, upload_id: null, action: saved.registration === "registered" ? "register" : "draft" }); setEditing(false);
      router.replace(`/evaluation/literature/${encodeURIComponent(saved.id)}`);
      setNotice(action === "register" ? "已完成登记。" : "草稿已保存。");
    });
  }
  async function openFile(download = false, target?: Paper) {
    await run(async () => {
      const selected = target || paper;
      if (!selected) return;
      const response = await fetch(`${apiBaseUrl}/api/literature/papers/${encodeURIComponent(selected.id)}/file?download=${download}`, { headers: { Authorization: `Bearer ${token}` } });
      if (response.status === 401) window.dispatchEvent(new CustomEvent("evaluation-session-expired", { detail: { token } }));
      if (!response.ok) { const data = await response.json().catch(() => null); throw new Error(data?.detail?.message || "PDF 无法打开。"); }
      const url = URL.createObjectURL(await response.blob());
      if (download) { const a = document.createElement("a"); a.href = url; a.download = selected.filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 60000); }
      else { setPdfUrl(url); setPdfError(""); }
    });
  }
  async function extractPdf(override?: { upload_id: string } | { paper_id: string }, autoFill = false, filenameHint = "") {
    const target = override || (form.upload_id ? { upload_id: form.upload_id } : paper ? { paper_id: paper.id } : null);
    if (!target) { setError("请先上传 PDF，再使用 AI 解析。"); return; }
    const version = ++extractRequest.current;
    setExtracting(true); setError(""); setNotice(""); setSuggestions(null);
    try {
      const result = await request<{ fields: ExtractedFields; pages_read: number; method: "ai" | "local"; warning: string }>("/extract", json("POST", target));
      if (version !== extractRequest.current) return;
      setSuggestions(result.fields);
      if (autoFill) {
        const filenameTitle = filenameHint.replace(/\.pdf$/i, "");
        setForm((old) => {
          const changes = Object.fromEntries(extractedKeys.filter((key) => hasSuggestion(result.fields[key]) && (!hasSuggestion(old[key]) || key === "title" && old.title === filenameTitle) && !(key === "authors" && old.authors_unknown) && !(key === "venue" && old.venue_unknown) && !(key === "year" && old.year_unknown)).map((key) => [key, result.fields[key]])) as Partial<ExtractedFields>;
          return { ...old, ...changes };
        });
        setSelectedSuggestions([]);
        setDirty(true);
        setNotice(`${result.warning ? `${result.warning} ` : ""}已读取 PDF 前 ${result.pages_read} 页并填入空白字段。请对照右侧原文核对；已有内容可在解析建议中选择覆盖。`);
      } else {
        setSelectedSuggestions(extractedKeys.filter((key) => hasSuggestion(result.fields[key]) && !hasSuggestion(form[key])));
        setNotice(`${result.warning ? `${result.warning} ` : ""}已读取 PDF 前 ${result.pages_read} 页。请核对解析建议，选择要填入的字段。`);
      }
    } catch (e) { if (version === extractRequest.current) setError(errorMessage(e)); }
    finally { if (version === extractRequest.current) setExtracting(false); }
  }
  function applySuggestions() {
    if (!suggestions || !selectedSuggestions.length) return;
    const changes = Object.fromEntries(selectedSuggestions.map((key) => [key, suggestions[key as keyof ExtractedFields]])) as Partial<ExtractedFields>;
    setForm((old) => ({ ...old, ...changes,
      authors_unknown: selectedSuggestions.includes("authors") ? false : old.authors_unknown,
      venue_unknown: selectedSuggestions.includes("venue") ? false : old.venue_unknown,
      year_unknown: selectedSuggestions.includes("year") ? false : old.year_unknown }));
    setDirty(true); setSuggestions(null); setNotice("已填入所选字段。请核对 PDF 原文，再保存文献。");
  }
  async function paperAction(action: "disable" | "restore" | "delete") {
    if (!paper) return;
    let reason = "";
    if (action !== "restore") {
      reason = window.prompt(`${action === "delete" ? `确认删除《${paper.title}》？删除后不再出现在常规查询中。` : `停用《${paper.title}》` }\n请填写原因：`)?.trim() || "";
      if (!reason) return;
      if (action === "delete" && !window.confirm(`再次确认删除《${paper.title}》？`)) return;
    } else if (!window.confirm(`恢复《${paper.title}》为正常使用？`)) return;
    await run(async () => {
      await request(`/papers/${encodeURIComponent(paper.id)}/${action}`, json("POST", { reason }));
      if (action === "delete") { go("/evaluation/literature"); return; }
      setPaper(await request<Paper>(`/papers/${encodeURIComponent(paper.id)}`));
      setNotice(action === "restore" ? "已恢复。请检查已停用标签和登记要求。" : "已停用。");
    });
  }
  async function quickAction(target: Paper, action: "disable" | "restore" | "delete") {
    let reason = "";
    if (action !== "restore") {
      reason = window.prompt(`${action === "delete" ? "确认删除" : "停用"}《${target.title}》，请填写原因：`)?.trim() || "";
      if (!reason || action === "delete" && !window.confirm(`再次确认删除《${target.title}》？`)) return;
    } else if (!window.confirm(`恢复《${target.title}》？`)) return;
    await run(async () => {
      await request(`/papers/${encodeURIComponent(target.id)}/${action}`, json("POST", { reason }));
      await refreshList(appliedFilters);
      setNotice(action === "delete" ? "已删除。" : action === "restore" ? "已恢复。" : "已停用。");
    });
  }
  async function checkDoi() {
    if (!form.doi.trim()) { setDuplicates([]); return; }
    try { const result = await request<{ papers: { id: string; title: string; usage: string }[] }>(`/duplicates?doi=${encodeURIComponent(form.doi)}`); setDuplicates(result.papers.filter((p) => p.id !== paper?.id)); } catch (e) { setError(errorMessage(e)); }
  }
  const field = (label: string, control: React.ReactNode, hint?: string) => <fieldset data-field={label} tabIndex={-1} className="min-w-0 space-y-1.5 text-sm"><legend className="mb-1.5 font-medium text-slate-700">{label}</legend>{control}{hint && <span className="block text-xs text-slate-500">{hint}</span>}{errorField === label && error && <p className="text-sm text-red-700">{error}</p>}</fieldset>;
  const pdfPane = <section className="overflow-hidden rounded-xl border bg-white shadow-sm" aria-label="PDF 原文预览"><div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3"><div className="min-w-0"><h2 className="font-semibold">PDF 原文预览</h2><p className="truncate text-xs text-slate-500" title={uploadName || paper?.filename || ""}>{uploadName || paper?.filename || "上传 PDF 后显示原文"}</p></div><div className="flex flex-wrap gap-2"><button className={primary} disabled={extracting || !form.upload_id && !paper} onClick={() => { if (!editing) setEditing(true); void extractPdf(); }}>{extracting ? "解析中…" : "AI 解析字段"}</button>{paper && <button className={button} disabled={busy} onClick={() => void openFile(true)}><Download size={14} className="mr-1 inline" />下载</button>}</div></div>{localPreview || pdfUrl ? <iframe title="PDF 原文预览" src={localPreview || pdfUrl} className="h-[min(72vh,900px)] min-h-96 w-full bg-slate-50" /> : <div className="flex min-h-96 items-center justify-center p-6 text-center text-sm text-slate-500">{pdfLoading ? "正在加载 PDF…" : pdfError || "上传 PDF 后可在此直接预览"}</div>}{pdfError && <button className="m-3 text-sm text-emerald-700 underline" onClick={() => void openFile()}>重新加载 PDF</button>}</section>;
  const suggestionPanel = suggestions && <section className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="font-semibold text-emerald-950">PDF 字段解析建议</h2><p className="mt-1 text-xs text-slate-600">默认勾选空白字段；已有内容由你决定是否覆盖。解析结果仅填入表单，保存前请对照右侧原文。</p></div><button className={button} onClick={() => setSuggestions(null)}>关闭建议</button></div><div className="mt-3 max-h-80 space-y-2 overflow-y-auto">{extractedKeys.filter((key) => hasSuggestion(suggestions[key])).map((key) => <label key={key} className="flex cursor-pointer items-start gap-3 rounded-lg border bg-white p-3 text-sm"><input type="checkbox" className="mt-1 accent-emerald-700" checked={selectedSuggestions.includes(key)} onChange={(e) => setSelectedSuggestions((old) => e.target.checked ? [...old, key] : old.filter((item) => item !== key))} /><span className="min-w-0"><strong className="block">{fieldLabels[key]}</strong><span className="block max-h-24 overflow-auto whitespace-pre-wrap break-words text-slate-700">{suggestionText(suggestions[key])}</span>{hasSuggestion(form[key]) && <small className="mt-1 block text-slate-500">当前：{suggestionText(form[key]).slice(0, 180)}</small>}</span></label>)}{!extractedKeys.some((key) => hasSuggestion(suggestions[key])) && <p className="text-sm text-slate-600">没有提取到可靠字段，请手动填写。</p>}</div><div className="mt-3 flex justify-end"><button className={primary} disabled={!selectedSuggestions.length} onClick={applySuggestions}>填入所选字段</button></div></section>;
  const tagLabel = (id: string) => { const tag = taxonomy.tags.find((t) => t.id === id); return tag ? `${taxonomy.dimensions.find((d) => d.id === tag.dimension_id)?.name || "分类"}：${tag.name}` : ""; };
  const activeFilters = Object.entries(appliedFilters).filter(([key, value]) => !["page", "page_size", "sort", "direction", "include_disabled_tags"].includes(key) && (Array.isArray(value) ? value.length > 0 : value !== (emptyFilters() as Record<string, unknown>)[key]));

  if (section === "literature-tags") return <TagManager taxonomy={taxonomy} selectedDimension={selectedDimension} setSelectedDimension={setSelectedDimension} refresh={refreshTaxonomy} request={request} run={run} busy={busy} error={error} notice={notice} setNotice={setNotice} />;

  return <div className="space-y-5">
    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
    {conflict && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">当前输入仍保留，可先复制需要保留的内容。<button className={button} disabled={busy} onClick={() => { if (window.confirm("加载最新版本会放弃当前未保存输入，确认继续？")) void run(async () => { const latest = await request<Paper>(`/papers/${encodeURIComponent(detail)}`); uploadXhr.current?.abort(); uploadXhr.current = null; setPaper(latest); setForm({ ...emptyForm(), ...latest, upload_id: null, action: latest.registration === "registered" ? "register" : "draft" }); setDirty(false); setConflict(false); setUploadName(""); setLocalPreview(""); setDuplicates([]); }); }}>加载最新版本重新编辑</button></div>}
    {fileDuplicate && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">相同文件已登记{fileDuplicate.usage === "disabled" ? "，该记录已停用，可在详情中恢复" : ""}。<button className="ml-2 text-emerald-700 underline" onClick={() => go(`/evaluation/literature/${fileDuplicate.id}`)}>查看现有文献 {fileDuplicate.id}</button></div>}
    {notice && <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</div>}
    {!detail && !list && !error && <p className="text-sm text-slate-500">正在加载文献列表…</p>}
    {!detail && list && <>
      <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-slate-500">全局文献库 · 未打标文献也会显示，可逐篇补充信息和分类。时间显示与日期筛选均按北京时间。</p><button className={primary} onClick={() => go("/evaluation/literature/new")}><span className="inline-flex items-center gap-2"><FilePlus2 size={16} />新增文献</span></button></div>
      {list && <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{([ ["文献总数", list.counts.total, { usage: "all", registration: "all" }], ["草稿", list.counts.draft, { usage: "all", registration: "draft" }], ["已登记", list.counts.registered, { usage: "all", registration: "registered" }], ["已停用", list.counts.disabled, { usage: "disabled", registration: "all" }] ] as const).map(([name, count, changes]) => <button key={name} className="rounded-xl border bg-white p-4 text-left hover:border-emerald-500" onClick={() => applyFilters({ ...emptyFilters(), ...changes })}><span className="block text-sm text-slate-500">{name}</span><strong className="mt-2 block text-2xl">{count}</strong></button>)}</div>}
      <section className="space-y-4 rounded-xl border bg-white p-5">
        <div className="grid gap-3 md:grid-cols-[1fr_12rem_auto_auto]">
          <input className={input} placeholder="搜索标题、作者、载体、DOI 或文献 ID" value={filters.keyword} onChange={(e) => setFilters({ ...filters, keyword: e.target.value })} onKeyDown={(e) => { if (e.key === "Enter") applyFilters({ ...filters, page: 1 }); }} />
          <select className={input} value={filters.field} onChange={(e) => setFilters({ ...filters, field: e.target.value })}>{[["all", "全部字段"], ["title", "标题"], ["authors", "作者"], ["venue", "发表载体"], ["doi", "DOI"], ["id", "文献 ID"]].map(([v, text]) => <option key={v} value={v}>{text}</option>)}</select>
          <button className={primary} onClick={() => applyFilters({ ...filters, page: 1 })}><Search size={16} className="mr-1 inline" />查询</button>
          <button className={button} onClick={() => applyFilters(emptyFilters())}>重置</button>
        </div>
        <div className="flex flex-wrap items-start gap-3">
          <div className="w-full min-w-36 sm:w-40">{field("登记状态", <select className={input} value={filters.registration} onChange={(e) => setFilters({ ...filters, registration: e.target.value })}><option value="all">全部</option><option value="draft">草稿</option><option value="registered">已登记</option></select>)}</div>
          <div className="w-full min-w-36 sm:w-40">{field("使用状态", <select className={input} value={filters.usage} onChange={(e) => setFilters({ ...filters, usage: e.target.value })}><option value="normal">正常</option><option value="disabled">已停用</option><option value="all">全部</option></select>)}</div>
          <div className="min-w-0 flex-1 basis-[20rem]"><p className="mb-2 text-sm font-medium text-slate-700">分类标签</p><TagCascader dimensions={taxonomy.dimensions} nodes={taxonomy.tags} value={filters.tags} onChange={(tags) => setFilters({ ...filters, tags })} includeDisabled={filters.include_disabled_tags} /></div>
        </div>
        <details className="rounded-lg border border-slate-200 px-3 py-2"><summary className="cursor-pointer text-sm text-slate-600">更多筛选（发表信息、人员、时间）</summary><div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {field("发表形式（多选）", <div className="flex min-h-10 flex-wrap gap-2 rounded-lg border p-2">{["期刊论文", "会议论文", "预印本", "其他学术论文"].map((v) => <label key={v} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={filters.publication_type.split(",").includes(v)} onChange={(e) => { const values = filters.publication_type.split(",").filter(Boolean).filter((x) => x !== v); if (e.target.checked) values.push(v); setFilters({ ...filters, publication_type: values.join(",") }); }} />{v}</label>)}</div>)}
          {field("语言（多选）", <div className="flex min-h-10 flex-wrap gap-2 rounded-lg border p-2">{["中文", "英文", "其他"].map((v) => <label key={v} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={filters.language.split(",").includes(v)} onChange={(e) => { const values = filters.language.split(",").filter(Boolean).filter((x) => x !== v); if (e.target.checked) values.push(v); setFilters({ ...filters, language: values.join(",") }); }} />{v}</label>)}</div>)}
          {field("年份起", <input type="number" className={input} value={filters.year_from} disabled={filters.year_unknown} onChange={(e) => setFilters({ ...filters, year_from: e.target.value })} />)}
          {field("年份止", <input type="number" className={input} value={filters.year_to} disabled={filters.year_unknown} onChange={(e) => setFilters({ ...filters, year_to: e.target.value })} />)}
          {field("创建人（多选）", <div className="max-h-28 min-h-10 overflow-auto rounded-lg border p-2">{users.map((person) => <label key={person.id} className="mr-3 inline-flex items-center gap-1 text-xs"><input type="checkbox" checked={filters.creators.split(",").includes(person.id)} onChange={(e) => { const values = filters.creators.split(",").filter(Boolean).filter((x) => x !== person.id); if (e.target.checked) values.push(person.id); setFilters({ ...filters, creators: values.join(",") }); }} />{person.name}</label>)}</div>)}
          {field("最近编辑人（多选）", <div className="max-h-28 min-h-10 overflow-auto rounded-lg border p-2">{users.map((person) => <label key={person.id} className="mr-3 inline-flex items-center gap-1 text-xs"><input type="checkbox" checked={filters.editors.split(",").includes(person.id)} onChange={(e) => { const values = filters.editors.split(",").filter(Boolean).filter((x) => x !== person.id); if (e.target.checked) values.push(person.id); setFilters({ ...filters, editors: values.join(",") }); }} />{person.name}</label>)}</div>)}
          {field("创建时间起", <input type="date" className={input} value={filters.created_from} onChange={(e) => setFilters({ ...filters, created_from: e.target.value })} />)}
          {field("创建时间止", <input type="date" className={input} value={filters.created_to} onChange={(e) => setFilters({ ...filters, created_to: e.target.value })} />)}
          {field("更新时间起", <input type="date" className={input} value={filters.updated_from} onChange={(e) => setFilters({ ...filters, updated_from: e.target.value })} />)}
          {field("更新时间止", <input type="date" className={input} value={filters.updated_to} onChange={(e) => setFilters({ ...filters, updated_to: e.target.value })} />)}
        </div>
        <label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={filters.year_unknown} onChange={(e) => setFilters({ ...filters, year_unknown: e.target.checked, year_from: "", year_to: "" })} />发表年份未知</label>
        <label className="ml-4 inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={filters.include_disabled_tags} onChange={(e) => setFilters({ ...filters, include_disabled_tags: e.target.checked, tags: e.target.checked ? filters.tags : filters.tags.filter((id) => taxonomy.tags.some((tag) => tag.id === id && tag.enabled && taxonomy.dimensions.some((dim) => dim.id === tag.dimension_id && dim.enabled))) })} />包含已停用标签</label>
        </details>
      </section>
      <section ref={listTop} className="scroll-mt-4 space-y-3 rounded-xl border bg-white p-5"><div className="flex flex-wrap items-center justify-between gap-3"><span className="text-sm text-slate-600">共 {list?.total ?? 0} 条结果</span><div className="flex gap-2"><select className={input} value={filters.sort} onChange={(e) => applyFilters({ ...filters, sort: e.target.value, page: 1 })}><option value="updated">最近更新</option><option value="created">创建时间</option><option value="year">发表年份</option></select><select className={input} value={filters.direction} onChange={(e) => applyFilters({ ...filters, direction: e.target.value, page: 1 })}><option value="desc">倒序</option><option value="asc">正序</option></select></div></div>
        {activeFilters.length > 0 && <div className="flex flex-wrap gap-2">{activeFilters.map(([key, value]) => <button key={key} className="rounded-full bg-slate-100 px-3 py-1 text-xs hover:bg-slate-200" onClick={() => applyFilters({ ...appliedFilters, [key]: (emptyFilters() as Record<string, unknown>)[key], page: 1 })}>{key === "tags" ? (value as string[]).map((id) => taxonomy.tags.find((t) => t.id === id)?.path || id).join("、") : `${filterLabels[key] || key}：${filterValues[String(value)] || String(value)}`} ×</button>)}</div>}
        {!list?.items.length ? <div className="py-12 text-center text-sm text-slate-500">没有符合条件的文献。<button className="ml-2 text-emerald-700 underline" onClick={() => applyFilters(emptyFilters())}>清空筛选</button></div> : <div className="overflow-x-auto"><table className="w-full min-w-[1050px] text-left text-sm"><thead className="border-b bg-slate-50 text-slate-500"><tr>{["标题", "作者", "发表载体", "年份", "形式", "标签", "登记", "使用", "创建人", "更新时间", "操作"].map((h) => <th key={h} className="p-2 font-medium">{h}</th>)}</tr></thead><tbody>{list.items.map((item) => <tr key={item.id} className="border-b align-top"><td className="max-w-52 p-2"><button title={item.title} className="max-w-52 truncate text-left font-medium text-emerald-800 hover:underline" onClick={() => go(`/evaluation/literature/${item.id}`)}>{item.title || "未填写"}</button><div className="text-xs text-slate-400">{item.id}</div></td><td className="max-w-32 truncate p-2" title={authorNames(item.authors)}>{item.authors.length ? authorNames(item.authors.slice(0, 2)) + (item.authors.length > 2 ? ` 等${item.authors.length}位` : "") : item.authors_unknown ? "未知" : "未填写"}</td><td className="p-2">{item.venue || (item.venue_unknown ? "未知" : "未填写")}</td><td className="p-2">{item.year ?? (item.year_unknown ? "未知" : "未填写")}</td><td className="p-2">{item.publication_type || "未填写"}</td><td className="max-w-40 p-2">{item.tag_ids.slice(0, 2).map(tagLabel).filter(Boolean).join("、") || "未打标（全局）"}{item.tag_ids.length > 2 && ` 等${item.tag_ids.length}个`}</td><td className="p-2">{item.registration === "draft" ? "草稿" : "已登记"}</td><td className="p-2">{item.usage === "normal" ? "正常" : "已停用"}</td><td className="p-2">{item.created_by}</td><td className="p-2">{fmt(item.updated_at)}</td><td className="p-2"><div className="flex flex-wrap gap-x-2"><button className="text-emerald-700 underline" onClick={() => go(`/evaluation/literature/${item.id}`)}>查看</button><button className="text-emerald-700 underline" onClick={() => go(`/evaluation/literature/${item.id}?edit=1`)}>编辑</button><button className="text-emerald-700 underline" onClick={() => void openFile(true, item)}>下载</button><button className="text-emerald-700 underline" onClick={() => void quickAction(item, item.usage === "normal" ? "disable" : "restore")}>{item.usage === "normal" ? "停用" : "恢复"}</button><button className="text-red-700 underline" onClick={() => void quickAction(item, "delete")}>删除</button></div></td></tr>)}</tbody></table></div>}
        <div className="flex flex-wrap items-center justify-end gap-2 text-sm"><select aria-label="每页条数" title="每页条数" className="w-20 rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm" value={filters.page_size} onChange={(e) => applyFilters({ ...filters, page_size: Number(e.target.value), page: 1 })}>{[20, 50, 100].map((n) => <option key={n}>{n}</option>)}</select><button className={button} disabled={filters.page <= 1} onClick={() => applyFilters({ ...filters, page: filters.page - 1 })}>上一页</button><span>{filters.page}</span><button className={button} disabled={!list || filters.page * filters.page_size >= list.total} onClick={() => applyFilters({ ...filters, page: filters.page + 1 })}>下一页</button></div>
      </section>
    </>}
    {detail && <div className="flex justify-between"><button className={button} onClick={() => go("/evaluation/literature")}>返回列表</button>{paper && !editing && <button className={button} onClick={() => setEditing(true)}><Pencil size={15} className="mr-1 inline" />编辑</button>}</div>}
    {paper && !!paper.warnings?.length && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">待补充：{paper.warnings.join("；")}</div>}
    {detail && !editing && paper && <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,45%)]">
      <div className="space-y-5"><section className="rounded-xl border bg-white p-6"><div className="flex flex-wrap items-center gap-2 text-xs"><span className="rounded bg-slate-100 px-2 py-1">{paper.id}</span><span className="rounded bg-blue-50 px-2 py-1">{paper.registration === "draft" ? "草稿" : "已登记"}</span><span className="rounded bg-slate-100 px-2 py-1">{paper.usage === "normal" ? "正常" : "已停用"}</span></div><h2 className="mt-4 text-xl font-semibold">{paper.title}</h2><dl className="mt-5 grid gap-4 text-sm sm:grid-cols-2">{[["作者", authorNames(paper.authors) || (paper.authors_unknown ? "未知" : "未填写")], ["发表形式", paper.publication_type || "未填写"], ["发表载体", paper.venue || (paper.venue_unknown ? "未知" : "未填写")], ["发表年份", paper.year ?? (paper.year_unknown ? "未知" : "未填写")], ["语言", `${paper.language || "未填写"}${paper.language_note ? ` · ${paper.language_note}` : ""}`], ["DOI", paper.doi || "—"]].map(([k, v]) => <div key={String(k)}><dt className="text-slate-500">{k}</dt><dd className="mt-1 break-words">{k === "DOI" && paper.doi ? <a className="text-emerald-700 underline" href={`https://doi.org/${paper.doi}`} target="_blank" rel="noopener noreferrer">{paper.doi}</a> : v}</dd></div>)}</dl></section><details className="rounded-xl border bg-white p-5"><summary className="cursor-pointer font-semibold">来源与补充说明</summary><dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2">{[["来源链接", paper.source_url || "—"], ["出处说明", paper.source_note || "—"], ["版本说明", paper.version_note || "—"], ["内部备注", paper.internal_note || "—"]].map(([key, value]) => <div key={key}><dt className="text-slate-500">{key}</dt><dd className="mt-1 break-words">{key === "来源链接" && paper.source_url ? <a className="text-emerald-700 underline" href={paper.source_url} target="_blank" rel="noopener noreferrer">{paper.source_url}</a> : value}</dd></div>)}</dl>{paper.abstract && <div className="mt-4 text-sm"><strong>摘要</strong><p className="mt-2 whitespace-pre-wrap text-slate-700">{paper.abstract}</p></div>}</details>
        <section className="rounded-xl border bg-white p-6"><h3 className="font-semibold">分类标签</h3><div className="mt-3 space-y-2">{taxonomy.dimensions.map((dim) => { const entries = taxonomy.tags.filter((tag) => tag.dimension_id === dim.id && paper.tag_ids.includes(tag.id)); return entries.length ? <p key={dim.id} className="text-sm"><span className="text-slate-500">{dim.name}：</span>{entries.map((tag) => <button key={tag.id} className="mr-2 text-emerald-800 underline" onClick={() => { applyFilters({ ...emptyFilters(), tags: [tag.id], usage: "all", include_disabled_tags: !tag.enabled }); go("/evaluation/literature"); }}>{tag.path}</button>)}</p> : null; })}{paper.tag_ids.length === 0 && <p className="text-sm text-slate-500">未打标（全局），可在编辑时逐步补充分类。</p>}</div></section>
        <section className="rounded-xl border bg-white p-6"><h3 className="font-semibold">关联文献</h3><div className="mt-3 space-y-2 text-sm">{paper.related_papers?.length ? paper.related_papers.map((related) => <p key={related.id}>{related.deleted ? "关联文献已删除" : <button className="text-emerald-700 underline" onClick={() => go(`/evaluation/literature/${related.id}`)}>{related.title}</button>}</p>) : "暂无关联"}</div></section>
        <section className="rounded-xl border bg-white p-6"><h3 className="font-semibold">操作记录</h3><div className="mt-4 space-y-3">{paper.events?.map((event) => <details key={event.id} className="rounded-lg border p-3 text-sm"><summary className="cursor-pointer">{event.summary || event.action} · {event.actor} · {fmt(event.at)}{event.reason ? ` · ${event.reason}` : ""}</summary><div className="mt-3 grid gap-2 sm:grid-cols-2"><pre className="overflow-auto rounded bg-slate-50 p-2 text-xs">变更前：{JSON.stringify(event.before, null, 2)}</pre><pre className="overflow-auto rounded bg-slate-50 p-2 text-xs">变更后：{JSON.stringify(event.after, null, 2)}</pre></div></details>)}</div></section></div>
      <aside className="space-y-5 lg:sticky lg:top-4">{pdfPane}<section className="rounded-xl border bg-white p-5 text-sm"><h3 className="font-semibold">协作信息</h3><p className="mt-3">创建：{paper.created_by} · {fmt(paper.created_at)}</p><p className="mt-2">登记：{paper.registered_by || "—"} · {fmt(paper.registered_at)}</p><p className="mt-2">最近编辑：{paper.updated_by} · {fmt(paper.updated_at)}</p></section><section className="rounded-xl border bg-white p-5"><div className="flex flex-wrap gap-2"><button className={button} disabled={busy} onClick={() => void paperAction(paper.usage === "normal" ? "disable" : "restore")}>{paper.usage === "normal" ? "停用" : "恢复"}</button><button className={`${button} text-red-700`} disabled={busy} onClick={() => void paperAction("delete")}><Trash2 size={14} className="mr-1 inline" />删除</button></div></section></aside>
    </div>}
    {detail && editing && (detail === "new" || paper) && <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,45%)]"><div className="space-y-4 pb-20">
      <section className="rounded-xl border bg-white p-6"><h2 className="font-semibold">原始文件</h2><div ref={dropZone} className="mt-3 rounded-xl border-2 border-dashed border-slate-300 p-6 text-center" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length !== 1) { setError("一次只能上传一篇 PDF。"); return; } void uploadFile(e.dataTransfer.files[0]); }}><UploadCloud size={28} className="mx-auto text-slate-500" /><p className="mt-2 text-sm">拖拽单篇 PDF 到此，或选择文件（上限 {maxPdfMb} MB）</p><input ref={fileInput} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e: ChangeEvent<HTMLInputElement>) => { const selected = e.target.files?.[0]; e.target.value = ""; void uploadFile(selected); }} /><button className={`${button} mt-3`} disabled={uploadProgress !== null || !!paper && paper.registration === "registered"} onClick={() => fileInput.current?.click()}>选择 PDF</button>{uploadProgress !== null && <div className="mt-3 text-sm">上传中 {uploadProgress}% <button className="ml-2 text-red-700 underline" onClick={() => uploadXhr.current?.abort()}>取消</button></div>}{(uploadName || paper?.filename) && <p className="mt-2 text-xs text-slate-500">{uploadName || paper?.filename}</p>}</div>{paper?.registration === "registered" && <p className="mt-2 text-xs text-slate-500">已登记论文不支持替换原始 PDF。新版本请新建文献并关联原记录。</p>}</section>
      {suggestionPanel}
      <section className="grid gap-4 rounded-xl border bg-white p-5 md:grid-cols-2"><h2 className="md:col-span-2 font-semibold">论文基本信息</h2>
        {field("论文标题", <input className={input} maxLength={500} value={form.title} onChange={(e) => patch("title", e.target.value)} />, "文件名仅作初始建议，请核对正式标题。")}
        <div className="md:col-span-2">{field("作者（按论文署名顺序）", <div className="space-y-2">{form.authors.map((author, index) => <div key={index} className="flex gap-2"><select className="rounded-lg border p-2 text-sm" disabled={form.authors_unknown} value={author.kind} onChange={(e) => patch("authors", form.authors.map((item, i) => i === index ? { ...item, kind: e.target.value as Author["kind"] } : item))}><option value="person">个人</option><option value="institution">机构</option></select><input className={input} disabled={form.authors_unknown} maxLength={200} value={author.name} onChange={(e) => patch("authors", form.authors.map((item, i) => i === index ? { ...item, name: e.target.value } : item))} /><button type="button" className={button} onClick={() => patch("authors", form.authors.filter((_, i) => i !== index))}>移除</button></div>)}<button type="button" className={button} disabled={form.authors_unknown} onClick={() => patch("authors", [...form.authors, { name: "", kind: "person" }])}>添加作者</button><label className="mt-1 flex items-center gap-2 text-xs"><input type="checkbox" checked={form.authors_unknown} onChange={(e) => { setForm({ ...form, authors_unknown: e.target.checked, authors: e.target.checked ? [] : form.authors }); setDirty(true); }} />未知</label></div>)}</div>
        {field("发表形式", <select className={input} value={form.publication_type || ""} onChange={(e) => patch("publication_type", e.target.value || null)}><option value="">请选择</option>{["期刊论文", "会议论文", "预印本", "其他学术论文"].map((v) => <option key={v}>{v}</option>)}</select>)}
        {field("发表载体", <><input className={input} disabled={form.venue_unknown} value={form.venue} placeholder={form.publication_type === "预印本" ? "预印本平台" : form.publication_type === "会议论文" ? "会议名称" : "期刊或发表载体名称"} onChange={(e) => patch("venue", e.target.value)} /><label className="mt-1 flex items-center gap-2 text-xs"><input type="checkbox" checked={form.venue_unknown} onChange={(e) => { setForm({ ...form, venue_unknown: e.target.checked, venue: e.target.checked ? "" : form.venue }); setDirty(true); }} />未知</label></>)}
        {field("发表年份", <><input type="number" min="1000" max="3000" className={input} disabled={form.year_unknown} value={form.year ?? ""} onChange={(e) => patch("year", e.target.value ? Number(e.target.value) : null)} /><label className="mt-1 flex items-center gap-2 text-xs"><input type="checkbox" checked={form.year_unknown} onChange={(e) => { setForm({ ...form, year_unknown: e.target.checked, year: e.target.checked ? null : form.year }); setDirty(true); }} />未知</label></>)}
        {field("论文语言", <><select className={input} value={form.language || ""} onChange={(e) => patch("language", e.target.value || null)}><option value="">请选择</option>{["中文", "英文", "其他"].map((v) => <option key={v}>{v}</option>)}</select>{form.language === "其他" && <input className={`${input} mt-2`} placeholder="请说明语言" value={form.language_note} onChange={(e) => patch("language_note", e.target.value)} />}</>)}
        {field("DOI", <input className={input} value={form.doi} onChange={(e) => patch("doi", e.target.value)} onBlur={() => void checkDoi()} placeholder="10.xxxx/… 或 DOI 链接" />)}
        {duplicates.length > 0 && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm md:col-span-2"><strong>相同 DOI 的文献</strong>{duplicates.map((item) => <label key={item.id} className="mt-2 flex items-center gap-2"><input type="checkbox" checked={form.related_paper_ids.includes(item.id)} onChange={(e) => patch("related_paper_ids", e.target.checked ? [...form.related_paper_ids, item.id] : form.related_paper_ids.filter((id) => id !== item.id))} /><span>{item.title}（{item.id}，{item.usage === "disabled" ? "已停用" : "正常"}）</span></label>)}<label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={form.confirm_same_doi} onChange={(e) => patch("confirm_same_doi", e.target.checked)} />确认作为不同版本继续登记</label></div>}
      </section>
      <details className="rounded-xl border bg-white p-5"><summary className="cursor-pointer font-semibold">来源与补充说明</summary><div className="mt-4 grid gap-4 md:grid-cols-2">{field("来源链接", <input className={input} type="url" value={form.source_url} onChange={(e) => patch("source_url", e.target.value)} placeholder="https://…" />)}{field("出处说明", <textarea className={input} maxLength={2000} rows={3} value={form.source_note} onChange={(e) => patch("source_note", e.target.value)} />)}{field("摘要", <textarea className={input} maxLength={20000} rows={5} value={form.abstract} onChange={(e) => patch("abstract", e.target.value)} />)}{field("版本／差异说明", <input className={input} maxLength={2000} value={form.version_note} onChange={(e) => patch("version_note", e.target.value)} />)}{field("关联文献", <RelatedPapers value={form.related_paper_ids} initial={paper?.related_papers || []} selfId={paper?.id} request={request} onChange={(ids) => patch("related_paper_ids", ids)} />)}{field("内部备注", <textarea className={input} maxLength={2000} rows={3} value={form.internal_note} onChange={(e) => patch("internal_note", e.target.value)} />)}</div></details>
      <section data-field="分类标签" tabIndex={-1} className="space-y-4 rounded-xl border bg-white p-6"><h2 className="font-semibold">分类标签</h2>{errorField === "分类标签" && error && <p className="text-sm text-red-700">{error}</p>}<TagCascader dimensions={taxonomy.dimensions} nodes={taxonomy.tags} value={form.tag_ids} onChange={(ids) => patch("tag_ids", ids)} mode="assign" /></section>
      <div className="sticky bottom-0 flex flex-wrap justify-end gap-2 border-t bg-white/95 p-4 shadow-lg"><button className={button} onClick={cancelEdit}>取消</button>{paper?.registration !== "registered" && <button className={button} disabled={busy || extracting || uploadProgress !== null} onClick={() => void save("draft")}>保存草稿</button>}<button className={primary} disabled={busy || extracting || uploadProgress !== null} onClick={() => void save("register")}>{paper?.registration === "registered" ? "保存修改" : "完成登记"}</button></div>
    </div><aside className="lg:sticky lg:top-4">{pdfPane}</aside></div>}
    {detail && detail !== "new" && !paper && !error && <p className="text-sm text-slate-500">正在加载文献…</p>}
  </div>;
}

function RelatedPapers({ value, initial, selfId, request, onChange }: {
  value: string[]; initial: { id: string; title: string; deleted: boolean }[]; selfId?: string;
  request: <T>(path: string, init?: RequestInit) => Promise<T>; onChange: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Paper[]>([]);
  const [known, setKnown] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      void request<ListResult>(`/papers?usage=all&page_size=20&keyword=${encodeURIComponent(query)}`).then((result) => {
        if (cancelled) return;
        setResults(result.items.filter((p) => p.id !== selfId));
        setKnown((old) => ({ ...old, ...Object.fromEntries(result.items.map((p) => [p.id, p.title])) }));
        setError("");
      }).catch((e) => { if (!cancelled) setError(errorMessage(e)); });
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query, request, selfId]);
  return <div className="space-y-2">
    <input className={input} aria-label="搜索关联文献" placeholder="搜索标题、作者、DOI 或文献 ID" value={query} onChange={(e) => setQuery(e.target.value)} />
    {value.map((id) => <div key={id} className="flex items-center justify-between gap-2 rounded bg-emerald-50 p-2 text-xs"><span>{initial.find((p) => p.id === id)?.title || known[id] || id}</span><button className="shrink-0 text-emerald-800 underline" type="button" onClick={() => onChange(value.filter((v) => v !== id))}>移除关联</button></div>)}
    <div className="max-h-40 overflow-auto rounded border">{results.filter((p) => !value.includes(p.id)).map((p) => <button key={p.id} type="button" className="block w-full border-b p-2 text-left text-xs hover:bg-slate-50" disabled={value.length >= 20} onClick={() => onChange([...value, p.id])}>{p.title}<span className="mt-1 block text-slate-500">{p.id}{p.usage === "disabled" ? " · 已停用" : ""}</span></button>)}{results.length === 0 && <p className="p-2 text-xs text-slate-500">暂无匹配文献</p>}</div>
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
  </div>;
}

function TagManager({ taxonomy, selectedDimension, setSelectedDimension, refresh, request, run, busy, error, notice, setNotice }: {
  taxonomy: { dimensions: Dimension[]; tags: Tag[] }; selectedDimension: string; setSelectedDimension: (id: string) => void; refresh: () => Promise<void>;
  request: <T>(path: string, init?: RequestInit) => Promise<T>; run: (task: () => Promise<void>) => Promise<void>; busy: boolean; error: string; notice: string; setNotice: (value: string) => void;
}) {
  const [dimensionForm, setDimensionForm] = useState({ name: "", description: "", selection: "multiple" as "single" | "multiple", required: false, enabled: true, sort_order: 0 });
  const [dimensionEdit, setDimensionEdit] = useState("");
  const [tagForm, setTagForm] = useState({ name: "", description: "", parent_id: "", enabled: true, sort_order: 0 });
  const [tagEdit, setTagEdit] = useState("");
  const [history, setHistory] = useState<Event[]>([]);
  const active = taxonomy.dimensions.find((dim) => dim.id === selectedDimension) || taxonomy.dimensions[0];
  const treeTags: Tag[] = [];
  if (active) {
    const inDimension = taxonomy.tags.filter((tag) => tag.dimension_id === active.id);
    const visit = (parent: string | null) => {
      inDimension.filter((tag) => tag.parent_id === parent).sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)).forEach((tag) => { treeTags.push(tag); visit(tag.id); });
    };
    visit(null);
  }
  const json = (method: string, value: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) });
  async function saveDimension(event: FormEvent) { event.preventDefault(); await run(async () => { await request(dimensionEdit ? `/dimensions/${dimensionEdit}` : "/dimensions", json(dimensionEdit ? "PUT" : "POST", dimensionForm)); await refresh(); setDimensionEdit(""); setDimensionForm({ name: "", description: "", selection: "multiple", required: false, enabled: true, sort_order: 0 }); setNotice("维度已保存。"); }); }
  async function saveTag(event: FormEvent) { event.preventDefault(); if (!active) return; await run(async () => { await request(tagEdit ? `/tags/${tagEdit}` : `/dimensions/${active.id}/tags`, json(tagEdit ? "PUT" : "POST", { ...tagForm, parent_id: tagForm.parent_id || null })); await refresh(); setTagEdit(""); setTagForm({ name: "", description: "", parent_id: "", enabled: true, sort_order: 0 }); setNotice("标签已保存。"); }); }
  async function remove(kind: "tag" | "dimension", id: string, name: string) { if (!window.confirm(`确认删除“${name}”？被引用的项目需先停用。`)) return; await run(async () => { await request(kind === "tag" ? `/tags/${id}` : `/dimensions/${id}`, { method: "DELETE" }); await refresh(); setNotice("已删除。"); }); }
  async function loadHistory(kind: "tag" | "dimension", id: string) { await run(async () => setHistory(await request<Event[]>(`/events/${kind}/${id}`))); }
  return <div className="space-y-5">{error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}{notice && <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</div>}
    <div className="grid gap-5 xl:grid-cols-[20rem_minmax(0,1fr)]"><section className="space-y-4 rounded-xl border bg-white p-5"><h2 className="font-semibold">标签维度</h2><div className="space-y-2">{taxonomy.dimensions.map((dim) => <button key={dim.id} className={`block w-full rounded-lg border p-3 text-left text-sm ${active?.id === dim.id ? "border-emerald-500 bg-emerald-50" : ""}`} onClick={() => { setSelectedDimension(dim.id); setTagEdit(""); setTagForm({ name: "", description: "", parent_id: "", enabled: true, sort_order: 0 }); setHistory([]); }}><span className="font-medium">{dim.name}</span>{!dim.enabled && "（已停用）"}<span className="block text-xs text-slate-500">{dim.selection === "single" ? "单选" : "多选"} · {dim.required ? "登记必填" : "选填"}</span></button>)}</div><form className="space-y-3 border-t pt-4" onSubmit={(e) => void saveDimension(e)}><h3 className="text-sm font-semibold">{dimensionEdit ? "编辑维度" : "新增维度"}</h3><input required maxLength={50} className={input} placeholder="维度名称" value={dimensionForm.name} onChange={(e) => setDimensionForm({ ...dimensionForm, name: e.target.value })} /><details open={!!dimensionEdit} className="rounded-lg border p-3"><summary className="cursor-pointer text-xs text-slate-600">更多维度设置（默认多选、选填）</summary><div className="mt-3 space-y-3"><textarea className={input} placeholder="维度说明" value={dimensionForm.description} onChange={(e) => setDimensionForm({ ...dimensionForm, description: e.target.value })} /><select className={input} value={dimensionForm.selection} onChange={(e) => setDimensionForm({ ...dimensionForm, selection: e.target.value as "single" | "multiple" })}><option value="multiple">多选</option><option value="single">单选</option></select><label className="flex gap-2 text-sm"><input type="checkbox" checked={dimensionForm.required} onChange={(e) => setDimensionForm({ ...dimensionForm, required: e.target.checked })} />登记必填</label><label className="flex gap-2 text-sm"><input type="checkbox" checked={dimensionForm.enabled} onChange={(e) => setDimensionForm({ ...dimensionForm, enabled: e.target.checked })} />启用</label><label className="block text-sm">展示顺序<input type="number" className={input} value={dimensionForm.sort_order} onChange={(e) => setDimensionForm({ ...dimensionForm, sort_order: Number(e.target.value) })} /></label></div></details><div className="flex gap-2"><button className={primary} disabled={busy}>保存维度</button>{dimensionEdit && <button type="button" className={button} onClick={() => { setDimensionEdit(""); setDimensionForm({ name: "", description: "", selection: "multiple", required: false, enabled: true, sort_order: 0 }); }}>取消</button>}</div></form></section>
      <div className="space-y-5">{active ? <><section className="rounded-xl border bg-white p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">{active.name}</h2><p className="mt-1 text-sm text-slate-500">{active.description || "暂无说明"}</p></div><div className="flex gap-2"><button className={button} onClick={() => { setDimensionEdit(active.id); setDimensionForm({ name: active.name, description: active.description, selection: active.selection, required: !!active.required, enabled: !!active.enabled, sort_order: active.sort_order }); }}>编辑维度</button><button className={button} onClick={() => void loadHistory("dimension", active.id)}>记录</button><button className={`${button} text-red-700`} onClick={() => void remove("dimension", active.id, active.name)}>删除</button></div></div></section>
        <section className="rounded-xl border bg-white p-5"><div className="mb-4 flex justify-between"><h2 className="font-semibold">标签树</h2><Link href="/evaluation/literature" className="text-sm text-emerald-700 underline">查看文献</Link></div>
          <TaxonomyTree key={active.id} nodes={treeTags} onAdd={async (parent_id, name) => { await request(`/dimensions/${active.id}/tags`, json("POST", { name, parent_id })); await refresh(); setNotice("标签已保存。"); }} description={(node) => { const tag = treeTags.find((t) => t.id === node.id)!; return `${tag.description || ""}${tag.description ? " · " : ""}直接关联 ${tag.paper_count} 篇`; }} actions={(node) => { const tag = treeTags.find((t) => t.id === node.id)!; return <><Link href={`/evaluation/literature?tag=${tag.id}`} className="text-emerald-700 underline">关联文献</Link><button className="text-emerald-700 underline" onClick={() => { setTagEdit(tag.id); setTagForm({ name: tag.name, description: tag.description, parent_id: tag.parent_id || "", enabled: !!tag.enabled, sort_order: tag.sort_order }); }}>编辑</button><button className="text-emerald-700 underline" onClick={() => void loadHistory("tag", tag.id)}>记录</button><button className="text-red-700 underline" onClick={() => void remove("tag", tag.id, tag.name)}>删除</button></>; }} />
        </section>
        {tagEdit && <form className="space-y-3 rounded-xl border bg-white p-5" onSubmit={(e) => void saveTag(e)}><h2 className="font-semibold">{tagEdit ? "编辑标签" : "新增标签"}</h2><div className="grid gap-3 md:grid-cols-2"><input required maxLength={50} className={input} placeholder="标签名称" value={tagForm.name} onChange={(e) => setTagForm({ ...tagForm, name: e.target.value })} /><select className={input} value={tagForm.parent_id} onChange={(e) => setTagForm({ ...tagForm, parent_id: e.target.value })}><option value="">一级标签</option>{taxonomy.tags.filter((tag) => tag.dimension_id === active.id && tag.id !== tagEdit).map((tag) => <option key={tag.id} value={tag.id}>{tag.path}</option>)}</select><textarea className={input} placeholder="标签说明和适用边界" value={tagForm.description} onChange={(e) => setTagForm({ ...tagForm, description: e.target.value })} /><label className="text-sm">同级顺序<input type="number" className={input} value={tagForm.sort_order} onChange={(e) => setTagForm({ ...tagForm, sort_order: Number(e.target.value) })} /></label></div><label className="flex gap-2 text-sm"><input type="checkbox" checked={tagForm.enabled} onChange={(e) => setTagForm({ ...tagForm, enabled: e.target.checked })} />启用</label><div className="flex gap-2"><button className={primary} disabled={busy}>保存标签</button>{tagEdit && <button className={button} type="button" onClick={() => { setTagEdit(""); setTagForm({ name: "", description: "", parent_id: "", enabled: true, sort_order: 0 }); }}>取消</button>}</div></form>}</> : <div className="rounded-xl border bg-white p-6 text-sm text-slate-500">请先创建标签维度。</div>}
        {history.length > 0 && <section className="rounded-xl border bg-white p-5"><h2 className="font-semibold">变更记录</h2>{history.map((event) => <details key={event.id} className="mt-3 rounded border p-3 text-sm"><summary>{event.summary || event.action} · {event.actor} · {fmt(event.at)}</summary><pre className="mt-2 overflow-auto text-xs">{JSON.stringify({ before: event.before, after: event.after }, null, 2)}</pre></details>)}</section>}
      </div></div>
  </div>;
}
