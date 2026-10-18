import { notFound } from "next/navigation";
import { DemoWorkspace } from "@/components/demo-workspace";
import { evaluationModules } from "@/lib/evaluation-navigation";

export const metadata = { title: "评测后台展示 · 农业模型助手" };
const modules: string[] = evaluationModules.map((item) => item.key);

export default async function Page({ params }: { params: Promise<{ path?: string[] }> }) {
  const path = (await params).path ?? [];
  if (path.length > 2 || (path[0] && !modules.includes(path[0]))) notFound();
  if (["literature-tags", "starred-questions"].includes(path[0]) && path[1]) notFound();
  return <DemoWorkspace key={path.join("/")} section={path[0] ?? "overview"} detail={path[1] ?? ""} />;
}
