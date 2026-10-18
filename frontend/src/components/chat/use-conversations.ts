"use client";

import { useEffect, useRef, useState, type SetStateAction } from "react";
import { ApiError, checkSessionFiles, getAccountChatHistory, releaseSessionFiles } from "@/lib/api";
import type { ChatHistoryMessage, ChatResponse, ChatRunView, FileReceipt, SavedConversation, SessionFile } from "@/lib/types";

export type Turn = { id: string; role: "user"; content: string; filename?: string }
  | { id: string; role: "assistant"; content: string; response: ChatResponse; request: Retry; run?: ChatRunView };
export type Retry = { query: string; attachments: FileReceipt[]; history: ChatHistoryMessage[]; answerId?: string;
  turnId: string; requestId: string; rerunOfRunId?: string; recoveryExpired?: boolean };
export type Conversation = {
  id: string; turns: Turn[]; files: SessionFile[]; draft: string;
  uploadNotice: string; error: ApiError | null; retry: Retry | null;
  running: boolean;
  preparing?: boolean;
  restorePending?: boolean;
};
export const CONVERSATION_LIMIT = 10;
export function makeId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
function emptyConversation(): Conversation {
  return { id: makeId(), turns: [], files: [], draft: "", uploadNotice: "", error: null, retry: null, running: false };
}
function hasContent(conversation: Conversation) {
  return conversation.running || conversation.preparing || conversation.turns.length > 0
    || conversation.files.length > 0 || conversation.draft.trim().length > 0;
}
export function conversationTitle(conversation: Conversation) {
  return conversation.turns.find((turn) => turn.role === "user")?.content
    || conversation.draft.trim() || conversation.files[0]?.filename || "新对话";
}
function release(conversation: Conversation, keepalive = false) {
  // Detached executions still own these files after the page disconnects.
  // Abandoned files retain the existing bounded server lease.
  if (conversation.running || conversation.preparing) return;
  void releaseSessionFiles(conversation.files.flatMap((file) => file.receipt ? [file.receipt.file_id] : []), conversation.id, keepalive);
}

const cacheKey = (scope: string) => `nitrogen_pending_runs_v1:${scope}`;
function readPending(scope: string): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const stored = JSON.parse(sessionStorage.getItem(cacheKey(scope)) || "null");
    if (!stored || stored.version !== 1 || Date.now() - stored.savedAt > 86400_000 || !Array.isArray(stored.conversations)) return [];
    return stored.conversations.filter((item: Conversation) => item && typeof item.id === "string" && item.running && item.retry
      && typeof item.retry.query === "string" && typeof item.retry.turnId === "string" && typeof item.retry.requestId === "string"
      && Array.isArray(item.retry.attachments) && Array.isArray(item.retry.history) && Array.isArray(item.turns) && Array.isArray(item.files))
      .slice(0, CONVERSATION_LIMIT).map((item: Conversation) => ({ ...item, preparing: false, error: null, restorePending: true }));
  } catch { return []; }
}
function savePending(scope: string, conversations: Conversation[]) {
  try {
    const pending = conversations.filter((item) => item.running && item.retry).map((item) => ({ ...item, turns: item.turns.slice(-12), error: null }));
    if (!pending.length) { sessionStorage.removeItem(cacheKey(scope)); return; }
    const encoded = JSON.stringify({ version: 1, savedAt: Date.now(), conversations: pending });
    if (encoded.length <= 1_000_000) sessionStorage.setItem(cacheKey(scope), encoded);
  } catch { /* Storage-disabled browsers retain ordinary in-memory recovery. */ }
}
export function retainPendingRun(scope: string, conversation: Conversation, retry: Retry, turns: Turn[]) {
  savePending(scope, [{ ...conversation, retry, turns, running: true }, ...readPending(scope).filter((item) => item.id !== conversation.id)]);
}

function restoreConversation(saved: SavedConversation): Conversation {
  const turns: Turn[] = [];
  let retry: Retry | null = null;
  let error: ApiError | null = null;
  let running = false;
  for (const item of saved.turns) {
    const answerId = `answer_${item.turn_id}`;
    const request: Retry = { ...item.request, rerunOfRunId: item.request.rerunOfRunId ?? undefined,
      recoveryExpired: !item.recoverable };
    turns.push({ id: item.turn_id, role: "user", content: request.query,
      filename: request.attachments.map((file) => file.filename).join("、") || undefined });
    if (item.response) turns.push({ id: answerId, role: "assistant", content: item.response.answer,
      response: item.response, request: item.recoverable && !["accepted", "running"].includes(item.status)
        ? { ...request, requestId: makeId(), rerunOfRunId: item.run_id } : request });
    if (item === saved.turns.at(-1)) {
      running = item.recoverable && ["accepted", "running"].includes(item.status);
      if (running) retry = { ...request, ...(item.response ? { answerId } : {}) };
      if (item.error) {
        error = new ApiError(item.error.code, item.error.http_status, item.error.message);
        if (item.recoverable) retry = { ...request, requestId: makeId(), rerunOfRunId: item.run_id,
          ...(item.response ? { answerId } : {}) };
      }
    }
  }
  return { id: saved.id, turns, files: [], draft: "", uploadNotice: "", error, retry, running,
    restorePending: running };
}

export function useConversations(scope = "visitor") {
  const account = scope !== "visitor";
  // Newest conversations stay first; selecting a conversation does not reorder them.
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const pending = readPending(scope);
    return pending.length ? pending : [emptyConversation()];
  });
  const [activeId, setActiveId] = useState(conversations[0].id);
  const conversation = conversations.find((item) => item.id === activeId) ?? conversations[0];
  const [notice, setNotice] = useState("");
  const [historyReady, setHistoryReady] = useState(!account);
  const [historyError, setHistoryError] = useState("");
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const retained = useRef(conversations);
  useEffect(() => {
    if (!account) return;
    let disposed = false;
    const controller = new AbortController();
    async function restore() {
      try {
        const page = await getAccountChatHistory(0, controller.signal);
        if (disposed) return;
        const saved = page.items.map(restoreConversation);
        setConversations((old) => {
          // Local pending requests may have lost their first admission receipt.
          // A completed server record wins over an outdated pending browser copy.
          const pending = old.filter((item) => item.running && item.retry && !page.items.some((value) =>
            value.id === item.id && value.turns.some((turn) => turn.request.requestId === item.retry!.requestId
              && !["accepted", "running"].includes(turn.status))));
          const ids = new Set(pending.map((item) => item.id));
          const merged = [...pending, ...saved.filter((item) => !ids.has(item.id))];
          return merged.length ? merged : old;
        });
        setActiveId((old) => retained.current.some((item) => item.id === old && item.running) ? old : saved[0]?.id ?? old);
        setHistoryOffset(page.items.length);
        setHistoryTotal(page.total);
        setHistoryError("");
        setHistoryReady(true);
      } catch {
        if (!disposed) setHistoryError("历史会话暂时无法加载，请重试。");
      }
    }
    void restore();
    return () => { disposed = true; controller.abort(); };
  }, [account, scope, historyAttempt]);

  async function loadMoreHistory() {
    if (loadingMore || historyOffset >= historyTotal) return;
    setLoadingMore(true);
    try {
      const page = await getAccountChatHistory(historyOffset);
      setConversations((old) => {
        const ids = new Set(old.map((item) => item.id));
        return [...old, ...page.items.filter((item) => !ids.has(item.id)).map(restoreConversation)];
      });
      setHistoryOffset((old) => old + page.items.length);
      setHistoryTotal(page.total);
    } catch { setNotice("更早的会话暂时无法加载，请重试。"); }
    finally { setLoadingMore(false); }
  }
  useEffect(() => {
    const ids = new Set(conversations.map((conversation) => conversation.id));
    retained.current.filter((conversation) => !ids.has(conversation.id)).forEach((conversation) => release(conversation));
    retained.current = conversations;
    savePending(scope, conversations);
  }, [conversations, scope]);

  useEffect(() => {
    let disposed = false;
    let refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        await Promise.all(retained.current.map(async (conversation) => {
          const known = conversation.files.filter((file) => file.receipt && file.phase === "stored");
          if (!known.length) return;
          try {
            const status = await checkSessionFiles(known.map((file) => file.receipt!.file_id), conversation.id);
            const expired = new Set(status.files.filter((file) => file.status === "expired").map((file) => file.file_id));
            if (disposed || !expired.size) return;
            // A check may finish after switching conversations. Update only its owner.
            setConversations((old) => old.map((item) => item.id !== conversation.id ? item : {
              ...item,
              files: item.files.filter((file) => !file.receipt || !expired.has(file.receipt.file_id)),
              // File expiry prevents a new execution, but a submitted run can
              // still be recovered without reopening its original attachments.
              retry: !item.running && item.retry?.attachments.some((file) => expired.has(file.file_id)) ? null : item.retry,
              uploadNotice: "部分会话文件已失效，请重新上传。",
            }));
          } catch { /* Temporary failures must not discard retained files. */ }
        }));
      } finally { refreshing = false; }
    };
    const onVisible = () => { if (document.visibilityState === "visible") void refresh(); };
    const onPageHide = () => retained.current.forEach((conversation) => release(conversation, true));
    const timer = window.setInterval(() => void refresh(), 5 * 60 * 1000);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pagehide", onPageHide);
      onPageHide();
    };
  }, []);

  function update<K extends keyof Omit<Conversation, "id">>(id: string, key: K, value: SetStateAction<Conversation[K]>) {
    setConversations((old) => old.map((item) => item.id !== id ? item : {
      ...item, [key]: typeof value === "function" ? value(item[key]) : value,
    }));
  }
  function create() {
    if (!hasContent(conversation)) {
      setConversations((old) => old.map((item) => item.id === conversation.id
        ? { ...item, draft: "", error: null, retry: null, uploadNotice: "" } : item));
      return;
    }
    const next = emptyConversation();
    const full = !account && conversations.length >= CONVERSATION_LIMIT;
    const removable = [...conversations].reverse().find((item) => !item.running && !item.preparing);
    if (full && !removable) {
      setNotice(`已达到 ${CONVERSATION_LIMIT} 个对话，请先找回未确认运行的结果再新建对话。`);
      return;
    }
    setNotice(full ? `已达到 ${CONVERSATION_LIMIT} 个对话，最早创建且没有待确认运行的对话已移除。` : "");
    setConversations((old) => {
      if (account) return [next, ...old];
      // Apply the limit to the latest state, including batched create clicks.
      let remaining = CONVERSATION_LIMIT - old.filter((item) => item.running || item.preparing).length;
      return [next, ...old].filter((item) => item.running || item.preparing || remaining-- > 0);
    });
    setActiveId(next.id);
  }
  function select(id: string) {
    if (!conversations.some((item) => item.id === id)) return;
    setActiveId(id);
    setConversations((old) => old.filter((item) => item.id === id || hasContent(item)));
    setNotice("");
  }
  return { conversation, conversations, notice, update, create, select, historyReady, historyError,
    retryHistory: () => setHistoryAttempt((old) => old + 1), loadingMore,
    hasMoreHistory: account && historyOffset < historyTotal, loadMoreHistory };
}
