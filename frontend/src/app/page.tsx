"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowDown, Leaf, LoaderCircle, Plus } from "lucide-react";
import { AnswerCard } from "@/components/chat/answer-card";
import { ChatError } from "@/components/chat/chat-error";
import { ChatForm } from "@/components/chat/chat-form";
import { apiBaseUrl, ApiError, checkSessionFiles, getOrCreateOperatorId, postChat, uploadFile } from "@/lib/api";
import { UNKNOWN_FAILURE } from "@/lib/error-messages";
import type { ChatHistoryMessage, ChatResponse, FileReceipt, SessionFile } from "@/lib/types";

type Turn = { id: string; role: "user"; content: string; filename?: string } | { id: string; role: "assistant"; content: string; response: ChatResponse };
type Retry = { query: string; attachments: FileReceipt[]; history: ChatHistoryMessage[] };
export default function Home() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState(makeId);
  const [files, setFiles] = useState<SessionFile[]>([]);
  const [uploadNotice, setUploadNotice] = useState("");
  const [pending, setPending] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [retry, setRetry] = useState<Retry | null>(null);
  const [uploading, setUploading] = useState(false);
  const [showLatest, setShowLatest] = useState(false);
  const [exampleLoading, setExampleLoading] = useState(false);
  const busy = useRef(false);
  const panel = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const sessionFiles = files.flatMap((file) => file.receipt && file.phase === "stored" ? [file.receipt] : []);
  useEffect(() => { getOrCreateOperatorId(); }, []);
  useEffect(() => { if (follow.current) panel.current?.scrollTo({ top: panel.current.scrollHeight, behavior: "smooth" }); }, [turns, pending]);
  useEffect(() => {
    if (!pending) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [pending]);
  async function handleFiles(selected: File[]) {
    if (busy.current) return;
    busy.current = true; setUploading(true); setUploadNotice(""); setError(null); setRetry(null);
    let known = files.filter((file) => file.receipt && file.phase === "stored");
    const duplicates: string[] = [];
    const notices: string[] = [];
    try {
      if (known.length) {
        const status = await checkSessionFiles(known.map((file) => file.receipt!.file_id));
        const expired = new Set(status.files.filter((file) => file.status === "expired").map((file) => file.file_id));
        const expiredNames = known.filter((file) => expired.has(file.receipt!.file_id)).map((file) => file.filename);
        known = known.filter((file) => !expired.has(file.receipt!.file_id));
        setFiles((old) => old.filter((file) => !file.receipt || !expired.has(file.receipt.file_id)));
        if (expiredNames.length) notices.push(`会话文件已失效：${expiredNames.join("、")}。如需继续使用，请重新上传。`);
      }
      let count = known.length;
      let bytes = known.reduce((sum, file) => sum + file.size, 0);
      const hashes = new Set(known.map((file) => file.receipt!.sha256));
      for (const file of selected) {
        const slot: SessionFile = { clientId: makeId(), filename: file.name, size: file.size,
          phase: "uploading", progress: 0, receipt: null, used: false };
        let problem = "";
        if (!/\.xlsx?$/i.test(file.name)) problem = "请选择 .xls 或 .xlsx 文件。";
        else if (file.size > 10 * 1024 * 1024) problem = "每份文件不能超过 10 MiB。";
        if (!problem) {
          const hash = crypto.subtle ? Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await file.arrayBuffer())))
            .map((byte) => byte.toString(16).padStart(2, "0")).join("") : null;
          if (hash && hashes.has(hash)) { duplicates.push(file.name); continue; }
          if (count >= 5) problem = "每个会话最多保留 5 份文件。";
          else if (bytes + file.size > 40 * 1024 * 1024) problem = "会话文件合计不能超过 40 MiB。";
        }
        if (problem) {
          setFiles((old) => [...old, { ...slot, phase: "error", error: problem }]); continue;
        }
        setFiles((old) => [...old, slot]);
        try {
          const receipt = await uploadFile(file, (progress) => setFiles((old) => old.map((item) =>
            item.clientId === slot.clientId ? { ...item, progress } : item)));
          // Server digest also guards against repeated content within one upload batch.
          if (hashes.has(receipt.sha256)) {
            duplicates.push(file.name);
            setFiles((old) => old.filter((item) => item.clientId !== slot.clientId)); continue;
          }
          hashes.add(receipt.sha256); count++; bytes += file.size;
          setFiles((old) => old.map((item) => item.clientId === slot.clientId ?
            { ...item, phase: "stored", receipt, progress: 100 } : item));
        } catch (err) {
          const problem = err instanceof ApiError ? err : new ApiError("unknown", null, UNKNOWN_FAILURE);
          setFiles((old) => old.map((item) => item.clientId === slot.clientId ?
            { ...item, phase: "error", error: problem.userMessage } : item));
        }
      }
      if (duplicates.length) notices.push(`已跳过重复文件：${duplicates.join("、")}。本会话已上传，无需再次上传。`);
      setUploadNotice(notices.join(" "));
    } catch (err) {
      setUploadNotice(err instanceof ApiError ? err.userMessage : "文件读取失败，请重试。");
    } finally { busy.current = false; setUploading(false); }
  }
  async function loadExample() {
    if (busy.current) return;
    busy.current = true; setExampleLoading(true); setError(null);
    let receipt: FileReceipt;
    try {
      const response = await fetch(`${apiBaseUrl}/api/demo/examples/nitrogen`);
      if (!response.ok) throw new Error("example unavailable");
      const example = new File([await response.blob()], "Nbal_out.xls");
      receipt = await uploadFile(example);
      const id = makeId();
      setFiles([{ clientId: id, filename: receipt.filename, size: example.size, phase: "stored", progress: 100, receipt, used: false }]);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("demo_example_unavailable", null, "示例暂不可用，请重试或查看已保存案例。"));
      busy.current = false; setExampleLoading(false); return;
    }
    busy.current = false; setExampleLoading(false);
    await send("硝态氮淋失最大值及对应日序", undefined, receipt);
  }
  async function send(query: string, previous?: Retry, example?: FileReceipt) {
    if (busy.current) return;
    busy.current = true; follow.current = true;
    const attachments = example ? [example] : previous ? previous.attachments : sessionFiles;
    const history = example ? [] : previous?.history ?? turns.slice(-12).map((t) => ({ role: t.role, content: t.content.slice(0, 4000) }));
    setRetry({ query, attachments, history }); setError(null); setPending(true); setElapsed(0);
    if (!previous) setTurns((old) => [...old, { id: makeId(), role: "user", content: query, filename: attachments.map((file) => file.filename).join("、") || undefined }]);
    try {
      const response = await postChat(query, history, undefined, undefined, sessionId, undefined, getOrCreateOperatorId(), attachments.map((file) => file.file_id));
      setTurns((old) => [...old, { id: makeId(), role: "assistant", content: response.answer, response }]); setRetry(null);
      setFiles((old) => old.flatMap((item) => {
        const checked = response.attachments?.find((file) => file.file_id === item.receipt?.file_id);
        if (checked?.status === "expired") return [];
        if (checked?.status === "invalid") return [{ ...item, phase: "error" as const, error: "文件内容需修正，请重新上传。" }];
        return [{ ...item, used: item.used || attachments.some((file) => file.file_id === item.receipt?.file_id) }];
      }));
    } catch (err) {
      const problem = err instanceof ApiError ? err : new ApiError("unknown", null, UNKNOWN_FAILURE);
      setError(problem); if (problem.code === "file_not_found") {
        setFiles((old) => old.filter((item) => !attachments.some((file) => file.file_id === item.receipt?.file_id)));
        setRetry(null);
      }
    } finally { setPending(false); busy.current = false; }
  }
  function clear() {
    if (busy.current) return;
    setTurns([]); setFiles([]); setUploadNotice(""); setError(null); setRetry(null); setSessionId(makeId()); follow.current = true;
  }
  return <main className="flex h-dvh min-h-0 flex-col bg-slate-50/70">
    <header className="shrink-0 border-b bg-background px-4 py-3 sm:px-8"><div className="mx-auto flex max-w-4xl items-center justify-between gap-3">
      <div className="flex items-center gap-3"><span className="rounded-xl bg-emerald-50 p-2 text-emerald-800"><Leaf aria-hidden="true" className="size-5" /></span><div><h1 className="text-base font-semibold">农业模型助手</h1><p className="hidden text-xs text-muted-foreground sm:block">围绕问题，查看结果与依据</p></div></div>
      <nav className="flex items-center gap-3 text-xs"><Link href="/showcase" className="text-muted-foreground hover:underline">查看评测后台</Link><button disabled={pending || uploading || exampleLoading} onClick={clear} className="flex items-center gap-1 rounded-lg border px-3 py-2 disabled:opacity-40"><Plus className="size-4" />新对话</button></nav>
    </div></header>
    <div className="relative min-h-0 flex-1"><div ref={panel} aria-label="对话记录" className="h-full overflow-y-auto" onScroll={(e) => { const node = e.currentTarget; follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 160; setShowLatest(!follow.current); }}>
      <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:px-8">
        {!turns.length && <section className="mx-auto max-w-2xl py-8 sm:py-14"><p className="text-xs font-medium text-emerald-700">文献问答 · 结果表分析</p><h2 className="mt-3 text-2xl font-semibold tracking-tight">从一个问题，找到结果与依据</h2><p className="mt-3 text-sm leading-7 text-muted-foreground">无需注册。可以直接提问，或使用示例体验结果表分析。支持 WHCNS 氮/水平衡输出表的整表极值查询，暂不运行模型仿真。</p><div className="mt-6 grid gap-3 sm:grid-cols-2"><button disabled={pending || uploading || exampleLoading} className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-left disabled:opacity-50" onClick={() => void loadExample()}><span className="block font-medium text-emerald-950">{exampleLoading ? "正在准备示例…" : "使用示例文件体验"}</span><span className="mt-2 block text-xs leading-6 text-emerald-800">自动加载氮平衡结果表，实际计算最大值并查看单元格依据。</span></button><button disabled={pending || uploading || exampleLoading} className="rounded-xl border bg-background p-5 text-left" onClick={() => void send("氮素淋失主要受哪些因素影响？")}><span className="block font-medium">试试文献问答</span><span className="mt-2 block text-xs leading-6 text-muted-foreground">哪些因素影响氮素淋失？查看回答和参考文献。</span></button></div><div className="mt-4 flex flex-wrap gap-4 text-xs"><button disabled={pending || uploading || exampleLoading} className="text-emerald-800 hover:underline" onClick={() => void send("你能做什么？")}>了解支持的能力</button><Link href="/showcase/cases/file-extrema" className="text-muted-foreground hover:underline">查看已保存示例</Link></div></section>}
        {turns.map((t) => t.role === "user" ? <div key={t.id} className="flex justify-end"><div className="max-w-[88%] rounded-2xl rounded-tr-sm bg-emerald-900 px-4 py-3 text-sm leading-7 text-white"><p className="whitespace-pre-wrap break-words">{t.content}</p>{t.filename && <p className="mt-2 break-all border-t border-white/20 pt-1 text-xs opacity-80">附件：{t.filename}</p>}</div></div> : <AnswerCard key={t.id} response={t.response} scope={t.id} />)}
        {pending && <div role="status" className="rounded-2xl border bg-background p-5 text-sm"><p className="flex items-center gap-2"><LoaderCircle className="size-4 animate-spin" />正在处理问题 · {elapsed} 秒</p>{elapsed >= 10 && <p className="mt-2 text-xs text-muted-foreground">检索或生成仍在进行，请稍候。完成后会显示结果及可核查的依据。</p>}</div>}
        {sessionFiles.length > 0 && turns.some((t) => t.role === "assistant" && t.response.file_evidence.length > 0) && !pending && <div className="flex flex-wrap gap-2">{["那最小值呢？"].map((q) => <button key={q} disabled={uploading || exampleLoading} className="rounded-full border bg-white px-3 py-2 text-xs text-emerald-800" onClick={() => void send(q)}>{q}</button>)}</div>}
        {error && <ChatError error={error} onRetry={retry && !pending ? () => void send(retry.query, retry) : undefined} />}
        {error && <Link href="/showcase/cases/file-extrema" className="inline-block text-sm text-emerald-800 underline">也可以查看已保存的历史示例</Link>}
      </div>
    </div>{showLatest && <button className="absolute bottom-3 right-5 flex items-center gap-1 rounded-full border bg-background px-3 py-2 text-xs shadow" onClick={() => { follow.current = true; panel.current?.scrollTo({ top: panel.current.scrollHeight, behavior: "smooth" }); }}><ArrowDown className="size-3" />最新消息</button>}</div>
    <footer className="shrink-0 border-t bg-background/90 px-3 py-3 sm:px-8"><div className="mx-auto max-w-4xl space-y-2">
      <ChatForm key={sessionId} onSubmit={(q) => void send(q)} disabled={pending || uploading || exampleLoading} onFiles={handleFiles}
        files={files.filter((file) => !file.hidden)} onRemoveFile={(id) => {
          setFiles((old) => old.flatMap((item) => item.clientId !== id ? [item] : item.used ? [{ ...item, hidden: true }] : []));
          setRetry(null); setError(null);
        }} />
      {uploadNotice && <p role="status" className="break-words px-2 text-xs text-emerald-800">{uploadNotice}</p>}
      {files.some((file) => file.hidden) && <button type="button" className="px-2 text-xs text-muted-foreground hover:underline"
        onClick={() => setFiles((old) => old.map((file) => ({ ...file, hidden: false })))}>展开已收起的会话文件（{files.filter((file) => file.hidden).length}）</button>}
      <p className="text-center text-[11px] leading-5 text-muted-foreground">研究原型 · 结果请结合原文核对 · 请勿上传敏感资料；访客对话不在公开后台展示</p>
    </div></footer>
  </main>;
}
function makeId() { return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`; }
