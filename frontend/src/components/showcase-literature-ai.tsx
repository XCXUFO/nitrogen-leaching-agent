"use client";

import Link from "next/link";
import { useState } from "react";
import { useShowcaseLiterature } from "./showcase-literature-provider";
import { ShowcaseReceipts, demoButton as button, demoPrimary as primary, demoCard as card } from "./showcase-experience";
import { blankDemoPaper } from "@/lib/showcase-literature";
import { demoPaperSuggestions, demoSuggestedTags } from "@/lib/showcase-workbench";

export function ShowcaseLiteratureTools({ selected, clear }: { selected: string[]; clear: () => void }) {
  const { papers, setPapers, receipts, setReceipts } = useShowcaseLiterature();
  const [extract, setExtract] = useState(true);
  const [tag, setTag] = useState(true);
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState("");
  function process() {
    setPapers((items) => items.map((paper) => selected.includes(paper.id) ? { ...paper, ...(extract ? demoPaperSuggestions : {}), ...(tag ? { tags: demoSuggestedTags(paper.title) } : {}), events: ["体验操作 · 已有文献 AI 处理（预置建议）", ...paper.events] } : paper));
    setReceipts((items) => [{ id: crypto.randomUUID(), kind: "已有文献 AI 处理", items: papers.filter((paper) => selected.includes(paper.id)).map((paper) => ({ id: paper.id, title: paper.title, status: "已采用预置建议 · 请审核", href: `/showcase/literature/${paper.id}` })) }, ...items]);
    setMessage("所选示例已处理，登记和使用状态保留。请进入详情核对字段与标签。"); clear();
  }
  function importSamples() {
    const id = `SAMPLE-${crypto.randomUUID().slice(0, 8)}`;
    const paper = { ...blankDemoPaper(), id, title: "批量导入的水氮管理笔记（流程示例）", source: "预置合成批次，统一使用流程说明 PDF。", ...(extract ? demoPaperSuggestions : {}), tags: tag ? ["water-n"] : [], events: ["体验操作 · 批量导入示例，待人工审核"] };
    setPapers((items) => [paper, ...items]);
    setReceipts((items) => [{ id: crypto.randomUUID(), kind: "文献批量导入", aiExtract: extract, aiTag: tag, items: [
      { id, title: "水氮管理笔记.pdf", status: "已保存草稿 · 请审核", href: `/showcase/literature/${id}` },
      { id: "duplicate", title: "冬小麦研究（重复示例）.pdf", status: "重复文件 · 未再次导入", href: "/showcase/literature/SAMPLE-002" },
      { id: `${id}-retry`, title: "水稻研究（失败示例）.pdf", status: "模拟处理失败 · 可重试预置流程" },
    ] }, ...items]);
    setImporting(false); setMessage("合成批次已完成：1 项草稿、1 项重复、1 项模拟失败。失败项不会影响成功项。");
  }
  function retry() {
    const pending = receipts.flatMap((receipt) => receipt.items.filter((item) => item.status.startsWith("模拟处理失败")).map((item) => ({ ...item, aiExtract: receipt.aiExtract, aiTag: receipt.aiTag })));
    const recovered = pending.map((item) => ({ ...blankDemoPaper(), id: item.id, title: "重试后的水稻研究（流程示例）", source: "合成失败重试流程，统一使用流程说明 PDF。", ...(item.aiExtract ? demoPaperSuggestions : {}), tags: item.aiTag ? ["rice"] : [], events: ["体验操作 · 重试后保存草稿（预置建议）"] }));
    setPapers((items) => [...recovered, ...items]);
    setReceipts((items) => items.map((receipt) => ({ ...receipt, items: receipt.items.map((item) => pending.some((entry) => entry.id === item.id) ? { ...item, status: "重试完成 · 已保存示例草稿", href: `/showcase/literature/${item.id}` } : item) })));
    setMessage("失败条目的预置重试流程已完成，成功和重复条目未再次处理。");
  }
  return <section className={`${card} space-y-4`} aria-label="文献批量工具">
    <div className="flex flex-wrap justify-between gap-3"><div><h2 className="font-semibold">批量导入与 AI 处理</h2><p className="mt-2 text-sm leading-6 text-slate-500">正式工作台支持一次 1–100 篇 PDF。本展示使用预置的成功、重复与失败条目，不接收真实文件。</p></div><button className={primary} onClick={() => setImporting(true)}>批量导入示例</button></div>
    <div className="flex flex-wrap gap-4 text-sm"><label className="flex items-center gap-2"><input type="checkbox" checked={extract} onChange={(e) => setExtract(e.target.checked)} />批量 AI 解析字段</label><label className="flex items-center gap-2"><input type="checkbox" checked={tag} onChange={(e) => setTag(e.target.checked)} />批量 AI 一键打标</label></div>
    <p className="text-xs leading-6 text-slate-500">已有文献处理会覆盖解析到的字段，打标会替换原标签；登记状态保持原值。所有结果均为预置建议。</p>
    <button className={button} disabled={!selected.length || (!extract && !tag)} onClick={process}>AI 处理所选文献（{selected.length}）</button>
    {importing && <div role="dialog" aria-label="批量导入预置示例" className="space-y-3 rounded-lg border border-emerald-200 p-4"><h3 className="font-medium">预置合成批次 · 3 个条目</h3><p className="text-sm leading-6 text-slate-500">水氮管理笔记：成功；冬小麦研究：重复；水稻研究：模拟处理失败。沿用上方两项 AI 开关，成功项先保存为草稿。</p><button className={primary} onClick={importSamples}>开始预置导入</button><button className={`${button} ml-2`} onClick={() => setImporting(false)}>取消导入</button></div>}
    {message && <p role="status" className="text-sm text-emerald-800">{message}</p>}
    {receipts.some((receipt) => receipt.items.some((item) => item.status.startsWith("模拟处理失败"))) && <button className={button} onClick={retry}>重试失败示例</button>}
    <details><summary className="cursor-pointer text-sm text-emerald-800">查看本次处理记录</summary><div className="mt-3"><ShowcaseReceipts kind="literature" /></div></details>
    <Link href="/showcase/literature/new" className="text-sm text-emerald-800 underline">也可逐篇登记并审核 AI 建议</Link>
  </section>;
}
