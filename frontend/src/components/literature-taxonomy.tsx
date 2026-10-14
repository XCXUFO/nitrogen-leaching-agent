"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Plus, X } from "lucide-react";

export type TaxonomyNode = { id: string; dimension_id: string; parent_id: string | null; name: string; path: string; enabled?: number | boolean };
type Dimension = { id: string; name: string; enabled?: number | boolean; selection?: string; required?: number | boolean };
const input = "min-w-0 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm";
const button = "inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-40";

export function isWithin(id: string, ancestor: string, nodes: TaxonomyNode[]) {
  let node = nodes.find((item) => item.id === id);
  const seen = new Set<string>();
  while (node && !seen.has(node.id)) {
    if (node.id === ancestor) return true;
    seen.add(node.id);
    node = nodes.find((item) => item.id === node!.parent_id);
  }
  return false;
}

/** Browsing a branch never selects it. A checked parent includes descendants only in search mode. */
export function TagCascader({ dimensions, nodes, value, onChange, mode = "filter", includeDisabled = false }: {
  dimensions: Dimension[]; nodes: TaxonomyNode[]; value: string[]; onChange: (value: string[]) => void;
  mode?: "filter" | "assign"; includeDisabled?: boolean;
}) {
  return <div className="space-y-2">
    <div className="flex flex-wrap gap-2">{dimensions.filter((dim) => dim.enabled !== 0 && dim.enabled !== false || includeDisabled || value.some((id) => nodes.some((n) => n.id === id && n.dimension_id === dim.id))).map((dim) => <DimensionPicker key={dim.id} dimension={dim} nodes={nodes} value={value} onChange={onChange} mode={mode} includeDisabled={includeDisabled} />)}{!dimensions.length && <p className="text-xs text-slate-500">暂无分类维度，文献仍属于全局。</p>}</div>
    {!!value.length && <div className="flex flex-wrap gap-2">{value.map((id) => { const node = nodes.find((n) => n.id === id); return <button key={id} type="button" className="inline-flex max-w-full items-center gap-1 rounded bg-emerald-50 px-2 py-1 text-left text-xs text-emerald-900" aria-label={`移除标签 ${node?.path || id}`} onClick={() => onChange(value.filter((v) => v !== id))}><span className="break-words">{dimensions.find((d) => d.id === node?.dimension_id)?.name}：{node?.path || id}</span><X size={12} className="shrink-0" /></button>; })}</div>}
    <p className="text-xs text-slate-500">{mode === "filter" ? "选中父标签包含全部下级；同一维度内为“或”，不同维度间为“且”。" : "按层级选择分类；选择下级会替换同一路径的上级标签。"}</p>
  </div>;
}

function DimensionPicker({ dimension, nodes, value, onChange, mode, includeDisabled }: {
  dimension: Dimension; nodes: TaxonomyNode[]; value: string[]; onChange: (value: string[]) => void; mode: "filter" | "assign"; includeDisabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [branch, setBranch] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);
  const columns = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open && columns.current) columns.current.scrollLeft = columns.current.scrollWidth; }, [branch, open]);
  const own = nodes.filter((node) => node.dimension_id === dimension.id);
  const disabled = (node: TaxonomyNode) => !includeDisabled && (node.enabled === 0 || node.enabled === false || dimension.enabled === 0 || dimension.enabled === false);
  const selectable = own.filter((node) => !disabled(node) || value.includes(node.id));
  // Keep disabled ancestors as navigation when they lead to active/selected descendants.
  const visible = own.filter((node) => selectable.some((child) => isWithin(child.id, node.id, own)));
  const count = value.filter((id) => own.some((node) => node.id === id)).length;
  function choose(node: TaxonomyNode) {
    if (value.includes(node.id)) { onChange(value.filter((id) => id !== node.id)); return; }
    onChange([...value.filter((id) => !(mode === "assign" && dimension.selection === "single" && own.some((n) => n.id === id)) && !isWithin(id, node.id, own) && !isWithin(node.id, id, own)), node.id]);
  }
  function close() { setOpen(false); trigger.current?.focus(); }
  const groups = search.trim() ? [selectable.filter((node) => node.path.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))] : [null, ...branch].map((parent) => visible.filter((node) => node.parent_id === parent));
  return <div className="relative max-w-full" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }} onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); close(); } }}>
    <button ref={trigger} type="button" className={`${button} bg-white ${count ? "border-emerald-400 text-emerald-900" : "border-slate-300"}`} aria-label={`${dimension.name}级联选择`} aria-expanded={open} onClick={() => setOpen(!open)}>{dimension.name}{dimension.required ? " *" : ""}{count > 0 ? ` · ${count}` : mode === "filter" ? " · 不限" : " · 未选择"}<ChevronDown size={14} /></button>
    {open && <div role="dialog" aria-label={`${dimension.name}标签选择`} className="fixed inset-x-3 top-[15vh] z-40 max-h-[75vh] overflow-auto rounded-xl border border-emerald-200 bg-white p-3 shadow-xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-max sm:max-w-[min(40rem,90vw)]">
      <div className="mb-3 flex items-center gap-2"><input className={input} aria-label={`搜索${dimension.name}标签`} placeholder="搜索标签名称或完整路径" value={search} onChange={(e) => setSearch(e.target.value)} /><button type="button" className={button} aria-label="关闭标签选择" onClick={close}><X size={16} /></button></div>
      <div ref={columns} className="flex max-w-full gap-0 overflow-x-auto rounded-lg border">{groups.map((group, depth) => <div key={depth} aria-label={search.trim() ? "标签搜索结果" : `第${depth + 1}级标签`} className="max-h-64 min-w-44 flex-1 overflow-y-auto border-r last:border-r-0">
        <p className="sticky top-0 bg-slate-50 px-3 py-2 text-xs text-slate-500">{search.trim() ? "搜索结果 · 完整路径" : `第 ${depth + 1} 级`}</p>
        {group.map((node) => { const children = visible.some((n) => n.parent_id === node.id); const inherited = mode === "filter" && !value.includes(node.id) && value.some((id) => isWithin(node.id, id, own)); return <div key={node.id} className={`flex items-center gap-1 px-2 py-2 text-sm ${branch[depth] === node.id ? "bg-emerald-50" : "hover:bg-slate-50"}`}>
          <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-2" title={node.path}><input className="mt-1 accent-emerald-600" type="checkbox" checked={value.includes(node.id)} disabled={disabled(node) && !value.includes(node.id)} aria-label={node.path} onChange={() => choose(node)} /><span className="break-words">{search.trim() ? node.path : node.name}{disabled(node) && <small className="block text-slate-400">已停用</small>}{inherited && <small className="block text-emerald-700">已由上级包含</small>}</span></label>
          {children && !search.trim() && <button type="button" className="rounded p-1.5 hover:bg-emerald-100" aria-label={`展开 ${node.path}`} aria-expanded={branch[depth] === node.id} onClick={() => setBranch([...branch.slice(0, depth), node.id])}><ChevronRight size={16} /></button>}
        </div>; })}
        {!group.length && <p className="p-3 text-xs text-slate-500">暂无匹配标签</p>}
      </div>)}</div>
      <div className="mt-3 flex items-center justify-between gap-3 text-xs"><span className="text-slate-500">{mode === "filter" ? "勾选父级包含全部下级" : dimension.selection === "single" ? "本维度单选" : "可选择多个分支"}</span><button type="button" className={button} onClick={close}>完成选择</button></div>
    </div>}
  </div>;
}

/** Explicit nested hierarchy with small, contextual creation forms. */
export function TaxonomyTree({ nodes, onAdd, actions, description }: {
  nodes: TaxonomyNode[]; onAdd: (parent: string | null, name: string) => Promise<void>;
  actions?: (node: TaxonomyNode) => ReactNode; description?: (node: TaxonomyNode) => ReactNode;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const matches = nodes.filter((node) => node.path.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  function start(parent: string) { setAdding(parent); setName(""); setError(""); setExpanded((old) => new Set([...old, parent])); }
  function addForm(parent: string) { return adding === parent && <form className="my-2 rounded-lg border border-emerald-200 bg-emerald-50/40 p-3" onSubmit={async (e) => { e.preventDefault(); if (saving) return; const trimmed = name.trim(); if (!trimmed) { setError("请填写标签名称。"); return; } setSaving(true); setError(""); try { await onAdd(parent || null, trimmed); setName(""); setAdding(null); } catch (e) { setError(e instanceof Error ? e.message : "保存失败，请重试。"); } finally { setSaving(false); } }}>
    <p className="mb-2 text-xs text-slate-600">{parent ? `添加到：${nodes.find((n) => n.id === parent)?.path}` : "添加一级标签"}</p><div className="flex flex-wrap gap-2"><input autoFocus className={`${input} flex-1 basis-36`} aria-label="新标签名称" placeholder="标签名称" maxLength={50} value={name} disabled={saving} onChange={(e) => setName(e.target.value)} /><button type="submit" className={`${button} bg-emerald-700 text-white hover:bg-emerald-800`} disabled={saving}>{saving ? "保存中…" : "保存标签"}</button><button type="button" className={button} disabled={saving} onClick={() => setAdding(null)}>取消</button></div>{error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
  </form>; }
  function branch(parent: string | null, depth: number): ReactNode {
    return <ul className={parent ? "ml-3 border-l border-slate-200 pl-3 sm:ml-4" : "space-y-1"}>{nodes.filter((node) => node.parent_id === parent && (!search.trim() || matches.some((m) => isWithin(m.id, node.id, nodes)))).map((node) => {
      const children = nodes.some((n) => n.parent_id === node.id);
      const open = !!search.trim() || expanded.has(node.id);
      return <li key={node.id}>
        <div data-tag-id={node.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg px-2 py-2 hover:bg-slate-50">
          <div className="flex min-w-0 items-center gap-2">{children ? <button type="button" aria-label={`${open ? "收起" : "展开"} ${node.path}`} aria-expanded={open} className="shrink-0 rounded p-1 hover:bg-slate-200" onClick={() => setExpanded((old) => { const next = new Set(old); if (next.has(node.id)) next.delete(node.id); else next.add(node.id); return next; })}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button> : <span className="w-6 shrink-0 text-center text-slate-300">•</span>}
            <div className="min-w-0"><span className="break-words text-sm font-medium" title={node.path}>{node.name}</span><span className="ml-2 whitespace-nowrap text-xs text-slate-400">{depth} 级{node.enabled === 0 || node.enabled === false ? " · 已停用" : ""}</span>{description && <div className="text-xs text-slate-500">{description(node)}</div>}</div>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">{depth < 5 && <button type="button" disabled={saving} aria-label={`在 ${node.path} 下新增标签`} className="inline-flex items-center gap-1 text-emerald-800 hover:underline" onClick={() => start(node.id)}><Plus size={13} />新增下级</button>}{actions?.(node)}</div>
        </div>
        {addForm(node.id)}{children && open && branch(node.id, depth + 1)}
      </li>;
    })}</ul>;
  }
  return <div className="space-y-3"><div className="flex flex-wrap gap-2"><input className={`${input} flex-1 basis-40`} placeholder="搜索标签名称或完整路径" aria-label="搜索标签树" value={search} onChange={(e) => setSearch(e.target.value)} /><button type="button" className={button} disabled={saving} onClick={() => { setSearch(""); start(""); }}><Plus size={14} />新增一级标签</button><button type="button" className={button} onClick={() => setExpanded(new Set(nodes.map((n) => n.id)))}>展开全部</button><button type="button" className={button} onClick={() => { setSearch(""); setExpanded(new Set()); }}>收起全部</button></div>{addForm("")}{branch(null, 1)}{!matches.length && <p className="p-4 text-center text-sm text-slate-500">{nodes.length ? "暂无匹配标签" : "暂无标签，点击“新增一级标签”开始分类。"}</p>}<p className="text-xs text-slate-500">维度为分类起点，下设最多五级标签。展开节点可查看下级，在节点旁直接新增。</p></div>;
}
