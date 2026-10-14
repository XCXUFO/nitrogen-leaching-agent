"use client";

import Link from "next/link";
import { useState } from "react";
import { accountRoleLabels, useAccountSession } from "./account-session";

export function AccountNavigation() {
  const { session, ready, logout, error } = useAccountSession();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  if (!ready) return <span className="text-xs text-slate-500">正在验证身份…</span>;
  if (!session) return <div className="flex flex-wrap items-center gap-2 text-xs">
    <Link href="/evaluation?returnTo=%2F" className="text-emerald-800 hover:underline">内部人员登录</Link>
    {error && <span role="status" className="text-slate-500">{error}</span>}
  </div>;
  async function leave() {
    setBusy(true); setProblem("");
    try { await logout(); } catch { setProblem("退出失败，请重试。"); }
    finally { setBusy(false); }
  }
  return <div className="flex flex-wrap items-center gap-2 text-xs" aria-label="内部人员身份">
    <span>{session.username}</span><span className="rounded-full bg-emerald-50 px-2 py-1 text-emerald-800">{accountRoleLabels[session.user.role]}</span>
    <Link href="/evaluation" className="text-emerald-800 hover:underline">管理工作台</Link>
    <button disabled={busy} onClick={leave} className="text-slate-500 hover:underline disabled:opacity-50">退出登录</button>
    {problem && <span role="alert" className="text-destructive">{problem}</span>}
  </div>;
}
