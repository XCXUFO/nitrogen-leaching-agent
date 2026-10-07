const MESSAGES: Record<string, string> = {
  rag_not_configured:
    "后端检索服务未启用，请联系管理员开启 RAG_ENABLED 并完成索引。",
  rag_query_failed: "检索过程出错，请稍后重试或检查向量库索引是否完整。",
  llm_unreachable: "无法连接到大模型服务，请检查网络后重试。",
  llm_timeout: "大模型响应超时（可能在排队或网络拥塞），请稍后重试。",
  llm_rate_limited: "请求过于频繁，请稍后重试。",
  llm_upstream_error: "大模型服务暂时不可用，请稍后重试。",
  llm_auth_failed: "大模型 API key 配置异常，请联系管理员。",
  internal_error: "服务内部异常，请稍后重试。",
  conversation_busy: "当前对话仍有请求正在处理，请等待完成后再发送。",
  conversation_capacity: "当前对话数量已达上限，请稍后重试。",
  file_analysis_failed: "文件分析暂时失败，请稍后重试。",
};

export const NETWORK_FAILURE =
  "请求未发出，请检查后端是否启动（http://localhost:8000）。";

export const UNKNOWN_FAILURE = "请求失败，请稍后重试或查看浏览器控制台。";

export function translateErrorCode(code: string): string {
  return MESSAGES[code] ?? UNKNOWN_FAILURE;
}
