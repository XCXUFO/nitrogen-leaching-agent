import { notFound } from "next/navigation";
import { EvaluationWorkspace } from "@/components/evaluation-workspace";
import { evaluationModules } from "@/lib/evaluation-navigation";

export default async function Page({ params, searchParams }: {
  params: Promise<{ path: string[] }>;
  searchParams: Promise<{ execution?: string; case?: string }>;
}) {
  const raw = (await params).path;
  let path: string[];
  try { path = raw.map((part) => decodeURIComponent(part)); } catch { notFound(); }
  const currentModule = evaluationModules.find((item) => item.key === path[0]);
  if (!currentModule || path.length > 2) notFound();
  const query = await searchParams;
  return <EvaluationWorkspace key={`${path.join("/")}:${query.execution ?? ""}:${query.case ?? ""}`} section={currentModule.key} detail={path[1] ?? ""}
    executionId={typeof query.execution === "string" ? query.execution : ""} caseId={typeof query.case === "string" ? query.case : ""} />;
}
