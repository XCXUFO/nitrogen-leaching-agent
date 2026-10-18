"use client";

import { useEffect, useState } from "react";
import { evaluationRequest } from "@/lib/evaluation-api";

type Values = { style: "plain" | "professional"; detail: "short" | "medium" | "detailed"; organization: "answer_first" | "steps" };
type Configuration = { revision: number; version: string; values: Values; actor: string; changed_at: string | null; action: string };
const choices = {
  style: { plain: "简洁易懂，解释必要术语", professional: "保留专业术语并解释" },
  detail: { short: "简短", medium: "适中", detailed: "详细" },
  organization: { answer_first: "先回答，再补背景和例子", steps: "按相关步骤组织" },
};
const labels = { style: "默认表达风格", detail: "默认详细程度", organization: "回答组织方式" };
const button = "rounded-lg border bg-white px-3 py-2 text-sm disabled:opacity-50";

export function SkillExpressionEditor({ token }: { token: string }) {
  const [current, setCurrent] = useState<Configuration | null>(null);
  const [draft, setDraft] = useState<Values | null>(null);
  const [history, setHistory] = useState<Configuration[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [reload, setReload] = useState(0);
  const dirty = !!current && !!draft && JSON.stringify(draft) !== JSON.stringify(current.values);

  useEffect(() => {
    let active = true;
    evaluationRequest<{ current: Configuration; history: Configuration[] }>(token, "/skills/case_explanation/configuration")
      .then((data) => { if (active) { setCurrent(data.current); setDraft(data.current.values); setHistory(data.history); setError(""); } })
      .catch((problem) => { if (active) setError(problem instanceof Error ? problem.message : "配置读取失败。"); });
    return () => { active = false; };
  }, [token, reload]);

  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    const beforeLink = (event: MouseEvent) => {
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (link && !window.confirm("配置尚未保存，确定离开？")) { event.preventDefault(); event.stopPropagation(); }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", beforeLink, true);
    return () => { window.removeEventListener("beforeunload", beforeUnload); document.removeEventListener("click", beforeLink, true); };
  }, [dirty]);

  async function save(reset: boolean) {
    if (!current || !draft || saving) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const value = await evaluationRequest<Configuration>(token, `/skills/case_explanation/configuration${reset ? "/reset" : ""}`, {
        method: reset ? "POST" : "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: current.revision, ...(!reset ? { values: draft } : {}) }),
      });
      setCurrent(value); setDraft(value.values); setHistory((items) => [value, ...items].slice(0, 50));
      setNotice(`${reset ? "已恢复默认" : "已保存并启用"}，新运行使用版本 ${value.version}。`);
    } catch (problem) { setError(problem instanceof Error ? problem.message : "保存失败，输入已保留。"); }
    finally { setSaving(false); }
  }

  return <section className="space-y-3 rounded-xl border bg-white p-4" aria-label="表达配置">
    <h3 className="text-sm font-semibold">表达配置</h3>
    <p className="text-sm leading-6 text-slate-600">仅影响案例解释的默认表达；用户本轮要求优先。专业事实、来源、计算口径和路由由系统保留。保存后新运行采用，已受理运行保留当时配置。</p>
    {current && draft && <>
      <p className="break-all text-xs text-slate-500">生效版本：{current.version}{dirty ? " · 有未保存修改" : ""}</p>
      <div className="grid gap-3 sm:grid-cols-3">{(Object.keys(choices) as (keyof Values)[]).map((key) => <label key={key} className="space-y-1 text-sm"><span>{labels[key]}</span><select aria-label={labels[key]} disabled={saving} value={draft[key]} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} className="min-h-10 w-full rounded-lg border bg-white px-2">{Object.entries(choices[key]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>)}</div>
      <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={saving || !dirty} onClick={() => void save(false)}>保存并启用</button><button type="button" className={button} disabled={saving} onClick={() => void save(true)}>恢复默认</button><button type="button" className={button} disabled={saving} onClick={() => { if (!dirty || window.confirm("放弃当前修改并读取最新配置？")) setReload((n) => n + 1); }}>读取最新配置</button></div>
    </>}
    {error && <p role="alert" className="text-sm text-amber-900">{error}</p>}
    {!current && <button type="button" className={button} onClick={() => setReload((n) => n + 1)}>重新读取配置</button>}
    {notice && <p role="status" className="text-sm text-emerald-800">{notice}</p>}
    <details><summary className="cursor-pointer text-sm">变更记录</summary><ul className="mt-2 space-y-2 text-xs text-slate-600">{history.length ? history.map((item) => <li key={item.revision} className="rounded border p-2"><p>{item.version} · {item.action === "reset" ? "恢复默认" : "保存"} · {item.actor} · {item.changed_at}</p><p className="mt-1">{choices.style[item.values.style]}；{choices.detail[item.values.detail]}；{choices.organization[item.values.organization]}</p></li>) : <li>当前使用内置默认配置，尚无修改。</li>}</ul></details>
  </section>;
}
