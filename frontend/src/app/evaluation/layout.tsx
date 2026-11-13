import { EvaluationShell } from "@/components/evaluation-shell";
import "./workbench.css";

export const metadata = { title: "评测管理工作台 · 农业模型助手" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return <EvaluationShell>{children}</EvaluationShell>;
}
