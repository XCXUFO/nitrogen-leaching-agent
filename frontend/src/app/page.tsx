"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type SetStateAction } from "react";
import { ArrowDown, LoaderCircle } from "lucide-react";
import { AnswerCard } from "@/components/chat/answer-card";
import { ChatError } from "@/components/chat/chat-error";
import { ChatForm } from "@/components/chat/chat-form";
import { ExecutionProgress } from "@/components/chat/execution-progress";
import { FollowUpSuggestions } from "@/components/chat/follow-up-suggestions";
import { makeId, retainPendingRun, useConversations, type Conversation, type Turn, type Retry } from "@/components/chat/use-conversations";
import { ApiError, checkSessionFiles, getOrCreateOperatorId, postChat, releaseSessionFiles, uploadFile } from "@/lib/api";
import { UNKNOWN_FAILURE } from "@/lib/error-messages";
import type { ChatRunView, SessionFile } from "@/lib/types";

import { ChatShell } from "@/components/chat/chat-shell";
import { useAccountSession } from "@/components/account-session";

const exampleCardClassName = "rounded-xl border bg-background p-5 text-left disabled:opacity-50";

function PendingRunRestorer({ request, onResume }: { request: Retry; onResume: (request: Retry) => void }) {
  const restored = useRef(false);
  useEffect(() => {
    if (!restored.current) { restored.current = true; onResume(request); }
  }, [request, onResume]);
  return null;
}

export default function Home() {
  const { session, ready } = useAccountSession();
  if (!ready) return <main role="status" className="p-8">正在恢复登录状态…</main>;
  return <ChatHome key={session?.user.tester_id ?? "visitor"} scope={session?.user.tester_id ?? "visitor"} />;
}
function ChatHome({ scope }: { scope: string }) {
  const { conversation, conversations, notice, update, create, select, historyReady, historyError,
    retryHistory, loadingMore, hasMoreHistory, loadMoreHistory } = useConversations(scope);
  if (!historyReady) return <main className="p-8"><p role={historyError ? "alert" : "status"}>{historyError || "正在加载历史会话…"}</p>
    {historyError && <button className="mt-4 underline" onClick={retryHistory}>重试加载历史会话</button>}</main>;
  return <ChatShell conversations={conversations} activeId={conversation.id} onCreate={create} onSelect={select}
    historyMore={hasMoreHistory ? { loading: loadingMore, load: loadMoreHistory } : undefined}>
    {conversations.map((item) => <ConversationWorkspace key={item.id} conversation={item}
      active={item.id === conversation.id} scope={scope} notice={notice} update={update} />)}
  </ChatShell>;
}

function ConversationWorkspace({ conversation, active, scope, notice, update }: {
  conversation: Conversation; active: boolean; scope: string; notice: string;
  update: ReturnType<typeof useConversations>["update"];
}) {
  const { id: sessionId, turns, files, draft, uploadNotice, error, retry } = conversation;
  const setTurns = (value: SetStateAction<Turn[]>) => update(sessionId, "turns", value);
  const setFiles = (value: SetStateAction<SessionFile[]>) => update(sessionId, "files", value);
  const setUploadNotice = (value: string) => update(sessionId, "uploadNotice", value);
  const setError = (value: ApiError | null) => update(sessionId, "error", value);
  const setRetry = (value: Retry | null) => update(sessionId, "retry", value);
  const [pending, setPending] = useState(false);
  const [progress, setProgress] = useState<ChatRunView>();
  const [recovering, setRecovering] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [showLatest, setShowLatest] = useState(false);
  const inputBlocked = pending || uploading || conversation.running;
  const busy = useRef(false);
  const panel = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const sessionFiles = files.flatMap((file) => file.receipt && file.phase === "stored" ? [file.receipt] : []);
  const pendingFiles = files.flatMap((file) => !file.used && file.receipt && file.phase === "stored" ? [file.receipt] : []);
  const latestTurn = turns.at(-1);
  const suggestMinimum = latestTurn?.role === "assistant" && latestTurn.response.file_evidence.length > 0
    && latestTurn.response.file_evidence.every((evidence) => evidence.operation === "max"
      && pendingFiles.some((file) => file.sha256 === evidence.sha256));
  useEffect(() => { getOrCreateOperatorId(); }, []);
  useEffect(() => { if (active) follow.current = true; }, [active]);
  useEffect(() => { if (follow.current) panel.current?.scrollTo({ top: panel.current.scrollHeight, behavior: "smooth" }); }, [turns, pending, active]);
  useEffect(() => {
    if (!pending) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [pending]);
  async function handleFiles(selected: File[]) {
    if (busy.current || conversation.running) return;
    busy.current = true; setUploading(true); setUploadNotice(""); setError(null); setRetry(null);
    update(sessionId, "preparing", true);
    let known = files.filter((file) => file.receipt && file.phase === "stored");
    const duplicates: string[] = [];
    const notices: string[] = [];
    try {
      if (known.length) {
        const status = await checkSessionFiles(known.map((file) => file.receipt!.file_id), sessionId);
        const expired = new Set(status.files.filter((file) => file.status === "expired").map((file) => file.file_id));
        const expiredNames = known.filter((file) => expired.has(file.receipt!.file_id)).map((file) => file.filename);
        known = known.filter((file) => !expired.has(file.receipt!.file_id));
        setFiles((old) => old.filter((file) => !file.receipt || !expired.has(file.receipt.file_id)));
        if (expiredNames.length) notices.push(`会话文件已失效：${expiredNames.join("、")}。如需继续使用，请重新上传。`);
      }
      let count = known.length;
      const hashes = new Set(known.filter((file) => !file.used).map((file) => file.receipt!.sha256));
      for (const file of selected) {
        const slot: SessionFile = { clientId: makeId(), filename: file.name, size: file.size,
          phase: "uploading", progress: 0, receipt: null, used: false };
        let problem = "";
        if (!/\.(?:xls|xlsx|txt|md|pdf|doc|docx)$/i.test(file.name)) problem = "支持 .xls、.xlsx、.txt、.md、.pdf、.doc、.docx 文件。";
        else if (file.size > 10 * 1024 * 1024) problem = "每份文件不能超过 10 MiB。";
        if (!problem) {
          const hash = crypto.subtle ? Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await file.arrayBuffer())))
            .map((byte) => byte.toString(16).padStart(2, "0")).join("") : null;
          if (hash && hashes.has(hash)) { duplicates.push(file.name); continue; }
          if (count >= 10) problem = "每个会话最多上传 10 份文件。";
        }
        if (problem) {
          setFiles((old) => [...old, { ...slot, phase: "error", error: problem }]); continue;
        }
        setFiles((old) => [...old, slot]);
        try {
          const receipt = await uploadFile(file, (progress) => setFiles((old) => old.map((item) =>
            item.clientId === slot.clientId ? { ...item, progress } : item)), sessionId);
          // Server digest also guards against repeated content within one upload batch.
          if (hashes.has(receipt.sha256)) {
            duplicates.push(file.name);
            await releaseSessionFiles([receipt.file_id], sessionId);
            setFiles((old) => old.filter((item) => item.clientId !== slot.clientId)); continue;
          }
          hashes.add(receipt.sha256); count++;
          setFiles((old) => old.map((item) => item.clientId === slot.clientId ?
            { ...item, phase: "stored", receipt, progress: 100 } : item));
        } catch (err) {
          const problem = err instanceof ApiError ? err : new ApiError("unknown", null, UNKNOWN_FAILURE);
          setFiles((old) => old.map((item) => item.clientId === slot.clientId ?
            { ...item, phase: "error", error: problem.userMessage } : item));
        }
      }
      if (duplicates.length) notices.push(`已跳过重复文件：${duplicates.join("、")}。本条消息已附加，无需重复上传。`);
      setUploadNotice(notices.join(" "));
    } catch (err) {
      setUploadNotice(err instanceof ApiError ? err.userMessage : "文件读取失败，请重试。");
    } finally { busy.current = false; setUploading(false); update(sessionId, "preparing", false); }
  }
  async function send(query: string, previous?: Retry, resumeOnly = false, caseIds?: string[]) {
    // A paused poll is still an unresolved submission. Only its recovery may
    // reuse this conversation; a new question must use a new conversation.
    if (busy.current || (conversation.running && !previous)) return;
    busy.current = true; follow.current = true;
    const attachments = previous ? previous.attachments : pendingFiles;
    const history = previous?.history ?? turns.slice(-12).map((t) => ({ role: t.role, content: t.content.slice(0, 4000) }));
    const request: Retry = { query, attachments, history, caseIds: previous?.caseIds ?? caseIds, answerId: previous?.answerId,
      turnId: previous?.turnId ?? makeId(), requestId: previous?.requestId ?? makeId(), rerunOfRunId: previous?.rerunOfRunId };
    const nextTurns: Turn[] = previous ? turns : [...turns, { id: request.turnId, role: "user", content: query, filename: attachments.map((file) => file.filename).join("、") || undefined }];
    const submittedIds = new Set(attachments.map((file) => file.file_id));
    const nextFiles = files.map((file) => file.receipt && submittedIds.has(file.receipt.file_id)
      ? { ...file, used: true } : file);
    retainPendingRun(scope, { ...conversation, files: nextFiles }, request, nextTurns);
    let latest: ChatRunView | undefined;
    setRetry(request); setError(null); setPending(true); setElapsed(0); setProgress(undefined); setRecovering(false);
    setFiles(nextFiles); setUploadNotice("");
    update(sessionId, "running", true);
    if (!previous) setTurns((old) => [...old, { id: request.turnId, role: "user", content: query, filename: attachments.map((file) => file.filename).join("、") || undefined }]);
    try {
      const response = await postChat(query, history, undefined, undefined, sessionId, undefined, getOrCreateOperatorId(), attachments.map((file) => file.file_id), {
        ...request, resumeOnly,
        onProgress: (value) => { latest = value; setProgress(value); },
        onConnectionChange: setRecovering,
      });
      setTurns((old) => request.answerId
        ? old.map((turn) => turn.id === request.answerId && turn.role === "assistant"
          ? { ...turn, content: response.answer, response, request, run: latest } : turn)
        : [...old, { id: makeId(), role: "assistant", content: response.answer, response, request, run: latest }]);
      setRetry(null);
      update(sessionId, "running", false);
      setFiles((old) => old.flatMap((item) => {
        const checked = response.attachments?.find((file) => file.file_id === item.receipt?.file_id);
        if (checked?.status === "expired") return [];
        if (checked?.status === "invalid") return [{ ...item, phase: "error" as const, error: "文件内容需修正，请重新上传。" }];
        return [{ ...item, used: item.used || attachments.some((file) => file.file_id === item.receipt?.file_id) }];
      }));
    } catch (err) {
      const problem = err instanceof ApiError ? err : new ApiError("unknown", null, UNKNOWN_FAILURE);
      if (problem.terminalRun && problem.runId) setRetry({ ...request, requestId: makeId(), rerunOfRunId: problem.runId });
      if (problem.terminalRun || problem.httpStatus === 410 || (problem.httpStatus !== null && !latest)) update(sessionId, "running", false);
      if (problem.code === "recovery_expired") setRetry(null);
      setError(problem); if (problem.code === "file_not_found") {
        setFiles((old) => old.filter((item) => !attachments.some((file) => file.file_id === item.receipt?.file_id)));
        setRetry(null);
      }
    } finally { setPending(false); busy.current = false; }
  }
  function canRegenerate(request: Retry) {
    if (request.recoveryExpired) return false;
    return (conversation.running && retry?.turnId === request.turnId)
      || request.attachments.every((attachment) => sessionFiles.some((file) => file.file_id === attachment.file_id));
  }
  function regenerate(turn: Extract<Turn, { role: "assistant" }>) {
    if (turns.at(-1)?.id !== turn.id || !canRegenerate(turn.request)) return;
    // An uncertain retry queries the same submission. A deliberate regeneration
    // of a completed answer starts a new run while retaining the original turn.
    const next = retry?.answerId === turn.id ? retry : { ...turn.request, answerId: turn.id,
      ...(turn.run ? { requestId: makeId(), rerunOfRunId: turn.run.run_id } : {}) };
    void send(turn.request.query, next);
  }
  return <>
    {conversation.restorePending && retry && <PendingRunRestorer request={retry} onResume={(request) => { update(sessionId, "restorePending", false); void send(request.query, request, true); }} />}
    {active && <>
    <div className="relative min-h-0 flex-1"><div ref={panel} aria-label="对话记录" className="h-full overflow-y-auto" onScroll={(e) => { const node = e.currentTarget; follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 160; setShowLatest(!follow.current); }}>
      <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:px-8">
        {!turns.length && <section className="mx-auto max-w-3xl py-8 sm:py-14">
          <h2 className="text-2xl font-semibold tracking-tight">从一个问题，找到结果与依据</h2>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <button type="button" disabled={pending || uploading} className={exampleCardClassName}
              onClick={() => void send("氮素淋失主要受哪些因素影响？")}>
              <span className="block font-medium">专业知识解答</span>
              <span className="mt-2 block text-xs leading-6 text-muted-foreground">哪些因素影响氮素淋失？查看回答和参考文献。</span>
            </button>
            <button type="button" disabled={pending || uploading} className={exampleCardClassName}
              onClick={() => void send("有哪些水氮管理相关的案例与措施可以参考？")}>
              <span className="block font-medium">案例</span>
              <span className="mt-2 block text-xs leading-6 text-muted-foreground">查找相关案例与措施，了解场景、做法与适用条件。</span>
            </button>
          </div>
          <div className="mt-4 flex flex-wrap gap-4 text-xs"><button disabled={pending || uploading} className="text-emerald-800 hover:underline" onClick={() => void send("你能做什么？")}>了解支持的能力</button></div>
        </section>}
        {turns.map((t) => t.role === "user" ? <div key={t.id} className="flex justify-end"><div className="max-w-[88%] rounded-2xl rounded-tr-sm bg-emerald-900 px-4 py-3 text-sm leading-7 text-white"><p className="whitespace-pre-wrap break-words">{t.content}</p>{t.filename && <p className="mt-2 break-all border-t border-white/20 pt-1 text-xs opacity-80">附件：{t.filename}</p>}</div></div> : <div key={t.id} className="space-y-2"><AnswerCard response={t.response} scope={t.id}
          onRegenerate={t.id === turns.at(-1)?.id ? () => regenerate(t) : undefined}
          regenerateDisabled={pending || uploading || !canRegenerate(t.request)}
          regenerating={pending && retry?.answerId === t.id}
          regenerateHint={t.id === turns.at(-1)?.id && !canRegenerate(t.request) ? (t.request.recoveryExpired ? "原运行的恢复窗口已结束，可以继续发送新问题。" : "原问题的附件已失效，请重新上传后再次提问。") : undefined} />{t.run && !t.run.result_saved && t.run.result && <p className="text-xs text-amber-800">本次结果尚未保存，关闭页面后可能无法找回。</p>}</div>)}
        {pending && (progress ? <ExecutionProgress run={progress} recovering={recovering} /> : <div role="status" className="rounded-2xl border bg-background p-5 text-sm"><p className="flex items-center gap-2"><LoaderCircle className="size-4 animate-spin" />{recovering ? "正在查询原运行" : "正在提交问题"} · {elapsed} 秒</p>{elapsed >= 10 && <p className="mt-2 text-xs text-muted-foreground">连接或处理仍在进行，请稍候。</p>}</div>)}
        {suggestMinimum && !pending && <div className="flex flex-wrap gap-2"><button disabled={inputBlocked} className="rounded-full border bg-white px-3 py-2 text-xs text-emerald-800" onClick={() => void send("那最小值呢？")}>那最小值呢？</button></div>}
        {!pending && !error && <FollowUpSuggestions turns={turns} disabled={inputBlocked} onSelect={(question, caseIds) => void send(question, undefined, false, caseIds)} />}
        {!pending && error && progress && <ExecutionProgress run={progress} />}
        {error && <ChatError error={error} onRetry={retry && !retry.answerId && !pending && !uploading ? () => void send(retry.query, retry) : undefined} />}
        {conversation.running && !pending && <p role="status" className="text-sm text-amber-900">原问题的执行状态尚未确认，请先重试找回结果，或新建对话继续提问。</p>}
        {error && <Link href="/showcase/cases/file-extrema" className="inline-block text-sm text-emerald-800 underline">也可以查看已保存的历史示例</Link>}
      </div>
    </div>{showLatest && <button className="absolute bottom-3 right-5 flex items-center gap-1 rounded-full border bg-background px-3 py-2 text-xs shadow" onClick={() => { follow.current = true; panel.current?.scrollTo({ top: panel.current.scrollHeight, behavior: "smooth" }); }}><ArrowDown className="size-3" />最新消息</button>}</div>
    <footer className="shrink-0 border-t bg-background/90 px-3 py-3 sm:px-8"><div className="mx-auto max-w-4xl space-y-2">
      <ChatForm key={sessionId} value={draft} onValueChange={(value) => update(sessionId, "draft", value)} onSubmit={(q) => void send(q)} disabled={inputBlocked} onFiles={handleFiles}
        files={files.filter((file) => !file.used)} onRemoveFile={(id) => {
          const removed = files.find((file) => file.clientId === id);
          if (removed?.receipt && !removed.used) void releaseSessionFiles([removed.receipt.file_id], sessionId);
          setFiles((old) => old.filter((item) => item.clientId !== id));
          setRetry(null); setError(null);
        }} />
      {notice && <p role="status" className="px-2 text-xs text-muted-foreground">{notice}</p>}
      {uploadNotice && <p role="status" className="break-words px-2 text-xs text-emerald-800">{uploadNotice}</p>}
    </div></footer>
    </>}
  </>;
}
