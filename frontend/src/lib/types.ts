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
}

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  query: string;
  k?: number;
  session_id?: string;
  operator_id?: string;
  history?: ChatHistoryMessage[];
  file_id?: string;
  file_ids?: string[];
}

export interface ChatResponse {
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
