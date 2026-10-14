"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Leaf, PanelLeftClose, PanelLeftOpen, SquarePen } from "lucide-react";
import { AccountNavigation } from "@/components/account-navigation";
import { conversationTitle, type Conversation } from "./use-conversations";

interface Props {
  conversations: Conversation[];
  activeId: string;
  disabled: boolean;
  onCreate: () => void;
  onSelect: (id: string) => void;
  children: ReactNode;
}

export function ChatShell({ conversations, activeId, disabled, onCreate, onSelect, children }: Props) {
  const [expanded, setExpanded] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const drawer = useRef<HTMLDialogElement>(null);
  const desktopToggle = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 768px)");
    const closeOnDesktop = () => { if (media.matches) drawer.current?.close(); };
    media.addEventListener("change", closeOnDesktop);
    return () => media.removeEventListener("change", closeOnDesktop);
  }, []);

  function create() { onCreate(); drawer.current?.close(); }
  function sidebar(mobile: boolean) {
    return <>
      <div className="flex h-16 shrink-0 items-center justify-between px-4">
        <span className="flex items-center gap-2 text-sm font-medium"><Leaf aria-hidden="true" className="size-5 text-emerald-800" />农业模型助手</span>
        <button type="button" aria-label="收起侧边栏" title="收起侧边栏"
          onClick={() => {
            if (mobile) drawer.current?.close();
            else { setExpanded(false); requestAnimationFrame(() => desktopToggle.current?.focus()); }
          }} className="rounded-lg p-2 text-muted-foreground hover:bg-slate-200/60 focus-visible:ring-2 focus-visible:ring-emerald-700">
          <PanelLeftClose aria-hidden="true" className="size-5" />
        </button>
      </div>
      <div className="px-3 pb-6 pt-2">
        <button type="button" disabled={disabled} onClick={create}
          className="flex w-full items-center gap-3 rounded-xl border border-emerald-900/10 bg-background px-3 py-3 text-sm font-medium text-emerald-900 shadow-xs hover:bg-emerald-50 disabled:opacity-40">
          <SquarePen aria-hidden="true" className="size-4" />新对话
        </button>
      </div>
      <h2 className="px-6 pb-2 text-xs text-muted-foreground">最近对话</h2>
      <nav aria-label="对话列表" className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-4">{conversations.map((item) => {
        const title = conversationTitle(item);
        return <button key={item.id} type="button" title={title} aria-label={`切换对话：${title}`}
          aria-current={item.id === activeId ? "true" : undefined} disabled={disabled}
          onClick={() => { onSelect(item.id); drawer.current?.close(); }}
          className={`block w-full truncate rounded-lg px-3 py-2.5 text-left text-sm transition-colors disabled:opacity-40 ${item.id === activeId ? "bg-emerald-900/8 font-medium text-emerald-950" : "text-slate-600 hover:bg-slate-200/60"}`}>
          {title.replace(/\s+/g, " ")}
        </button>;
      })}</nav>
    </>;
  }

  return <main className="flex h-dvh min-h-0 overflow-hidden bg-slate-50/70">
    <aside id="desktop-conversations" aria-label="历史对话" className={`${expanded ? "hidden md:flex" : "hidden"} w-64 shrink-0 flex-col border-r bg-slate-100/80`}>
      {sidebar(false)}
    </aside>
    <dialog ref={drawer} id="mobile-conversations" aria-label="历史对话" onClose={() => setMobileOpen(false)}
      onClick={(event) => { if (event.target === event.currentTarget) drawer.current?.close(); }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"));
        const first = buttons[0], last = buttons.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }}
      className="fixed inset-0 m-0 h-dvh max-h-none w-full max-w-none bg-transparent p-0 backdrop:bg-slate-950/30">
      <div className="flex h-full w-72 max-w-[85vw] flex-col border-r bg-slate-50 shadow-xl">{sidebar(true)}</div>
    </dialog>
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex min-h-16 shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b bg-background px-3 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2">
          <button type="button" aria-label="打开侧边栏" title="打开侧边栏" aria-controls="mobile-conversations" aria-expanded={mobileOpen}
            onClick={() => { drawer.current?.showModal(); setMobileOpen(true); }} className="rounded-lg p-2 text-muted-foreground hover:bg-muted md:hidden">
            <PanelLeftOpen aria-hidden="true" className="size-5" />
          </button>
          <button ref={desktopToggle} type="button" aria-label="打开侧边栏" title="打开侧边栏" aria-controls="desktop-conversations" aria-expanded={expanded}
            onClick={() => setExpanded(true)} className={`${expanded ? "hidden" : "hidden md:block"} rounded-lg p-2 text-muted-foreground hover:bg-muted`}>
            <PanelLeftOpen aria-hidden="true" className="size-5" />
          </button>
          <h1 className="text-sm font-semibold sm:text-base">农业模型助手</h1>
          <button type="button" aria-label="新对话" title="新对话" disabled={disabled} onClick={create}
            className={`${expanded ? "md:hidden" : ""} rounded-lg p-2 text-muted-foreground hover:bg-muted disabled:opacity-40`}>
            <SquarePen aria-hidden="true" className="size-5" />
          </button>
        </div>
        <nav className="flex flex-wrap items-center gap-3 text-xs"><AccountNavigation /><Link href="/showcase" className="text-muted-foreground hover:underline">查看评测后台</Link></nav>
      </header>
      {children}
    </div>
  </main>;
}
