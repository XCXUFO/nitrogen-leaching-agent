"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useShowcaseLiterature } from "./showcase-literature-provider";

export const demoButton = "inline-flex items-center justify-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40";
export const demoPrimary = "inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-800 px-3 py-2 text-sm text-white hover:bg-emerald-900 disabled:opacity-40";
export const demoInput = "mt-2 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm";
export const demoCard = "rounded-xl border bg-white p-4 sm:p-5";

export function ShowcaseExperienceNotice({ href }: { href: string }) {
  const { reset } = useShowcaseLiterature();
  const router = useRouter();
  return <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
    <p className="max-w-2xl text-sm leading-6 text-emerald-950">独立合成流程示例，操作仅在本次体验中生效，刷新后重置。AI 建议与问答使用预置演示内容。正式工作台支持共享保存；这里不会修改正式资料或调用模型。</p>
    <button className={demoButton} onClick={() => { if (window.confirm("重置本次所有模块的示例操作？")) { reset(); router.push(href); } }}>重置示例</button>
  </div>;
}

export function ShowcaseReceipts({ kind }: { kind: "literature" | "case" }) {
  const { receipts } = useShowcaseLiterature();
  const items = receipts.filter((receipt) => kind === "case" ? receipt.kind === "案例 AI 打标" : receipt.kind !== "案例 AI 打标");
  return <section className={demoCard}><h2 className="font-semibold">本次体验处理记录</h2><p className="mt-2 text-xs text-slate-500">正式工作台可保存最近批次并重试失败项；本展示回执在刷新后重置。</p>
    {!items.length && <p className="mt-3 text-sm text-slate-500">暂无处理记录。</p>}
    {items.map((receipt) => <details key={receipt.id} open className="mt-3 rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium">{receipt.kind} · {receipt.items.length} 项 · 合成演示</summary><ul className="mt-3 space-y-2 text-sm">{receipt.items.map((item) => <li key={item.id} className="flex flex-wrap justify-between gap-2"><span className="min-w-0 break-words">{item.title} · {item.status}</span>{item.href && <Link href={item.href} className="text-emerald-800 underline">审核资料</Link>}</li>)}</ul></details>)}
  </section>;
}
