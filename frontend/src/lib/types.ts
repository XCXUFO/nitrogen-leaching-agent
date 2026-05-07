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
}

export interface ChatRequest {
  query: string;
  k?: number;
  session_id?: string;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  usage: ChatUsage;
  retrieved_count: number;
  model: string;
}

export interface BackendErrorDetail {
  code: string;
  message: string;
}
