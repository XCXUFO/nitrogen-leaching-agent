"use client";

import type { EvaluationCase } from "@/lib/evaluation-api";

type CaseData = EvaluationCase["case"];
const field = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm";
const button = "rounded-md border border-input px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const actions = ["query", "upload", "remove_attachment", "clear", "refresh", "wait", "manual"];

export function EvaluationCaseEditor({ text, onChange }: { text: string; onChange: (value: string) => void }) {
  let value: CaseData;
  try { value = JSON.parse(text) as CaseData; }
  catch { return <p className="text-sm text-muted-foreground">点击“新建空白用例”、复制当前用例，或选择已有草稿开始编辑。</p>; }
  if (!value || typeof value !== "object" || !Array.isArray(value.steps) || !Array.isArray(value.expected)) {
    return <p className="text-sm text-destructive">用例结构不完整，请先检查 JSON。</p>;
  }
  const change = (partial: Partial<CaseData>) => onChange(JSON.stringify({ ...value, ...partial }, null, 2));
  return <details open className="rounded border p-3"><summary className="cursor-pointer text-sm font-medium">表单编辑用例字段、步骤与标准</summary>
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      <label className="text-sm">用例 ID<input aria-label="表单用例 ID" className={field} value={value.case_id ?? ""} onChange={(e) => change({ case_id: e.target.value })} /></label>
      <label className="text-sm">版本<input aria-label="表单用例版本" type="number" min={1} className={field} value={value.version ?? 1} onChange={(e) => change({ version: Number(e.target.value) })} /></label>
      <label className="text-sm">标题<input aria-label="表单用例标题" className={field} value={value.title ?? ""} onChange={(e) => change({ title: e.target.value })} /></label>
      <label className="text-sm">类别<select aria-label="表单用例类别" className={field} value={value.category ?? "X"} onChange={(e) => change({ category: e.target.value })}>
        {["A", "K", "F", "B", "X", "O", "NEW"].map((item) => <option key={item}>{item}</option>)}</select></label>
      <label className="text-sm">优先级<select aria-label="表单用例优先级" className={field} value={value.priority ?? "P1"} onChange={(e) => change({ priority: e.target.value })}>
        {["P0", "P1", "P2"].map((item) => <option key={item}>{item}</option>)}</select></label>
      <label className="text-sm">来源<input aria-label="表单用例来源" className={field} value={value.source ?? ""} onChange={(e) => change({ source: e.target.value })} /></label>
      <label className="text-sm md:col-span-2">前提<textarea aria-label="表单用例前提" className={field} value={value.preconditions ?? ""} onChange={(e) => change({ preconditions: e.target.value })} /></label>
      <label className="text-sm md:col-span-2">附件要求（每行一个文件名）<textarea aria-label="表单附件要求" className={field} value={(value.attachment_requirements ?? []).join("\n")}
        onChange={(e) => change({ attachment_requirements: e.target.value.split("\n").map((line) => line.trim()).filter(Boolean) })} /></label>
      <label className="text-sm md:col-span-2">预期标准（每行一项）<textarea aria-label="表单预期标准" className={field} rows={4} value={value.expected.join("\n")}
        onChange={(e) => change({ expected: e.target.value.split("\n").map((line) => line.trim()).filter(Boolean) })} /></label>
    </div>
    <div className="mt-3 space-y-3"><div className="flex items-center justify-between"><h4 className="font-medium">执行步骤</h4>
      <button className={button} type="button" onClick={() => change({ steps: [...value.steps, { action: "query", instruction: "", input: "" }] })}>新增步骤</button></div>
      {value.steps.map((step, index) => <div key={index} className="grid gap-2 rounded border p-2 md:grid-cols-[9rem_1fr]">
        <select aria-label={`步骤 ${index + 1} 动作`} className={field} value={step.action}
          onChange={(e) => change({ steps: value.steps.map((item, i) => i === index ? { ...item, action: e.target.value } : item) })}>
          {actions.map((action) => <option key={action}>{action}</option>)}
        </select>
        <input aria-label={`步骤 ${index + 1} 说明`} className={field} value={step.instruction ?? ""} placeholder="步骤说明"
          onChange={(e) => change({ steps: value.steps.map((item, i) => i === index ? { ...item, instruction: e.target.value } : item) })} />
        <input aria-label={`步骤 ${index + 1} 输入`} className={field} value={step.input ?? ""} placeholder="问题原句（若适用）"
          onChange={(e) => change({ steps: value.steps.map((item, i) => i === index ? { ...item, input: e.target.value } : item) })} />
        <div className="flex gap-2"><input aria-label={`步骤 ${index + 1} 附件`} className={field} value={step.attachment ?? ""} placeholder="附件名（若适用）"
          onChange={(e) => change({ steps: value.steps.map((item, i) => i === index ? { ...item, attachment: e.target.value } : item) })} />
          <button className={button} type="button" disabled={value.steps.length <= 1} onClick={() => change({ steps: value.steps.filter((_, i) => i !== index) })}>移除</button></div>
      </div>)}
    </div>
    <p className="mt-2 text-xs text-muted-foreground">表单与下方 JSON 同步。提交时仍由服务端校验用例结构、附件资产与版本；已发布版本不可改写。</p>
  </details>;
}
