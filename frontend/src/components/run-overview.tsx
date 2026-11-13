"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import type { SessionTrace } from "@/lib/evaluation-api";
import { documents, executionView, keywordsView, material, object, outputView, recallPaths, records, retrievalViews, skillName, statusName, unique, word, type Data, type Material, type RetrievalView } from "@/lib/run-trace-view";

const muted = "text-xs leading-5 text-slate-500";
const pill = "inline-flex rounded-md border bg-white px-2 py-1 text-xs";
const usages: Record<string, string> = { explicit_tag_filter: "标签过滤", semantic_condition: "正文条件核对", ranking_signal: "辅助召回与排序" };
const methods: Record<string, string> = { exact_name: "名称匹配", exact_path: "路径匹配", controlled_alias: "标准别名", configured_alias: "配置别名" };
const reasons: Record<string, string> = { condition_unconfirmed: "条件未确认", material_budget: "材料预算不足", reference_list: "参考文献列表", comparison_incomplete: "比较对象不完整" };
const paths: Record<string, string> = { tag: "标签", full_text: "全文", semantic: "语义", managed_text: "文献正文", bounded_expansion: "补充候选", session: "会话文件" };
const routeNames: Record<string, string> = { KNOWLEDGE: "知识问答", COMPOSED: "组合分析", FILE_ANALYSIS: "文件分析", CLARIFY: "澄清问题", DIRECT: "直接回答", OUT_OF_SCOPE: "能力说明" };

function Card({ title, children }: { title: string; children: ReactNode }) {
  return <section className="min-w-0 space-y-3 rounded-lg border bg-white p-3"><h3 className="text-sm font-semibold text-slate-900">{title}</h3>{children}</section>;
}

function Source({ item }: { item: Material }) {
  return item.href ? <Link aria-label={`查看资料：${item.title}`} className="break-words text-emerald-800 underline decoration-emerald-300 underline-offset-2" href={item.href} target="_blank" rel="noopener noreferrer">{item.title} ↗</Link> : <span className="break-words">{item.title}</span>;
}

function MaterialNames({ items, empty = "无" }: { items: Material[]; empty?: string }) {
  const docs = documents(items);
  return docs.length ? <span className="inline-flex flex-wrap gap-1.5">{docs.map((item, index) => <span key={item.key} className={pill}>#{index + 1} <Source item={item} /></span>)}</span> : <span className={muted}>{empty}</span>;
}

function rank(items: Material[], doc: Material) {
  const index = items.findIndex((item) => item.key === doc.key);
  return index < 0 ? null : index + 1;
}

function RetrievalTable({ view, rows }: { view: RetrievalView; rows: Material[] }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[600px] text-left text-sm">
    <thead className="border-b bg-slate-50 text-slate-500"><tr>{["资料", "召回来源", "排序 / 筛选后", "送入模型", "最终引用"].map((name) => <th className="px-2 py-2 font-medium" key={name}>{name}</th>)}</tr></thead>
    <tbody>{rows.map((doc) => {
      const position = rank(view.ranked, doc);
      const supplied = rank(view.supplied, doc);
      const rejected = view.candidates.find((item) => item.key === doc.key && item.selected === false);
      const origins = recallPaths(view.candidates.filter((item) => item.key === doc.key).flatMap((item) => item.paths));
      return <tr className="border-b last:border-b-0" key={doc.key}>
        <td className="max-w-72 px-2 py-2"><Source item={doc} /><p className="mt-1 text-slate-400">{unique(view.candidates.filter((item) => item.key === doc.key).map((item) => item.chunk)).length || 1} 个候选片段</p></td>
        <td className="max-w-40 px-2 py-2 text-slate-500">{origins.length ? origins.map(({ route, rank }) => (paths[route] || (route.startsWith("semantic:") ? "语义 · " + (paths[route.slice(9)] || route.slice(9)) : route)) + (rank ? `（#${rank}）` : "")).join("、") : "未记录"}</td>
        <td className="px-2 py-2">{position ? view.hasRanking ? `#${position}` : "筛选通过" : rejected ? reasons[rejected.reason] || "未通过筛选" : view.hasRanking ? "未入选" : "未记录"}
          {position && rejected && <p className="mt-1 text-slate-500">{reasons[rejected.reason] || "未通过筛选"}</p>}</td>
        <td className="px-2 py-2">{view.hasContext ? supplied ? <span className="text-emerald-800">#{supplied}</span> : "未送入" : "未记录"}</td>
        <td className="px-2 py-2">{view.cited.some((item) => item.key === doc.key) ? <span className="font-medium text-emerald-800">已引用</span> : view.citationUnknown.some((item) => item.key === doc.key) ? <span className="text-amber-800">批次未确认</span> : "未引用"}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}

function RetrievalRound({ view, index, turn }: { view: RetrievalView; index: number; turn: SessionTrace }) {
  const rows = documents([...view.ranked, ...view.candidates, ...view.supplied, ...view.cited]);
  const name = view.kind === "case" ? "案例" : "文献";
  const tagScope = object(view.pipeline.tag_scope);
  return <div className="min-w-0 space-y-2 rounded-lg border p-3" aria-label={`第 ${index + 1} 次资料检索`}>
    <p className="text-xs font-medium">检索 {index + 1} · {name}{view.skill && ` · ${skillName(view.skill)}`}</p>
    {view.query && <p className="break-words text-xs text-slate-600">检索问题：{view.query}</p>}
    {tagScope.mode && tagScope.mode !== "unrestricted" ? <div className="rounded border border-emerald-200 bg-emerald-50/40 p-2 text-xs leading-5">
      <p>标签筛选范围：{records(tagScope.filters).map((filter) => word(filter.term)).join("、")} · {String(tagScope.paper_count)} / {String(tagScope.total_papers)} 篇可用文献</p>
      <p>{tagScope.expanded ? "系统根据证据缺口补查了其他本地文献，正文条件继续核验。" : "范围限制在召回与重排之前执行。"}</p>
      {word(tagScope.expansion_reason) && <p>补查原因：{({ no_usable_tagged_content: "范围内没有可用正文", comparison_objects_missing: "比较对象的证据不完整", necessary_explanation_gap: "现有内容缺少必要解释" } as Record<string, string>)[word(tagScope.expansion_reason)] || word(tagScope.expansion_reason)}</p>}
      {typeof tagScope.retrieval_ms === "number" && <p>本轮检索 {tagScope.retrieval_ms} ms · 条件核验后 {String(tagScope.eligible_chunks ?? 0)} 个可用片段</p>}
      {tagScope.retrieval_failed === true && <p>检索发生异常，未以此触发范围扩大。</p>}
    </div> : null}
    {view.tasks.length > 0 && <p className={muted}>对应任务：{view.tasks.map((id) => {
      const tasks = records(object(turn.understanding).subtasks);
      const taskIndex = tasks.findIndex((task) => task.subtask_id === id);
      return taskIndex >= 0 ? `任务 ${taskIndex + 1}` : id;
    }).join("、")}</p>}
    <p className="flex flex-wrap gap-x-2 gap-y-1 text-xs text-slate-600">
      <span>候选 {documents(view.candidates).length} 份 / {view.candidates.length} 片段</span><span aria-hidden="true">→</span>
      <span>{view.hasRanking ? "排序后" : "筛选通过"} {documents(view.ranked).length} 份</span><span aria-hidden="true">→</span>
      <span>送入模型 {view.hasContext ? `${documents(view.supplied).length} 份` : "未记录"}</span><span aria-hidden="true">→</span><span>引用 {documents(view.cited).length} 份</span>
      {view.citationUnknown.length > 0 && <span className="text-amber-800">另有 {documents(view.citationUnknown).length} 份最终来源的引用批次未确认</span>}
    </p>
    {rows.length ? <>
      <RetrievalTable view={view} rows={rows.slice(0, 6)} />
      {rows.length > 6 && <details><summary className="cursor-pointer text-xs text-emerald-800">展开其余 {rows.length - 6} 份资料</summary><RetrievalTable view={view} rows={rows.slice(6)} /></details>}
      <p className={muted}>按资料去重展示；名次取该资料最前片段的位置。筛选通过、送入模型和最终引用分别记录。</p>
    </> : <p className={muted}>{view.pipeline.candidate_count ? `本轮记录了 ${view.pipeline.candidate_count} 个候选，未保存具体资料名单。` : "本轮没有记录候选资料。"}</p>}
    {view.semantic.length ? <details className="rounded border bg-slate-50 p-2"><summary className="cursor-pointer text-xs text-slate-600">重排前后对比 · {view.semantic.length} 路语义检索</summary>
      <div className="mt-3 space-y-3">{view.semantic.map((round, roundIndex) => <div className="space-y-2 text-xs" key={roundIndex}>
        <p className="font-medium">语义检索 {roundIndex + 1}：{word(round.query)}</p>
        <div className="space-y-2"><div>重排前：<MaterialNames items={records(round.recall).map((item) => material(item, view.kind))} empty="历史记录未保存" /></div>
          <div>重排后：{round.rerank_status === "applied" ? <MaterialNames items={records(round.reranked).map((item) => material(item, view.kind))} /> : <span className={muted}>{round.rerank_status === "disabled" ? "本路未启用重排" : round.rerank_status === "no_candidates" ? "没有可重排的候选" : "历史记录未单独保存重排阶段"}</span>}</div>
          <div>本路返回：<MaterialNames items={records(round.returned).map((item) => material(item, view.kind))} /></div></div>
      </div>)}</div>
    </details> : <p className={muted}>{view.kind === "case" ? "案例按相关度和条件核对结果筛选。" : "未单独记录重排阶段；上表展示已保存的排序或筛选结果。"}</p>}
  </div>;
}

function Step({ step, all }: { step: Data; all: Data[] }) {
  const kind = word(step.kind);
  const skill = word(step.skill);
  const parent = all.find((item) => item.step_id === step.parent_step_id);
  const label = word(step.name) || skillName(skill);
  const elapsed = typeof step.latency_ms === "number" ? step.latency_ms : word(step.started_at) && word(step.time) ? Date.parse(word(step.time)) - Date.parse(word(step.started_at)) : null;
  return <div className={`rounded border px-3 py-2 text-xs ${kind === "skill" ? "border-emerald-200 bg-emerald-50/40" : "bg-white"}`}>
    <div className="flex flex-wrap items-center justify-between gap-2"><span><span className="mr-2 text-slate-400">{kind === "skill" ? "Skill" : kind === "tool" ? "工具" : "服务"}</span>
      {kind === "skill" && skill ? <Link href={`/evaluation/skills/${encodeURIComponent(skill)}`} className="text-emerald-800 underline">{skillName(skill)}</Link> : label}</span>
      <span className={step.status === "failed" || step.status === "error" ? "text-red-700" : "text-slate-500"}>{statusName(step.status)}{typeof elapsed === "number" && Number.isFinite(elapsed) && elapsed >= 0 ? ` · ${elapsed} ms` : ""}</span></div>
    {parent?.skill ? <p className="mt-1 text-slate-500">归属：{skillName(word(parent.skill))}</p> : null}
    {typeof step.attempt_no === "number" && step.attempt_no > 1 && <p className="mt-1 text-amber-800">第 {step.attempt_no} 次尝试</p>}
    {step.error_code ? <p className="mt-1 text-red-700">{word(step.error_code)}</p> : null}
  </div>;
}

export function RunOverview({ turn }: { turn: SessionTrace }) {
  const keywords = keywordsView(turn);
  const retrieval = retrievalViews(turn);
  const steps = executionView(turn);
  const output = outputView(turn);
  const evidence = records(turn.evidence);
  const sources = documents(evidence.map((item) => material(item, word(item.source_type), evidence)));
  const starred = object(turn.starred_match);
  const understanding = object(turn.understanding);
  const semantic = object(understanding.semantic);
  const calls = turn.tool_calls || [];
  const stageNames: Record<string, string> = { file_observation: "文件计算结果", literature_inference: "文献机理说明", limitation: "未覆盖部分与局限" };
  const mappingRecorded = Object.keys(keywords.mapping).length > 0;
  const skipped = keywords.mapping.status === "skipped";
  const flow = starred.status === "full" && !calls.length && !retrieval.length
    ? ["理解问题", "星标覆盖需求", output.title]
    : ["理解问题", "匹配星标与标签", calls.length ? "执行 Skill" : "Skill 调用未记录", retrieval.length ? "检索与排序" : "无检索记录", output.title];
  return <section aria-label="本轮执行概览" className="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50/30 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold text-emerald-950">本轮执行概览</h2><span className={muted}>{statusName(turn.outcome || turn.status)} · {turn.latency_ms} ms</span></div>
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600" aria-label="本轮处理流程">
      {flow.map((name, index) => <span className="flex items-center gap-2" key={name}>{index > 0 && <span aria-hidden="true">→</span>}<span className="rounded border bg-white px-2 py-1">{name}</span></span>)}
    </div>
    <Card title="问题理解与 Query 改写">
      <p className="break-words text-xs text-slate-600">原问题：{word(understanding.raw_query) || turn.input || "未记录"}</p>
      {semantic.status === "applied" ? <>
        <p className={muted}>语义理解模型：{word(semantic.model)} · {semantic.candidate_recall === "full_library_semantic_review" ? "逐项核对星标库的语义与答案覆盖范围" : semantic.candidate_recall === "embedding_semantic_recall" ? "向量召回星标后核对答案覆盖范围" : semantic.candidate_recall === "semantic_candidate_recall_unavailable" ? "星标语义召回暂不可用，已完成问题理解与改写" : "本轮无需星标匹配"}</p>
        {records(semantic.rewrites).map((item, index) => <div className="space-y-1 rounded border bg-white p-2 text-xs" key={word(item.subtask_id) || index}>
          <p>需求理解：{word(item.intent_description)}</p>
          <p className="break-words">独立问题：{word(item.resolved_query)}</p>
          <p className="break-words">检索 Query：{word(item.effective_retrieval_query)}</p>
          {item.status === "rejected_scope_change" && <p className="text-amber-800">改写未通过条件保留检查，使用原问题。</p>}
          {word(item.clarification) && <p className="text-amber-800">待澄清：{word(item.clarification)}</p>}
        </div>)}
        {records(semantic.assessments).flatMap((aspect) => records(aspect.matches)).filter((match) => match.coverage !== "none").map((match, index) => <p className={muted} key={index}>星标覆盖判断：{word(match.reason)}</p>)}
      </> : <p className={muted}>{semantic.status === "degraded" ? "本轮模型理解失败，已回退到原问题与规则处理。" : semantic.status === "unavailable" ? "本轮未配置语义理解模型，使用原问题与规则处理。" : "历史记录未保存模型理解与改写结果。"}</p>}
    </Card>
    <Card title="1 · 关键词与标签">
      <p className="text-sm">关键词 <strong>{keywords.rows.length || Object.keys(object(turn.understanding)).length ? `${keywords.rows.length} 个` : "未记录"}</strong>{mappingRecorded && !skipped && keywords.mapping.status !== "unavailable" && <> · 已匹配 <strong>{keywords.matched}</strong> 个 · 命中 <strong>{keywords.tagCount}</strong> 个标签{keywords.ambiguous > 0 && <> · 待确认 <strong>{keywords.ambiguous}</strong> 个</>}</>}</p>
      {keywords.mapping.status === "unavailable" && <p className={muted}>标签体系不可用，未完成标签匹配。</p>}
      {skipped && <p className={muted}>{keywords.mapping.reason === "starred_full_coverage" ? "星标问答已完整覆盖，本轮跳过标签映射。" : "本轮跳过标签映射。"}</p>}
      {!mappingRecorded && <p className={muted}>历史记录未保存标签匹配过程。</p>}
      {keywords.rows.length ? <div className="flex flex-wrap gap-2">{keywords.rows.map((row) => <div key={row.keyword} className="rounded-lg border bg-slate-50 px-3 py-2 text-sm">
        <span className="font-medium">{row.keyword}</span><span className="mx-2 text-slate-400">→</span>
        <span className={row.ambiguous ? "text-amber-800" : "text-emerald-800"}>{row.tags.length ? unique(row.tags.map((tag) => word(tag.path) || word(tag.id))).join("、") : row.coveredByStarred ? "星标已覆盖，未再映射" : skipped ? "本轮跳过" : mappingRecorded ? "未匹配标签" : "未记录"}</span>
        {row.ambiguous && <span className="ml-2 text-amber-800">待确认，候选不计入命中数</span>}
        {row.matches.length > 0 && <p className="mt-1 text-slate-500">{unique(row.matches.map((match) => `${methods[word(match.method)] || "匹配"} · ${usages[word(match.usage)] || "用途未记录"}${match.polarity === "exclude" ? " · 排除条件" : ""}`)).join("；")}</p>}
      </div>)}</div> : <p className={muted}>{Object.keys(object(turn.understanding)).length ? "本轮未提取到结构化关键词。" : "历史记录未保存关键词。"}</p>}
      {Boolean(starred.status) && <p className={muted}>星标问答：{({ full: "完整覆盖", partial: "部分覆盖", no_match: "未命中", not_applicable: "本轮不适用", empty_library: "问答库为空", failed: "匹配失败，继续处理" }[word(starred.status)] || "未采用或不可用")} · 采用 {unique(records(starred.adopted).map((item) => word(item.question_id))).length} 项。</p>}
    </Card>
    <Card title="2 · 资料召回、排序与采用">
      {retrieval.length ? retrieval.map((view, index) => <RetrievalRound key={index} view={view} index={index} turn={turn} />) : <p className={muted}>{skipped && keywords.mapping.reason === "starred_full_coverage" ? "星标答复已覆盖需求，本轮未继续检索。" : "本轮没有资料检索记录；文件分析或直接回答可能无需检索。"}</p>}
    </Card>
    <Card title="3 · 实际调用的 Skill 与步骤">
      <p className="text-xs text-slate-600">路由：{routeNames[turn.decision?.route || ""] || turn.decision?.route || "未记录"} · 实际调用 Skill {turn.tool_calls ? `${calls.length} 次` : "未记录"}</p>
      {calls.length > 0 && <div className="flex flex-wrap gap-2">{calls.map((call, index) => <span className={pill} key={index}>{index + 1}. {skillName(call.skill)} · {statusName(call.status)}</span>)}</div>}
      {steps.length ? <div className="space-y-2">{steps.slice(0, 5).map((step, index) => <Step key={index} step={step} all={steps} />)}
        {steps.length > 5 && <details><summary className="cursor-pointer text-xs text-emerald-800">查看全部 {steps.length} 个步骤及 Skill 归属</summary><div className="mt-2 space-y-2">{steps.slice(5).map((step, index) => <Step key={index} step={step} all={steps} />)}</div></details>}
      </div> : <p className={muted}>{starred.status === "full" ? "复用已有答复，没有继续调用 Skill。" : "未记录实际调用步骤。"}</p>}
      <p className={muted}>按实际执行记录展示；计划中的候选能力保留在下方底层明细。</p>
    </Card>
    <Card title="4 · 最终如何输出">
      <p className="text-sm font-medium text-emerald-900">{output.title}</p><p className="text-xs text-slate-600">{output.detail}</p>
      {records(turn.sections).length > 0 && <div className="flex flex-wrap gap-2">{records(turn.sections).map((section, index) => <span className={pill} key={index}>第 {index + 1} 段 · {stageNames[word(section.kind)] || word(section.kind)}</span>)}</div>}
      <div className="text-xs"><p className="mb-2 text-slate-600">最终依据：{sources.length} 份来源</p><MaterialNames items={sources} empty="未记录引用来源" /></div>
      {records(turn.warnings).map((warning, index) => <p className="text-xs text-amber-800" key={index}>{word(warning.message)}</p>)}
    </Card>
    <p className={muted}>以上为运行记录的简化展示。完整字段、配置、证据和原始 JSON 保留在下方 MQ 明细。</p>
  </section>;
}
