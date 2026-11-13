"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type Dispatch, type SetStateAction, type FormEvent, type ReactNode } from "react";
import { Activity, ArrowLeft, BookOpen, ChevronLeft, ChevronRight, ClipboardList, Database, FlaskConical, FolderOpen, LayoutDashboard, ListChecks, LogOut, Menu, MessagesSquare, PanelLeftClose, PanelLeftOpen, Puzzle, RotateCcw, Settings2, ShieldCheck, Star, Tags, TriangleAlert, X } from "lucide-react";
import { type Evaluator } from "@/lib/evaluation-api";
import { canViewModule, conversationCaseSections, evaluationHref, evaluationModules, primaryEvaluationModules, extraEvaluationModules } from "@/lib/evaluation-navigation";

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
const icons = { overview: LayoutDashboard, "online-effects": Activity, literature: BookOpen, "case-library": Database,
  "starred-questions": Star, "literature-tags": Tags, tasks: ClipboardList, cases: FolderOpen, executions: ListChecks,
  regressions: RotateCcw, reviews: ShieldCheck, issues: TriangleAlert, runs: MessagesSquare, skills: Puzzle,
  "explanation-trials": Settings2, "case-groups": ClipboardList };
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
  const caseSection = currentModule?.key === "case-groups" ? conversationCaseSections.find((item) => item.key === (parts[2] === "versions" ? "versions" : "groups")) : undefined;
  const caseDetail = caseSection?.key === "groups" && (parts[2] === "cases" || parts[3] === "cases");
  const caseGroup = caseDetail && parts[3] === "cases" ? parts[2] : undefined;
  const title = caseDetail ? "会话用例" : caseSection?.title ?? currentModule?.title ?? "页面不存在";
  const detail = caseSection?.key === "versions" ? undefined : parts[2];
  const taskId = currentModule?.key === "executions" && returnTask?.pathname === pathname ? returnTask.taskId : null;
  const backHref = caseDetail ? evaluationHref("case-groups", caseGroup) : taskId ? evaluationHref("tasks", taskId) : evaluationHref(currentModule?.key ?? "overview");
  const backLabel = caseDetail ? caseGroup ? "返回所属用例组" : "返回用例组管理" : taskId ? "返回所属任务" : `返回${title}`;

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
    if (!ready || !session) return;
    setBusy(true); setError("");
    try {
      await account.logout(); setPassword("");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "退出失败，请重试。"); }
    finally { setBusy(false); }
  }

  function navigation(compact = false) {
    function itemLink(item: typeof evaluationModules[number]) {
      const Icon = icons[item.key];
      const active = currentModule?.key === item.key;
      if (item.key === "case-groups") return <div key={item.key}>
        <Link href={evaluationHref(item.key)} title={compact ? item.title : undefined} onClick={() => drawer.current?.close()}
          className={`wb-nav-item ${compact ? "wb-nav-item-compact" : ""}`}>
          <Icon size={18} aria-hidden="true" className="shrink-0" /><span className={compact ? "sr-only" : ""}>{item.title}</span>
        </Link>
        <div className={`wb-nav-children ${compact ? "wb-nav-children-compact" : ""}`}>
          {conversationCaseSections.map((section) => {
            const SectionIcon = section.key === "groups" ? FolderOpen : RotateCcw;
            return <Link key={section.key} href={section.href} aria-current={active && caseSection?.key === section.key ? "page" : undefined}
              title={compact ? section.title : undefined} onClick={() => drawer.current?.close()}
              className={`wb-nav-item ${compact ? "wb-nav-item-compact" : ""}`}>
              <SectionIcon size={16} aria-hidden="true" className="shrink-0" /><span className={compact ? "sr-only" : ""}>{section.title}</span>
            </Link>;
          })}
        </div>
      </div>;
      return <Link key={item.key} href={evaluationHref(item.key)} aria-current={active ? "page" : undefined}
        title={compact ? item.title : undefined} onClick={() => drawer.current?.close()}
        className={`wb-nav-item ${compact ? "wb-nav-item-compact" : ""}`}>
        <Icon size={18} aria-hidden="true" className="shrink-0" /><span className={compact ? "sr-only" : ""}>{item.title}</span>
      </Link>;
    }
    const allowed = (item: typeof evaluationModules[number]) => session && canViewModule(item.key, session.user.role);
    return <nav aria-label="工作台导航" className="wb-navigation">
      {[["会话评测", ["runs", "case-groups", "issues"]], ["资料管理", ["literature", "case-library", "starred-questions", "literature-tags"]], ["回答调整", ["explanation-trials"]]].map(([group, keys]) =>
        <div key={group as string}><p className={`wb-nav-group ${compact ? "sr-only" : ""}`}>{group}</p>
          <div className="space-y-0.5">{(keys as string[]).flatMap((key) => primaryEvaluationModules.filter((item) => item.key === key && allowed(item))).map(itemLink)}</div></div>)}
      <details className="wb-nav-more" open={currentModule && extraEvaluationModules.some((item) => item.key === currentModule.key) ? true : undefined}>
        <summary title="更多工具与历史记录">{compact ? "更多" : "更多工具与历史记录"}</summary>
        <div className="mt-1 space-y-0.5">{extraEvaluationModules.filter(allowed).map(itemLink)}</div>
      </details>
      <Link href="/" className="wb-nav-item lg:hidden" onClick={() => drawer.current?.close()}><ArrowLeft size={18} aria-hidden="true" />返回对话</Link>
    </nav>;
  }

  if (!ready) return <main className="evaluation-workspace wb-login" role="status">正在恢复登录状态…</main>;

  if (!session) return <main className="evaluation-workspace wb-login">
    <div className="w-full max-w-md space-y-5">
      <Link href="/" className="inline-flex items-center gap-2 text-sm text-slate-500"><ArrowLeft size={16} />返回对话</Link>
      <form onSubmit={login} className="wb-panel space-y-5 p-8">
        <div className="wb-brand-icon"><FlaskConical size={21} aria-hidden="true" /></div>
        <h1 className="text-2xl font-semibold">管理工作台</h1>
        <label className="block space-y-2 text-sm font-medium"><span>账号</span>
          <input type="text" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={80} value={username} onChange={(e) => setUsername(e.target.value)} className="wb-field" /></label>
        <label className="block space-y-2 text-sm font-medium"><span>密码</span>
          <input type="password" name="password" autoComplete="current-password" required maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} className="wb-field" /></label>
        <p className="text-xs leading-5 text-muted-foreground">开发者可管理配置并确认版本；专家可开展日常运行评测；普通账号在工作台仅可查看。暂不开放注册。</p>
        <p className="text-xs leading-5 text-muted-foreground">当前窗口内，前台与工作台共享登录状态，切换页面和刷新均无需重复登录。</p>
        {(error || account.error) && <p role="alert" className="text-sm text-destructive">{error || account.error}</p>}
        <button disabled={busy} className="wb-button wb-button-primary w-full">{busy ? "正在验证…" : "进入工作台"}</button>
      </form>
      <Link href="/showcase" className="block text-center text-sm text-emerald-800 hover:underline">访客无需登录，查看只读工作台</Link>
    </div>
  </main>;

  return <Session.Provider value={session}><ReturnTask.Provider value={setReturnTask}>
    <div className="evaluation-workspace wb-shell" data-navigation={collapsed ? "collapsed" : "expanded"}>
      <a href="#evaluation-content" className="wb-skip-link">跳转到主要内容</a>
      <aside className="wb-sidebar">
        <Link href="/evaluation/overview" className="wb-brand" title="管理工作台">
          <span className="wb-brand-icon"><FlaskConical size={20} aria-hidden="true" /></span><span className={collapsed ? "sr-only" : "font-semibold"}>管理工作台</span>
        </Link>
        <div className="flex-1 overflow-y-auto">{navigation(collapsed)}</div>
        <button className="wb-sidebar-toggle" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}>
          {collapsed ? <PanelLeftOpen size={18} /> : <><PanelLeftClose size={18} />收起导航</>}
        </button>
      </aside>
      <dialog ref={drawer} className="wb-drawer" aria-label="移动端导航">
        <div className="flex h-16 items-center justify-between border-b px-5"><span className="font-semibold">管理工作台</span><button aria-label="关闭导航" onClick={() => drawer.current?.close()} className="wb-icon-button"><X size={20} aria-hidden="true" /></button></div>
        {navigation()}
      </dialog>
      <header className="wb-topbar">
        <div className="flex min-w-0 items-center gap-3">
          <button aria-label="打开导航" className="wb-icon-button lg:hidden" onClick={() => drawer.current?.showModal()}><Menu size={18} aria-hidden="true" /></button>
          <nav aria-label="面包屑" className="wb-breadcrumb">
            <Link href="/evaluation/overview">工作台</Link><ChevronRight size={13} aria-hidden="true" />
            {caseSection && <><Link href={evaluationHref("case-groups")}>会话用例组</Link><ChevronRight size={13} aria-hidden="true" /></>}
            {caseDetail ? <><Link href={evaluationHref("case-groups")}>用例组管理</Link><ChevronRight size={13} aria-hidden="true" />{caseGroup && <><Link href={evaluationHref("case-groups", caseGroup)}>用例组详情</Link><ChevronRight size={13} aria-hidden="true" /></>}<span aria-current="page">会话用例详情</span></> : detail ? <><Link href={evaluationHref(currentModule?.key ?? "overview")}>{title}</Link><ChevronRight size={13} aria-hidden="true" /><span aria-current="page">{detail === "new" ? "新建" : detail === "drafts" ? "草稿管理" : "详情"}</span></> : <span aria-current="page">{title}</span>}
          </nav>
        </div>
        <div className="wb-account">
          <Link href="/" className="wb-return-link"><ArrowLeft size={14} aria-hidden="true" />返回对话</Link>
          <span className="wb-account-name" title={session.username}>{session.username}</span><span className="wb-role">{roles[session.user.role]}</span>
          <button disabled={busy} className="wb-icon-button" aria-label="退出登录" onClick={logout}><LogOut size={16} aria-hidden="true" /></button>
        </div>
      </header>
      <main id="evaluation-content" tabIndex={-1} className="wb-content">
        {(error || account.error) && <p role="alert" className="text-sm text-destructive">{error || account.error}</p>}
        <div className="wb-page-heading">
          {detail && <Link onClick={currentModule?.key === "runs" ? (event) => { event.preventDefault(); router.push(`${backHref}${window.location.search}`); } : undefined} aria-label={backLabel} title={backLabel} href={backHref} className="wb-button wb-back-button"><ChevronLeft size={18} aria-hidden="true" /></Link>}
          <h1>{title}{detail ? detail === "new" ? " · 新建" : detail === "drafts" ? " · 草稿" : " · 详情" : ""}</h1>
        </div>
        {children}
      </main>
    </div>
  </ReturnTask.Provider></Session.Provider>;
}
