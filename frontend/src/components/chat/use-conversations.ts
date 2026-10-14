"use client";

import { useEffect, useRef, useState, type SetStateAction } from "react";
import { ApiError, checkSessionFiles, releaseSessionFiles } from "@/lib/api";
import type { ChatHistoryMessage, ChatResponse, FileReceipt, SessionFile } from "@/lib/types";

export type Turn = { id: string; role: "user"; content: string; filename?: string }
  | { id: string; role: "assistant"; content: string; response: ChatResponse };
export type Retry = { query: string; attachments: FileReceipt[]; history: ChatHistoryMessage[] };
export type Conversation = {
  id: string; turns: Turn[]; files: SessionFile[]; draft: string;
  uploadNotice: string; error: ApiError | null; retry: Retry | null;
};
export const CONVERSATION_LIMIT = 10;
export function makeId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
function emptyConversation(): Conversation {
  return { id: makeId(), turns: [], files: [], draft: "", uploadNotice: "", error: null, retry: null };
}
function hasContent(conversation: Conversation) {
  return conversation.turns.length > 0 || conversation.files.length > 0 || conversation.draft.trim().length > 0;
}
export function conversationTitle(conversation: Conversation) {
  return conversation.turns.find((turn) => turn.role === "user")?.content
    || conversation.draft.trim() || conversation.files[0]?.filename || "新对话";
}
function release(conversation: Conversation, keepalive = false) {
  void releaseSessionFiles(conversation.files.flatMap((file) => file.receipt ? [file.receipt.file_id] : []), conversation.id, keepalive);
}

export function useConversations() {
  // Most recently opened conversation first; each conversation owns its context.
  const [conversations, setConversations] = useState<Conversation[]>(() => [emptyConversation()]);
  const [notice, setNotice] = useState("");
  const retained = useRef(conversations);
  useEffect(() => {
    const ids = new Set(conversations.map((conversation) => conversation.id));
    retained.current.filter((conversation) => !ids.has(conversation.id)).forEach((conversation) => release(conversation));
    retained.current = conversations;
  }, [conversations]);

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
              retry: item.retry?.attachments.some((file) => expired.has(file.file_id)) ? null : item.retry,
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
    if (!hasContent(conversations[0])) {
      setConversations((old) => [{ ...old[0], draft: "", error: null, retry: null, uploadNotice: "" }, ...old.slice(1)]);
      return;
    }
    const next = emptyConversation();
    setNotice(conversations.length >= CONVERSATION_LIMIT ? `已达到 ${CONVERSATION_LIMIT} 个对话，最早使用的对话已移除。` : "");
    setConversations((old) => [next, ...old].slice(0, CONVERSATION_LIMIT));
  }
  function select(id: string) {
    setConversations((old) => {
      const selected = old.find((item) => item.id === id);
      if (!selected || selected === old[0]) return old;
      return [selected, ...old.filter((item) => item.id !== id && hasContent(item))];
    });
    setNotice("");
  }
  return { conversation: conversations[0], conversations, notice, update, create, select };
}
