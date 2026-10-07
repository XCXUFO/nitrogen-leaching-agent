import { apiBaseUrl } from "./api";
import type { AttachmentState, ChatResponse } from "./types";

export type Evaluator = { tester_id: string; role: "tester" | "developer" | "reviewer" };
export type EvaluationCase = {
  professional_review: "pending" | "domain_expert_reviewed";
  professional_outcome?: "pass" | "partial" | "fail" | "blocked" | null;
  ai_assisted_review_count?: number;
  domain_expert_review_count?: number;
  dataset_id: string;
  fixtures: { filename: string; sha256: string | null }[];
  case: { case_id: string; version: number; category: string; priority: string; source: string;
    supersedes?: string | null; title: string; preconditions: string;
    expected: string[]; attachment_requirements: string[];
    steps: { action: string; instruction: string; input?: string | null; attachment?: string | null }[] };
};
export type EvaluationEvent = {
  sequence: number; action: string; created_at: string; run_id: string | null;
  input?: string; note?: string; attachment?: { filename: string; status: string; sha256: string };
  response?: ChatResponse; error?: { code: string; http_status: number; message?: string }; trace_missing?: boolean;
};
export type ExecutionSummary = {
  execution_id: string; case_id: string; case_version: number; tester_id: string;
  created_at: string; status: "open" | "reviewed"; task_id?: string | null;
};
export type EvaluationExecution = ExecutionSummary & {
  automation_running?: boolean;
  needs_reset: boolean; attachment: AttachmentState | null; events: EvaluationEvent[];
  review: Record<string, unknown> | null;
};
export type LayerCount = { denominator: number; yes: number; partial: number; no: number };
export type EvaluationStats = {
  executions: number; pending: number; reviewed: number;
  assessment_counts?: { ai_assisted: number; domain_expert: number };
  overall: Record<string, number>; layers: Record<string, LayerCount>;
  by_case_version: { case_id: string; case_version: number; reviewed: number; overall: Record<string, number> }[];
};
export type RunSummary = {
  run_id: string; input: string; started_at: string; status: string; outcome: string | null;
  latency_ms: number; config_version: string; error_code: string | null;
};
export type SessionSummary = {
  session_id: string; topic: string; created_at: string; operator_id: string;
  status: "正常" | "异常"; latency_ms: number; turn_count: number;
};
export type SessionTrace = {
  run_id: string; started_at: string; input: string; answer: string | null;
  history_count?: number;
  status: string; outcome: string | null; latency_ms: number; error_code: string | null;
  decision?: { route?: string; reason_code?: string } | null;
  tool_calls?: { skill: string; status: string; latency_ms: number; error_code?: string | null }[];
  state_before?: Record<string, unknown>; state_after?: Record<string, unknown> | null;
  evidence?: unknown[]; sections?: unknown[]; warnings?: unknown[];
  config_version?: string; config_manifest?: unknown;
};
export type SessionDetail = SessionSummary & { turns: SessionTrace[] };

export async function evaluationRequest<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/eval${path}`, {
      ...init, cache: "no-store",
      headers: { ...init.headers, Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new Error("无法连接评测服务，请检查后端是否启动。");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (Array.isArray(data?.detail)) throw new Error(`输入不完整或不符合评分规则：${data.detail[0]?.msg ?? "请检查表单"}`);
    throw new Error(data?.detail?.message ?? `评测请求失败（${response.status}）`);
  }
  return data as T;
}

export function evaluationJson(value: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) };
}
