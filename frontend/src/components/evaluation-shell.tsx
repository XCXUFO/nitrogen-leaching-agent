"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type Dispatch, type SetStateAction, type FormEvent, type ReactNode } from "react";
import { Activity, ArrowLeft, BookOpen, ChevronLeft, ChevronRight, ClipboardList, FlaskConical, LayoutDashboard, ListChecks, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Puzzle, RotateCcw, ShieldCheck, Tags, TriangleAlert, X } from "lucide-react";
import { type Evaluator } from "@/lib/evaluation-api";
import { canViewModule, evaluationHref, evaluationModules, primaryEvaluationModules, extraEvaluationModules } from "@/lib/evaluation-navigation";

import { accountRoleLabels, useAccountSession } from "./account-session";

const Session = createContext<{ token: string; user: Evaluator } | null>(null);
type TaskReturn = { pathname: string; taskId: string } | null;
const ReturnTask = createContext<Dispatch<SetStateAction<TaskReturn>> | null>(null);
export function useEvaluationReturnTask(taskId: string | null) {
  const setReturnTask = useContext(ReturnTask);
  const pathname = usePathname();
  useEffect(() => {
    setReturnTask?.(taskId ? { pathname, taskId } : null);
    return () => setReturnTask?.(null);
  }, [pathname, taskId, setReturnTask]);
}
export function useEvaluationSession() {
  const session = useContext(Session);
  if (!session) throw new Error("Evaluation session required");
  return session;
}
const icons = [LayoutDashboard, Activity, BookOpen, BookOpen, BookOpen, Tags, ClipboardList, BookOpen, ListChecks, RotateCcw, ShieldCheck, TriangleAlert, Activity, Puzzle, FlaskConical];
const roles = accountRoleLabels;

export function EvaluationShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const account = useAccountSession();
  const { session, ready } = account;
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [returnTask, setReturnTask] = useState<TaskReturn>(null);
  const drawer = useRef<HTMLDialogElement>(null);
  const parts = pathname.split("/").filter(Boolean);
  const currentModule = evaluationModules.find((item) => item.key === (!parts[1] || parts[1] === "overview" ? "runs" : parts[1]));
  const title = currentModule?.title ?? "页面不存在";
  const detail = parts[2];
  const isIndex = !!currentModule && !detail;
  const taskId = currentModule?.key === "executions" && returnTask?.pathname === pathname ? returnTask.taskId : null;
  const backHref = taskId ? evaluationHref("tasks", taskId) : evaluationHref(currentModule?.key ?? "overview");
  const backLabel = taskId ? "返回所属任务" : `返回${title}`;

  useEffect(() => {
    if (session && new URLSearchParams(window.location.search).get("returnTo") === "/") router.replace("/");
  }, [session, router]);

  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await account.login(username.trim(), password); setPassword("");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "登录失败"); }
    finally { setBusy(false); }
  }

  async function logout() {
    if (!ready) return <main className="flex min-h-dvh items-center justify-center" role="status">正在恢复登录状态…</main>;

  if (!session) return;
    setBusy(true); setError("");
    try {
      await account.logout(); setPassword("");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "退出失败，请重试。"); }
    finally { setBusy(false); }
  }

  function navigation(compact = false) {
    function itemLink(item: typeof evaluationModules[number]) {
      const Icon = icons[evaluationModules.indexOf(item)];
      const active = currentModule?.key === item.key;
      return <Link key={item.key} href={evaluationHref(item.key)} aria-current={active ? "page" : undefined}
        title={compact ? item.title : undefined} onClick={() => drawer.current?.close()}
        className={`flex min-h-9 items-center gap-3 rounded-lg px-3 py-1.5 text-sm transition-colors ${active ? "bg-emerald-50 font-semibold text-emerald-800" : "text-slate-600 hover:bg-slate-100"}`}>
        <Icon size={18} aria-hidden="true" className="shrink-0" /><span className={compact ? "sr-only" : ""}>{item.title}</span>
      </Link>;
    }
    const allowed = (item: typeof evaluationModules[number]) => session && canViewModule(item.key, session.user.role);
    return <nav aria-label="工作台导航" className="space-y-4 px-3 py-3">
      {[["会话审核", ["runs"]], ["资料管理", ["literature", "case-library", "starred-questions"]], ["回答调整", ["explanation-trials"]]].map(([group, keys]) =>
        <div key={group as string}><p className={`mb-1 px-3 text-[11px] font-medium text-slate-400 ${compact ? "sr-only" : ""}`}>{group}</p>
          <div className="space-y-0.5">{primaryEvaluationModules.filter((item) => (keys as string[]).includes(item.key) && allowed(item)).map(itemLink)}</div></div>)}
      <details className="border-t pt-3" open={currentModule && extraEvaluationModules.some((item) => item.key === currentModule.key) ? true : undefined}>
        <summary title="更多工具与历史记录" className="cursor-pointer px-3 py-2 text-xs text-slate-500">{compact ? "更多" : "更多工具与历史记录"}</summary>
        <div className="mt-1 space-y-0.5">{extraEvaluationModules.filter(allowed).map(itemLink)}</div>
      </details>
    </nav>;
  }

  if (!ready) return <main className="flex min-h-dvh items-center justify-center" role="status">正在恢复登录状态…</main>;

  if (!session) return <main className="flex min-h-dvh items-center justify-center bg-slate-50 px-5 py-12">
    <div className="w-full max-w-md space-y-6">
      <Link href="/" className="inline-flex items-center gap-2 text-sm text-slate-500"><ArrowLeft size={16} />返回对话</Link>
      <Link href="/showcase" className="block rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">访客无需登录：查看只读工作台 →</Link>
      <form onSubmit={login} className="space-y-5 rounded-2xl border bg-white p-8 shadow-sm">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-700 text-white"><FlaskConical size={23} /></div>
        <div><h1 className="text-2xl font-semibold">管理工作台</h1><p className="mt-2 text-sm text-muted-foreground">审核会话，整理资料，改进回答。</p></div>
        <label className="block space-y-2 text-sm font-medium"><span>账号</span>
          <input type="text" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={80} value={username} onChange={(e) => setUsername(e.target.value)} className="w-full rounded-lg border bg-background px-3 py-3" /></label>
        <label className="block space-y-2 text-sm font-medium"><span>密码</span>
          <input type="password" name="password" autoComplete="current-password" required maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} className="w-full rounded-lg border bg-background px-3 py-3" /></label>
        <p className="text-xs leading-5 text-muted-foreground">使用分配的账号和密码登录，你和协作者都可以整理资料、审核会话。暂不开放注册。</p>
        <p className="text-xs leading-5 text-muted-foreground">当前窗口内，前台与工作台共享登录状态，切换页面和刷新均无需重复登录。</p>
        {(error || account.error) && <p role="alert" className="text-sm text-destructive">{error || account.error}</p>}
        <button disabled={busy} className="w-full rounded-lg bg-emerald-700 px-4 py-3 text-sm font-medium text-white hover:bg-emerald-800 disabled:opacity-50">{busy ? "正在验证…" : "进入工作台"}</button>
      </form>
    </div>
  </main>;

  return <Session.Provider value={session}><ReturnTask.Provider value={setReturnTask}>
    <div className={`evaluation-workspace min-h-dvh bg-slate-50 ${collapsed ? "lg:pl-[76px]" : "lg:pl-[232px]"}`}>
      <aside className={`fixed inset-y-0 left-0 z-30 hidden flex-col border-r bg-white lg:flex ${collapsed ? "w-[76px]" : "w-[232px]"}`}>
        <Link href="/evaluation/overview" className="flex h-16 shrink-0 items-center gap-3 border-b px-6 text-emerald-800" title="管理工作台">
          <FlaskConical size={24} className="shrink-0" /><span className={collapsed ? "sr-only" : "font-semibold"}>管理工作台</span>
        </Link>
        <div className="flex-1 overflow-y-auto">{navigation(collapsed)}</div>
        <button className="m-3 flex items-center justify-center gap-2 rounded-lg border p-2.5 text-xs text-slate-500 hover:bg-slate-50" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}>
          {collapsed ? <PanelLeftOpen size={18} /> : <><PanelLeftClose size={18} />收起导航</>}
        </button>
      </aside>
      <dialog ref={drawer} className="fixed inset-y-0 left-0 m-0 h-dvh max-h-none w-72 max-w-[85vw] border-r bg-white p-0 backdrop:bg-slate-950/40" aria-label="移动端导航">
        <div className="flex h-16 items-center justify-between border-b px-5"><span className="font-semibold">管理工作台</span><button aria-label="关闭导航" onClick={() => drawer.current?.close()} className="p-2"><X size={20} /></button></div>
        {navigation()}
      </dialog>
      <header className="sticky top-0 z-20 flex min-h-16 flex-wrap items-center justify-between gap-3 border-b bg-white/95 px-4 py-3 backdrop-blur sm:px-7">
        <div className="flex min-w-0 items-center gap-3">
          <button aria-label="打开导航" className="rounded border p-2 lg:hidden" onClick={() => drawer.current?.showModal()}><Menu size={18} /></button>
          <nav aria-label="面包屑" className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-slate-500">
            <Link href="/evaluation/overview">工作台</Link><ChevronRight size={13} />
            {detail ? <><Link href={evaluationHref(currentModule?.key ?? "overview")}>{title}</Link><ChevronRight size={13} /><span className="text-slate-900">{detail === "new" ? "新建" : detail === "drafts" ? "草稿管理" : "详情"}</span></> : <span className="text-slate-900">{title}</span>}
          </nav>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
          <Link href="/" className="hover:text-emerald-700">返回对话</Link>
          <span className="max-w-40 truncate">{session.username}</span><span className="rounded-full bg-slate-100 px-2 py-1">{roles[session.user.role]}</span>
          <button disabled={busy} className="rounded p-1.5 hover:bg-slate-100 disabled:opacity-50" aria-label="退出登录" onClick={logout}><LogOut size={16} /></button>
        </div>
      </header>
      <main id="evaluation-content" className={`min-w-0 ${isIndex ? "space-y-3 p-3 sm:p-4" : "space-y-5 p-4 sm:p-7"}`}>
        {(error || account.error) && <p role="alert" className="text-sm text-destructive">{error || account.error}</p>}
        <div className="flex items-start gap-3">
          {detail && <Link onClick={currentModule?.key === "runs" ? (event) => { event.preventDefault(); router.push(`${backHref}${window.location.search}`); } : undefined} aria-label={backLabel} title={backLabel} href={backHref} className="mt-0.5 rounded-lg border bg-white p-2"><ChevronLeft size={18} /></Link>}
          <h1 className={`${isIndex ? "text-xl" : "text-2xl"} font-semibold tracking-tight text-slate-900`}>{title}{detail ? detail === "new" ? " · 新建" : detail === "drafts" ? " · 草稿" : " · 详情" : ""}</h1>
        </div>
        {children}
      </main>
    </div>
  </ReturnTask.Provider></Session.Provider>;
}
