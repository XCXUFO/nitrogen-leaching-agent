export interface ChatUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface Citation {
  index: number;
  chunk_id: string;
  source: string;
  score: number;
  snippet: string;
  title?: string | null;
  author_hint?: string | null;
  year?: string | null;
  document_id?: string | null;
  document_available?: boolean;
  content_version?: string | null;
  file_sha256?: string | null;
  char_start?: number | null;
  char_end?: number | null;
}

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  query: string;
  turn_id?: string;
  request_id?: string;
  rerun_of_run_id?: string;
  k?: number;
  session_id?: string;
  operator_id?: string;
  history?: ChatHistoryMessage[];
  file_id?: string;
  file_ids?: string[];
}

export interface ChatRunEvent {
  event_id: string;
  run_id: string;
  sequence: number;
  time: string;
  type: string;
  step_id?: string;
  name?: string;
  status: string;
  outcome?: string;
  summary?: string;
  kind?: "skill" | "tool" | "service" | "container";
  attempt_no?: number;
  parent_step_id?: string | null;
  subtask_ids?: string[];
}

export interface ChatRunView {
  protocol: "chat-runs-v1";
  run_id: string;
  turn_id: string;
  request_id: string;
  primary_run_id: string;
  rerun_of_run_id: string | null;
  status: "accepted" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted" | "unknown";
  outcome: string | null;
  events: ChatRunEvent[];
  last_sequence: number;
  result: ChatResponse | null;
  result_saved: boolean;
  error: { code: string; message: string; http_status: number } | null;
  expires_at?: number;
}

export interface SavedChatTurn {
  run_id: string;
  turn_id: string;
  request: { query: string; history: ChatHistoryMessage[]; attachments: FileReceipt[];
    turnId: string; requestId: string; rerunOfRunId?: string | null };
  status: ChatRunView["status"];
  response: ChatResponse | null;
  error: { code: string; message: string; http_status: number } | null;
  expires_at: number | null;
  recoverable: boolean;
}

export interface SavedConversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turns: SavedChatTurn[];
}

export interface AccountChatHistory {
  items: SavedConversation[];
  total: number;
}

export interface ChatResponse {
  case_route?: string[];
  case_match?: "matched" | "missing" | "text_only" | "unavailable" | null;
  case_gap_recorded?: boolean;
  case_references?: { id: string; title: string; source: string }[];
  answer: string;
  citations: Citation[];
  usage: ChatUsage;
  retrieved_count: number;
  model: string;
  route: "knowledge" | "file" | "clarification" | "direct" | "out_of_scope" | "composed";
  file_evidence: FileEvidence[];
  run_id: string | null;
  conversation_id: string | null;
  agent_route: "DIRECT" | "KNOWLEDGE" | "FILE_ANALYSIS" | "COMPOSED" | "CLARIFY" | "OUT_OF_SCOPE" | null;
  trace_saved: boolean;
  outcome: "complete" | "partial" | "clarification";
  attachment: AttachmentState | null;
  attachments?: AttachmentState[];
  sections: AnswerSection[];
  warnings: { code: string; message: string }[];
}

export interface AttachmentState {
  file_id?: string | null;
  filename: string;
  status: "pending" | "ready" | "invalid" | "expired";
  kind: string | null;
  rows: number | null;
}

export interface AnswerSection {
  kind: "file_observation" | "literature_inference" | "limitation";
  content: string;
  citation_indices: number[];
  file_evidence_indices: number[];
  evidence_ids: string[];
}

export interface FileReceipt {
  file_id: string;
  filename: string;
  kind: string | null;
  rows: number | null;
  status: "pending" | "ready" | "invalid";
  sha256: string;
  format: string;
  expires_in_seconds: number;
}

export interface SessionFile {
  clientId: string;
  filename: string;
  size: number;
  phase: "uploading" | "stored" | "error";
  progress: number;
  receipt: FileReceipt | null;
  used: boolean;
  hidden?: boolean;
  error?: string;
}

export interface FileEvidence {
  filename: string;
  sha256: string;
  sheet: string;
  field: string;
  unit: string;
  operation: "min" | "max";
  value: number;
  model_day: number;
  cell: string;
  day_cell: string;
  occurrences: number;
  data_range: string;
  tool_version: string;
  schema_id: string;
}

export interface BackendErrorDetail {
  code: string;
  message: string;
}
