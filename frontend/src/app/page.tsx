"use client";

import { useState } from "react";

import { ChatError } from "@/components/chat/chat-error";
import { ChatForm } from "@/components/chat/chat-form";
import { ChatMessage } from "@/components/chat/chat-message";
import { CitationList } from "@/components/chat/citation-list";
import { HealthProbe } from "@/components/debug/health-probe";
import { ApiError, apiBaseUrl, postChat } from "@/lib/api";
import { UNKNOWN_FAILURE } from "@/lib/error-messages";
import type { ChatHistoryMessage, ChatResponse } from "@/lib/types";

type AssistantTurn =
  | { kind: "loading"; slow: boolean }
  | { kind: "ok"; response: ChatResponse }
  | { kind: "error"; error: ApiError };

type ConversationTurn =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; content: string; response: ChatResponse };

export default function Home() {
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [lastQuery, setLastQuery] = useState<string | null>(null);
  const [assistant, setAssistant] = useState<AssistantTurn | null>(null);
  const [sessionId] = useState(() => makeId());

  async function handleSubmit(query: string) {
    const history = toHistory(turns);
    setLastQuery(query);
    setTurns((prev) => [
      ...prev,
      { id: makeId(), role: "user", content: query },
    ]);
    setAssistant({ kind: "loading", slow: false });

    const slowTimer = window.setTimeout(() => {
      setAssistant((prev) =>
        prev?.kind === "loading" ? { kind: "loading", slow: true } : prev,
      );
    }, 3000);

    try {
      const response = await postChat(query, history, undefined, undefined, sessionId);
      setTurns((prev) => [
        ...prev,
        {
          id: makeId(),
          role: "assistant",
          content: response.answer,
          response,
        },
      ]);
      setAssistant({ kind: "ok", response });
    } catch (err) {
      const error =
        err instanceof ApiError
          ? err
          : new ApiError("unknown", null, UNKNOWN_FAILURE, err);
      setAssistant({ kind: "error", error });
    } finally {
      window.clearTimeout(slowTimer);
    }
  }

  function clearConversation() {
    if (assistant?.kind === "loading") return;
    setTurns([]);
    setLastQuery(null);
    setAssistant(null);
  }

  const isLoading = assistant?.kind === "loading";

  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col gap-6 px-6 py-10">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            氮淋失风险决策 Agent
          </h1>
          <p className="text-muted-foreground text-xs">
            多轮问答 · 基于本地论文知识库 · 回答带引用
          </p>
        </div>
        {turns.length > 0 && (
          <button
            type="button"
            className="border-input text-muted-foreground hover:bg-muted rounded-md border px-3 py-1.5 text-xs transition disabled:opacity-50"
            onClick={clearConversation}
            disabled={isLoading}
          >
            清空
          </button>
        )}
      </header>

      <ChatForm onSubmit={handleSubmit} disabled={isLoading} />

      <section className="flex flex-col gap-3">
        {turns.map((turn) => {
          if (turn.role === "user") {
            return (
              <ChatMessage key={turn.id} role="user" content={turn.content} />
            );
          }
          return (
            <div key={turn.id} className="space-y-2">
              <ChatMessage role="assistant" content={turn.content} />
              <CitationList
                citations={turn.response.citations}
                retrievedCount={turn.response.retrieved_count}
              />
            </div>
          );
        })}

        {assistant?.kind === "loading" && (
          <ChatMessage
            role="assistant"
            content="正在思考…"
            pending
            slowHint={assistant.slow}
          />
        )}

        {assistant?.kind === "error" && (
          <ChatError
            error={assistant.error}
            onRetry={
              lastQuery ? () => handleSubmit(lastQuery) : undefined
            }
          />
        )}
      </section>

      <details className="text-muted-foreground mt-auto pt-8 text-xs">
        <summary className="cursor-pointer">调试 / Backend health</summary>
        <div className="mt-2 space-y-2">
          <p>
            API base: <code>{apiBaseUrl}</code>
          </p>
          <p>
            Session: <code>{sessionId}</code>
          </p>
          <HealthProbe />
        </div>
      </details>
    </main>
  );
}

function toHistory(turns: ConversationTurn[]): ChatHistoryMessage[] {
  return turns
    .slice(-12)
    .map((turn) => ({ role: turn.role, content: turn.content }));
}

function makeId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
