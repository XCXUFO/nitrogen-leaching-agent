import { CaseLibraryWorkspace } from "@/components/case-library-workspace";
import { notFound } from "next/navigation";
import { EvaluationWorkspace } from "@/components/evaluation-workspace";
import { LiteratureWorkspace } from "@/components/literature-workspace";
import { evaluationModules } from "@/lib/evaluation-navigation";

export default async function Page({ params, searchParams }: {
  params: Promise<{ path: string[] }>;
  searchParams: Promise<{ execution?: string; case?: string; tag?: string; edit?: string }>;
}) {
  const raw = (await params).path;
  let path: string[];
  try { path = raw.map((part) => decodeURIComponent(part)); } catch { notFound(); }
  const currentModule = evaluationModules.find((item) => item.key === path[0]);
  if (!currentModule || path.length > 2) notFound();
  const query = await searchParams;
  if (currentModule.key === "case-library") return <CaseLibraryWorkspace key={`${path[1] ?? ""}:${query.edit ?? ""}`} detail={path[1] ?? ""} edit={query.edit === "1"} />;
  if (currentModule.key === "literature" || currentModule.key === "literature-tags") return <LiteratureWorkspace key={`${currentModule.key}:${path[1] ?? ""}:${query.edit ?? ""}`} section={currentModule.key} detail={path[1] ?? ""} tagId={typeof query.tag === "string" ? query.tag : ""} edit={query.edit === "1"} />;
  return <EvaluationWorkspace key={`${path.join("/")}:${query.execution ?? ""}:${query.case ?? ""}`} section={currentModule.key} detail={path[1] ?? ""}
    executionId={typeof query.execution === "string" ? query.execution : ""} caseId={typeof query.case === "string" ? query.case : ""} />;
}
