import type { SessionTrace } from "./evaluation-api";

export type Data = Record<string, unknown>;
export const object = (value: unknown): Data => value && typeof value === "object" && !Array.isArray(value) ? value as Data : {};
export const records = (value: unknown): Data[] => Array.isArray(value) ? value.map(object) : [];
export const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
export const word = (value: unknown): string => typeof value === "string" ? value : "";
export const unique = <T,>(items: T[]) => [...new Set(items)];

export const skillNames: Record<string, string> = {
  knowledge_search: "文献知识检索", concept_explanation: "概念解释", case_assistant: "案例与措施助手",
  case_reference: "案例参考", case_explanation: "案例解释", whcns_analyzer: "WHCNS 数据分析",
  file_inspector: "文件检查", clarification: "澄清问题", capability_guidance: "能力说明",
};
export const skillName = (name: string) => skillNames[name] || name || "未记录 Skill";
export const statusName = (status: unknown) => ({ ok: "成功", succeeded: "成功", error: "失败", failed: "失败", cancelled: "已取消", running: "处理中", clarification: "需要澄清", complete: "完成", partial: "部分完成" }[word(status)] || word(status) || "未记录");

export type RecallPath = { route: string; rank?: number };
export function recallPaths(value: unknown): RecallPath[] {
  if (!Array.isArray(value)) return [];
  const paths = value.flatMap((item): RecallPath[] => {
    if (typeof item === "string") return item ? [{ route: item }] : [];
    const path = object(item);
    if (!word(path.route)) return [];
    return [{ route: word(path.route), rank: typeof path.rank === "number" && Number.isFinite(path.rank) && path.rank > 0 ? path.rank : undefined }];
  });
  return [...new Map(paths.map((path) => [`${path.route}:${path.rank ?? ""}`, path])).values()];
}

export type Material = { key: string; chunk: string; title: string; href?: string; rank?: number; score?: number; selected?: boolean; reason: string; paths: RecallPath[] };
export type RetrievalView = {
  id: string; citationUnknown: Material[];
  kind: string; query: string; skill: string; tasks: string[]; candidates: Material[]; ranked: Material[];
  supplied: Material[]; cited: Material[]; hasRanking: boolean; hasContext: boolean; semantic: Data[]; pipeline: Data;
};

export function material(value: Data, kind: string, known: Data[] = []): Material {
  const chunk = word(value.chunk_id) || word(value.id) || word(value.source_id);
  const evidence = known.find((item) => word(item.source_id) === chunk);
  const provenance = object(evidence?.provenance);
  const source = word(value.source) || word(provenance.source);
  const paper = word(value.paper_id) || word(value.document_id) || word(provenance.paper_id)
    || /^managed:\/\/([^/]+)\//.exec(source)?.[1] || "";
  const caseId = kind === "case" ? word(value.id) || word(value.source_id) : "";
  return {
    key: kind === "starred" || kind === "file" ? chunk : caseId || paper || source || chunk,
    chunk, title: word(value.title) || word(provenance.title) || word(provenance.filename) || source.split(/[\\/]/).at(-1) || chunk || "来源未记录",
    href: caseId ? `/evaluation/case-library/${encodeURIComponent(caseId)}` : paper ? `/evaluation/literature/${encodeURIComponent(paper)}` : undefined,
    rank: typeof value.rank === "number" ? value.rank : undefined,
    score: typeof value.score === "number" ? value.score : undefined,
    selected: typeof value.selected === "boolean" ? value.selected : undefined,
    reason: word(value.reason), paths: recallPaths(value.recall_paths),
  };
}

export function documents(items: Material[]): Material[] {
  const found = new Map<string, Material>();
  for (const item of items) {
    const old = found.get(item.key);
    if (!old) found.set(item.key, item);
    else found.set(item.key, { ...old, href: old.href || item.href, paths: recallPaths([...old.paths, ...item.paths]) });
  }
  return [...found.values()];
}

export function retrievalViews(turn: SessionTrace): RetrievalView[] {
  const evidence = records(turn.evidence);
  const groups: { selection: Data; context?: Data }[] = [];
  for (const record of records(turn.retrieval)) {
    if (record.stage === "model_context") {
      const group = [...groups].reverse().find((item) => record.retrieval_id
        ? item.selection.retrieval_id === record.retrieval_id
        : !item.context && item.selection.source_type === record.source_type);
      if (group) group.context = record;
      else groups.push({ selection: { source_type: record.source_type, retrieval_id: record.retrieval_id }, context: record });
    } else groups.push({ selection: record });
  }
  const views: RetrievalView[] = groups.map(({ selection, context }) => {
    const kind = word(selection.source_type) || "literature";
    const semantic = records(object(selection.semantic).rounds);
    const raw = [...records(selection.candidates), ...semantic.flatMap((round) => records(round.recall || round.returned))];
    const merged = new Map<string, Data>();
    for (const item of raw) {
      const key = word(item.chunk_id) || word(item.id);
      if (key) merged.set(key, { ...item, ...merged.get(key), ...Object.fromEntries(Object.entries(item).filter(([, v]) => v != null)) });
    }
    const candidates = [...merged.values()].map((item) => material(item, kind, evidence));
    const find = (id: string) => candidates.find((item) => item.chunk === id) || material({ chunk_id: id }, kind, evidence);
    const ranked = Array.isArray(selection.ranked_candidates) ? records(selection.ranked_candidates).map((item) => material(item, kind, evidence)) : candidates.filter((item) => item.selected);
    const supplied = Array.isArray(context?.supplied_candidates) ? records(context?.supplied_candidates).map((item) => material(item, kind, evidence))
      : strings(context?.adopted_chunk_ids || selection.adopted_case_ids).map(find);
    return { id: word(selection.retrieval_id), citationUnknown: [], kind, query: word(selection.query), skill: word(selection.skill), tasks: strings(selection.subtask_ids),
      candidates, ranked, supplied, cited: [], hasRanking: Array.isArray(selection.ranked_candidates),
      hasContext: !!context || Array.isArray(selection.adopted_case_ids), semantic, pipeline: object(selection.pipeline) };
  });
  const eligible = views.map((view) => view.hasContext ? view.supplied : view.ranked.filter((entry) => entry.selected !== false));
  for (const item of evidence) {
    const source = material(item, word(item.source_type), evidence);
    const chunks = unique([source.chunk, ...strings(item.chunk_ids)]).filter(Boolean);
    const origins = strings(item.retrieval_ids);
    // Candidates alone do not prove use. Older traces can only be attributed
    // when an exact supplied fragment has one possible retrieval origin.
    const possible = views.flatMap((view, index) => view.kind === item.source_type
      && eligible[index].some((entry) => chunks.includes(entry.chunk) || entry.key === source.key) ? [index] : []);
    if (origins.length) {
      for (const index of possible) if (views[index].id && origins.includes(views[index].id)) views[index].cited.push(source);
    } else if (possible.length === 1 && eligible[possible[0]].some((entry) => chunks.includes(entry.chunk))) {
      views[possible[0]].cited.push(source);
    } else {
      for (const index of possible) views[index].citationUnknown.push(source);
    }
  }
  return views;
}

export function keywordsView(turn: SessionTrace) {
  const understanding = object(turn.understanding);
  const mapping = object(turn.tag_mapping);
  const mappings = records(mapping.mappings);
  const concepts = records(understanding.concepts);
  const scoped = object(turn.execution_context);
  const scopedKeywords = strings(scoped.keywords);
  const hasStarred = records(object(turn.starred_match).adopted).length > 0;
  const keywords = unique([...strings(understanding.keywords), ...concepts.map((item) => word(item.canonical) || word(item.original)),
    ...mappings.map((item) => word(item.canonical) || word(item.term))]).filter(Boolean);
  const rows = keywords.map((keyword) => {
    const original = concepts.filter((item) => item.canonical === keyword).map((item) => word(item.original));
    const matches = mappings.filter((item) => item.canonical === keyword || item.term === keyword || original.includes(word(item.term)));
    return { keyword, matches, tags: matches.flatMap((item) => records(item.candidates)),
      coveredByStarred: hasStarred && Array.isArray(scoped.keywords) && !scopedKeywords.includes(keyword) && !matches.length,
      ambiguous: matches.some((item) => item.status === "ambiguous" || item.requires_resolution === true) };
  });
  return { rows, mapping, matched: rows.filter((row) => row.tags.length && !row.ambiguous).length,
    ambiguous: rows.filter((row) => row.ambiguous).length,
    tagCount: unique(rows.filter((row) => !row.ambiguous).flatMap((row) => row.tags.map((tag) => word(tag.id) || word(tag.path)))).length };
}

export function executionView(turn: SessionTrace) {
  const events = records(turn.execution_steps);
  const steps = new Map<string, Data>();
  for (const event of events) {
    if (event.type !== "step_started" && event.type !== "step_finished") continue;
    const key = `${word(event.step_id)}:${event.attempt_no || 1}`;
    const previous = steps.get(key);
    steps.set(key, { ...previous, ...event, started_at: previous?.started_at || (event.type === "step_started" ? event.time : undefined) });
  }
  if (steps.size) return [...steps.values()];
  return (turn.tool_calls || []).map((call, index) => ({ ...call, kind: "skill", name: skillName(call.skill), step_id: `legacy:${index}` }));
}

export function outputView(turn: SessionTrace) {
  if ((turn.status === "error" || turn.status === "cancelled") && !turn.answer) return {
    title: "未生成最终回答", detail: turn.status === "cancelled" ? "本轮运行已取消，已执行步骤仍保留。" : `本轮运行失败${turn.error_code ? `：${turn.error_code}` : ""}。`, combined: false,
  };
  if (turn.outcome === "clarification") return { title: "需要补充条件", detail: "本轮返回澄清提示，等待补充信息后继续。", combined: false };
  const assembly = object(turn.answer_assembly);
  const starred = object(turn.starred_match);
  const adopted = records(starred.adopted);
  const kinds = unique(records(turn.sections).map((section) => word(section.kind)));
  const mode = word(assembly.mode) || (adopted.length && starred.continuation ? "starred_plus_continuation"
    : adopted.length && starred.status === "full" ? "starred_only"
    : kinds.includes("file_observation") && kinds.includes("literature_inference") ? "file_plus_literature" : "");
  if (mode === "starred_plus_continuation") return { title: "组合输出", detail: "已有星标答复 + 剩余问题的处理结果", combined: true };
  if (mode === "starred_only") return { title: "复用星标答复", detail: "星标问答已覆盖本轮需求，跳过后续检索和生成。", combined: false };
  if (mode === "file_plus_literature") return { title: "组合输出", detail: "文件计算结果 + 文献机理说明，按段落组织。", combined: true };
  if (mode === "single") return { title: "单路输出", detail: kinds.includes("file_observation") ? "输出文件分析结果；未记录文献说明段落。" : "由本轮能力生成回答，可综合多份资料。", combined: false };
  if (turn.decision?.route === "COMPOSED") return { title: "组合任务", detail: "历史记录缺少实际输出组成，无法确认是否完成组合。", combined: false };
  return { title: "输出组成未记录", detail: "可在下方查看实际调用、答案段落及完整运行记录。", combined: false };
}
