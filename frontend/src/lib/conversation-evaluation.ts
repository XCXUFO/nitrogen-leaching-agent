import { evaluationJson, evaluationRequest } from './evaluation-api';
import type { ChatResponse } from './types';

export type ConversationCase = {
  case_id: string; source_session_id: string; title: string; expected: string; notes: string; revision: number;
  seed_history: { role: string; content: string }[];
  turns: { query: string; source_run_id: string; baseline_answer: string | null; baseline_status: string;
    baseline_config: string; attachments: { filename: string; sha256?: string }[] }[];
  versions?: CaseVersion[];
};
export type CaseGroup = { group_id: string; title: string; notes: string; case_count: number; turn_count: number; cases?: ConversationCase[] };
export type CaseResult = { case: ConversationCase; session_id: string; status: string; error?: string;
  judgment?: { conclusion: string; note: string; actor: string; at: string };
  turns: { query: string; run_id: string; status: string; response?: ChatResponse; config_version?: string }[] };
export type CaseVersion = { batch_id: string; version_name: string; config_version: string; created_at: string; result: CaseResult };
export type ConversationBatch = { batch_id: string; group_ids: string[]; group_titles: string[]; version_name: string;
  config_version: string; created_at: string; status: string; acceptance: string; case_count: number; completed_cases: number;
  source_session_ids?: string[]; cases?: ConversationCase[]; results?: CaseResult[] };
export type ConversationIssue = { issue_id: string; session_id: string; run_id: string; source: string; note: string;
  status: string; category: string; assignee: string; revision: number; created_at: string; created_by: string;
  history: { actor?: string; at: string; status?: string; note: string }[];
  cases: { case_id: string; title: string }[]; groups: CaseGroup[]; legacy_id?: string; verification_batch_id?: string };
export const statusLabels: Record<string, string> = { queued: '等待运行', running: '正在运行', completed: '运行结束',
  succeeded: '运行成功', failed: '运行失败', blocked: '受阻', cancelled: '已取消', interrupted: '已中断',
  pending: '待验收', pass: '验收通过', fail: '验收不通过', open: '待处理', in_progress: '处理中', ready_for_retest: '待验证', closed: '已解决' };
export function conversationApi<T>(token: string, path: string, data?: unknown, method = 'POST'): Promise<T> {
  return evaluationRequest<T>(token, path, data === undefined ? {} : { ...evaluationJson(data), method });
}
