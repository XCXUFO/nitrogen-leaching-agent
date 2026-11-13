import { CaseLibraryWorkspace } from "@/components/case-library-workspace";
import { notFound, redirect } from "next/navigation";
import { EvaluationWorkspace } from "@/components/evaluation-workspace";
import { LiteratureWorkspace } from "@/components/literature-workspace";
import { StarredQuestions } from "@/components/starred-questions";
import { SkillWorkspace } from "@/components/skill-workspace";
import { OnlineEffects } from "@/components/online-effects";
import { ExplanationTrials } from "@/components/explanation-trials";
import { RunReviewWorkspace } from "@/components/run-review-workspace";
import { conversationCaseHref, evaluationHref, evaluationModules } from "@/lib/evaluation-navigation";
import { ConversationCaseWorkspace, ConversationCasesWorkspace, ConversationVersionsWorkspace, ConversationIssuesWorkspace } from "@/components/conversation-cases";

export default async function Page({ params, searchParams }: {
  params: Promise<{ path: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = (await params).path;
  let path: string[];
  try { path = raw.map((part) => decodeURIComponent(part)); } catch { notFound(); }
  const caseDetail = path[0] === 'case-groups' && (
    (path.length === 3 && path[1] === 'cases') ||
    (path.length === 4 && !['cases', 'versions'].includes(path[1]) && path[2] === 'cases')
  );
  if (path.length > 2 && !caseDetail) notFound();
  if (path[0] === "formal-reviews") redirect(evaluationHref("runs", path[1]));
  const currentModule = evaluationModules.find((item) => item.key === path[0]);
  if (!currentModule) notFound();
  const query = await searchParams;
  if (currentModule.key === 'case-groups') {
    if (caseDetail) return <ConversationCaseWorkspace caseId={path[path.length - 1]} />;
    const initialCase = typeof query.case === 'string' ? query.case : '';
    const initialBatch = typeof query.batch === 'string' ? query.batch : '';
    const initialGroup = typeof query.group === 'string' ? query.group : '';
    if (path[1] === 'versions') return <ConversationVersionsWorkspace key={`versions:${initialGroup}:${initialCase}:${initialBatch}`} initialGroup={initialGroup} initialCase={initialCase} initialBatch={initialBatch} />;
    if (initialBatch) {
      const legacyQuery = new URLSearchParams({ batch: initialBatch });
      if (initialCase) legacyQuery.set('case', initialCase);
      if (path[1]) legacyQuery.set('group', path[1]);
      redirect(`${evaluationHref('case-groups', 'versions')}?${legacyQuery}`);
    }
    if (initialCase) redirect(conversationCaseHref(initialCase, path[1]));
    return <ConversationCasesWorkspace key={path[1] ?? 'list'} detail={path[1]} />;
  }
  if (currentModule.key === 'issues') return <ConversationIssuesWorkspace key={path[1] ?? 'list'} detail={path[1]} />;
  if (currentModule.key === "runs" || currentModule.key === "overview") {
    const serialized = new URLSearchParams(Object.entries(query).flatMap(([key, value]) => typeof value === "string" ? [[key, value]] : [])).toString();
    return <RunReviewWorkspace key={`${path[1] ?? "list"}:${serialized}`} detail={path[1] ?? ""} query={serialized} />;
  }
  if (currentModule.key === "explanation-trials" && !path[1]) return <ExplanationTrials sourceRun={typeof query.source_run === "string" ? query.source_run : ""} />;
  if (currentModule.key === "online-effects") {
    if (path[1]) notFound();
    const serialized = new URLSearchParams(Object.entries(query).flatMap(([key, value]) => typeof value === "string" ? [[key, value]] : [])).toString();
    return <OnlineEffects key={serialized} query={serialized} />;
  }
  if (currentModule.key === "skills") return <SkillWorkspace key={path[1] ?? "list"} detail={path[1] ?? ""} />;
  if (currentModule.key === "case-library") return <CaseLibraryWorkspace key={`${path[1] ?? ""}:${query.edit ?? ""}:${query.tag ?? ""}`} detail={path[1] ?? ""} edit={query.edit === "1"} tagId={typeof query.tag === "string" ? query.tag : ""} />;
  if (currentModule.key === "starred-questions" && !path[1]) return <StarredQuestions />;
  if (currentModule.key === "literature" || currentModule.key === "literature-tags") return <LiteratureWorkspace key={`${currentModule.key}:${path[1] ?? ""}:${query.edit ?? ""}`} section={currentModule.key} detail={path[1] ?? ""} tagId={typeof query.tag === "string" ? query.tag : ""} edit={query.edit === "1"} />;
  return <EvaluationWorkspace key={`${path.join("/")}:${query.execution ?? ""}:${query.case ?? ""}`} section={currentModule.key} detail={path[1] ?? ""}
    executionId={typeof query.execution === "string" ? query.execution : ""} caseId={typeof query.case === "string" ? query.case : ""} />;
}
