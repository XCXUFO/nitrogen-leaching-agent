"use client";

import { useState } from "react";

import { ChatError } from "@/components/chat/chat-error";
import { ChatForm } from "@/components/chat/chat-form";
import { ChatMessage } from "@/components/chat/chat-message";
import { CitationList } from "@/components/chat/citation-list";
import { HealthProbe } from "@/components/debug/health-probe";
import { ApiError, apiBaseUrl, postChat } from "@/lib/api";
import { UNKNOWN_FAILURE } from "@/lib/error-messages";
import type { ChatResponse } from "@/lib/types";

type AssistantTurn =
  | { kind: "loading"; slow: boolean }
  | { kind: "ok"; response: ChatResponse }
  | { kind: "error"; error: ApiError };

export default function Home() {
  const [userQuery, setUserQuery] = useState<string | null>(null);
  const [assistant, setAssistant] = useState<AssistantTurn | null>(null);

  async function handleSubmit(query: string) {
    setUserQuery(query);
    setAssistant({ kind: "loading", slow: false });

    const slowTimer = window.setTimeout(() => {
      setAssistant((prev) =>
        prev?.kind === "loading" ? { kind: "loading", slow: true } : prev,
      );
    }, 3000);

    try {
      const response = await postChat(query);
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

  const isLoading = assistant?.kind === "loading";

  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col gap-6 px-6 py-10">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          氮淋失风险决策 Agent
        </h1>
        <p className="text-muted-foreground text-xs">
          单轮问答 · 基于本地论文知识库 · 回答带引用
        </p>
      </header>

      <ChatForm onSubmit={handleSubmit} disabled={isLoading} />

      <section className="flex flex-col gap-3">
        {userQuery && <ChatMessage role="user" content={userQuery} />}

        {assistant?.kind === "loading" && (
          <ChatMessage
            role="assistant"
            content="正在思考…"
            pending
            slowHint={assistant.slow}
          />
        )}

        {assistant?.kind === "ok" && (
          <>
            <ChatMessage
              role="assistant"
              content={assistant.response.answer}
            />
            <CitationList
              citations={assistant.response.citations}
              retrievedCount={assistant.response.retrieved_count}
            />
          </>
        )}

        {assistant?.kind === "error" && <ChatError error={assistant.error} />}
      </section>

      <details className="text-muted-foreground mt-auto pt-8 text-xs">
        <summary className="cursor-pointer">调试 / Backend health</summary>
        <div className="mt-2 space-y-2">
          <p>
            API base: <code>{apiBaseUrl}</code>
          </p>
          <HealthProbe />
        </div>
      </details>
    </main>
  );
}
