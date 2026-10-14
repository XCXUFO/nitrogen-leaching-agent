"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { evaluationJson, evaluationRequest, type Evaluator } from "@/lib/evaluation-api";
import { readAccount, storeAccount, type StoredAccount } from "@/lib/account-storage";

export const accountRoleLabels = { developer: "开发者", tester: "测试者", reviewer: "领域审核人" };
type Account = StoredAccount & { user: Evaluator };
const Context = createContext<{
  session: Account | null; ready: boolean; error: string;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>; refresh: () => Promise<void>;
} | null>(null);

export function AccountSessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const validating = useRef(false);
  const refresh = useCallback(async () => {
    if (validating.current) return;
    const stored = readAccount();
    if (!stored) { setSession(null); setReady(true); return; }
    validating.current = true;
    try {
      const user = await evaluationRequest<Evaluator>(stored.token, "/me");
      if (readAccount()?.token === stored.token) { setSession({ ...stored, user }); setError(""); }
    } catch (problem) {
      if (readAccount()?.token === stored.token) setError(problem instanceof Error ? problem.message : "暂时无法验证登录，请重试。");
    } finally { validating.current = false; setReady(true); }
  }, []);

  useEffect(() => {
    const expired = (event: Event) => {
      const token = (event as CustomEvent<{ token?: string }>).detail?.token;
      if (token && token !== readAccount()?.token) return;
      storeAccount(null); setSession(null); setError("登录已失效，请重新登录。"); setReady(true);
    };
    const visible = () => { if (document.visibilityState === "visible") void refresh(); };
    window.addEventListener("evaluation-session-expired", expired);
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    // Keep an open window's server session alive, including time spent on the front page.
    const timer = window.setInterval(() => void refresh(), 5 * 60 * 1000);
    const initial = window.setTimeout(() => void refresh(), 0);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer); window.removeEventListener("evaluation-session-expired", expired);
      window.removeEventListener("focus", visible); document.removeEventListener("visibilitychange", visible);
    };
  }, [refresh]);

  async function login(username: string, password: string) {
    const result = await evaluationRequest<{ token: string; user: Evaluator }>("", "/login", evaluationJson({ username, password }));
    const next = { token: result.token, username, user: result.user };
    storeAccount({ token: next.token, username }); setSession(next); setError(""); setReady(true);
  }
  async function logout() {
    const stored = readAccount();
    if (stored) await evaluationRequest(stored.token, "/logout", { method: "POST" });
    storeAccount(null); setSession(null); setError("");
  }
  if (ready && !session && error && readAccount()) return <main className="p-8"><p role="alert">{error}</p><button className="mt-4 underline" onClick={() => void refresh()}>重新验证登录</button></main>;
  return <Context.Provider value={{ session, ready, error, login, logout, refresh }}>{children}</Context.Provider>;
}
export function useAccountSession() {
  const state = useContext(Context);
  if (!state) throw new Error("AccountSessionProvider required");
  return state;
}
