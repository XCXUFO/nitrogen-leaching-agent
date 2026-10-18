export type Ratio = { numerator: number; denominator: number; rate: number | null };
type StepMetrics = {
  success: Ratio;
  attempt_failure: Ratio;
  retrieval_no_result: Ratio;
  excluded: Record<string, number>;
  observed_steps: number;
};

export type OnlineMetrics = {
  metric_version: string;
  updated_at: string;
  unit: "session";
  filters: Record<string, string>;
  sessions: number;
  session_states: Record<string, number>;
  multi_turn: Ratio;
  mean_turns: number | null;
  turn_distribution: { turns: number; sessions: number }[];
  recent_sessions: { session_id: string; run_id: string | null; topic: string; created_at: string; turns: number; status: string; trace_missing: number }[];
  questions: number;
  reruns: { attempts: number; succeeded: number; recovered_failed_primary: number; sessions: number };
  states: Record<string, number>;
  steps: Record<"tool" | "skill" | "service", StepMetrics>;
  trace_missing: number;
  by_task: Record<string, number>;
  by_skill: { skill: string; calls: number; failures: number; runs: number; sessions: number; mean_latency_ms: number }[];
  daily: { date: string; sessions: number; abnormal_sessions: number; turns: number }[];
};

export const ratioLabel = (value: Ratio) => value.denominator
  ? `${(100 * value.numerator / value.denominator).toFixed(1)}%（${value.numerator}/${value.denominator}）`
  : "暂无可计算样本（0/0）";
