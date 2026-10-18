import { accountHeaders, expireAccount, readAccount } from "./account-storage";
import type {
  BackendErrorDetail,
  AccountChatHistory,
  ChatHistoryMessage,
  ChatRequest,
  ChatResponse,
  ChatRunView,
  FileReceipt,
} from "./types";
import {
  NETWORK_FAILURE,
  UNKNOWN_FAILURE,
  translateErrorCode,
} from "./error-messages";

const RAW_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export const apiBaseUrl = RAW_BASE_URL.replace(/\/+$/, "");

let fallbackOperatorId: string | null = null;
function newOperatorId(): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID() : `${Date.now()}_${Math.random().toString(16).slice(2)}`;
  return `visitor_${random}`;
}
export function getOrCreateOperatorId(): string {
  if (fallbackOperatorId) return fallbackOperatorId;
  const key = "nitrogen_visitor_id";
  try {
    const existing = window.localStorage.getItem(key);
    if (existing && /^visitor_[A-Za-z0-9_-]{8,80}$/.test(existing)) return existing;
    const created = newOperatorId();
    window.localStorage.setItem(key, created);
    return created;
  } catch {
    fallbackOperatorId = newOperatorId();
    return fallbackOperatorId;
  }
}

export class ApiError extends Error {
  runId?: string;
  terminalRun = false;
  public readonly userMessage: string;
  constructor(
    public readonly code: string,
    public readonly httpStatus: number | null,
    userMessage: string,
    cause?: unknown,
  ) {
    const message = translateErrorCode(code, userMessage);
    super(message, { cause });
    this.userMessage = message;
    this.name = "ApiError";
  }
}

export interface ChatSubmission {
  turnId: string;
  requestId: string;
  rerunOfRunId?: string;
  resumeOnly?: boolean;
  onProgress?: (view: ChatRunView) => void;
  onConnectionChange?: (recovering: boolean) => void;
}

export async function getAccountChatHistory(offset = 0, signal?: AbortSignal): Promise<AccountChatHistory> {
  const auth = accountHeaders();
  const response = await fetch(`${apiBaseUrl}/api/chat/history?limit=30&offset=${offset}`, {
    headers: auth, credentials: "include", cache: "no-store", signal,
  });
  return readResponse<AccountChatHistory>(response, auth.Authorization?.slice(7));
}

const sessionBootstraps = new Map<string, Promise<boolean>>();
async function ensureChatSession(auth: Record<string, string>, signal?: AbortSignal): Promise<boolean> {
  signal?.throwIfAborted();
  const identity = auth.Authorization ?? "visitor";
  let pending = sessionBootstraps.get(identity);
  if (!pending) {
    const request = (async () => {
      let response: Response;
      try {
        response = await fetch(`${apiBaseUrl}/api/chat/session`, {
          credentials: "include", headers: auth, cache: "no-store", signal: AbortSignal.timeout(15_000),
        });
      } catch (err) {
        throw new ApiError("network", null, "连接暂不可用，请检查网络后用原提交重试。", err);
      }
      if (response.status === 404 || response.status === 405) return false;
      const session = await readResponse<{ protocol: string }>(response, auth.Authorization?.slice(7));
      if (session.protocol !== "chat-runs-v1") throw new ApiError("run_protocol", null, "会话恢复服务暂不可用，请稍后重试。");
      return true;
    })();
    sessionBootstraps.set(identity, request);
    const clear = () => { if (sessionBootstraps.get(identity) === request) sessionBootstraps.delete(identity); };
    void request.then(clear, clear);
    pending = request;
  }
  if (!signal) return pending;
  // A caller can stop waiting without cancelling another conversation's bootstrap.
  return new Promise((resolve, reject) => {
    const abort = () => { signal.removeEventListener("abort", abort); reject(signal.reason); };
    signal.addEventListener("abort", abort, { once: true });
    pending.then(value => { signal.removeEventListener("abort", abort); resolve(value); },
      error => { signal.removeEventListener("abort", abort); reject(error); });
  });
}

export async function postChat(
  query: string,
  history: ChatHistoryMessage[] = [],
  k?: number,
  signal?: AbortSignal,
  sessionId?: string,
  fileId?: string,
  operatorId?: string,
  fileIds?: string[],
  submission?: ChatSubmission,
): Promise<ChatResponse> {
  const body: ChatRequest = { query };
  if (history.length > 0) body.history = history;
  if (k !== undefined) body.k = k;
  if (sessionId !== undefined) body.session_id = sessionId;
  if (fileId !== undefined) body.file_id = fileId;
  if (fileIds !== undefined) body.file_ids = fileIds;
  if (operatorId !== undefined) body.operator_id = operatorId;

  const auth = accountHeaders();
  // Concurrent chats and uploads share initialization so their first responses
  // cannot replace each other's visitor identity.
  let recoverable = false;
  if (submission && sessionId) {
    try {
      recoverable = await ensureChatSession(auth, signal);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError("network", null, "连接暂不可用，请检查网络后用原提交重试。", err);
    }
    if (recoverable) {
      body.turn_id = submission.turnId;
      body.request_id = submission.requestId;
      if (submission.rerunOfRunId) body.rerun_of_run_id = submission.rerunOfRunId;
    }
  }
  if (recoverable && submission) return submitRecoverable(body, auth, submission, signal);
  if (submission?.resumeOnly) throw new ApiError("run_recovery_unavailable", 409, "当前服务不支持恢复原提交，请确认后手动重试。");
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/chat`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...auth },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    throw new ApiError("network", null, NETWORK_FAILURE, err);
  }

  if (response.ok) {
    return (await response.json()) as ChatResponse;
  }

  return readResponse<ChatResponse>(response, auth.Authorization?.slice(7));
}

async function submitRecoverable(body: ChatRequest, auth: Record<string, string>, submission: ChatSubmission, signal?: AbortSignal): Promise<ChatResponse> {
  let snapshot: ChatRunView | undefined;
  let failures = 0;
  let posted = false;
  const deadline = Date.now() + 6 * 60_000;
  const accept = (value: ChatRunView) => {
    if (value.protocol !== "chat-runs-v1" || value.request_id !== body.request_id || value.turn_id !== body.turn_id
      || (snapshot && value.run_id !== snapshot.run_id)) {
      throw new ApiError("run_protocol", null, "运行回执无法核对，请用原提交重试。");
    }
    const events = new Map(snapshot?.events.map(event => [event.sequence, event]));
    for (const event of value.events) events.set(event.sequence, event);
    snapshot = { ...value, events: [...events.values()].sort((a, b) => a.sequence - b.sequence) };
    submission.onProgress?.(snapshot);
    submission.onConnectionChange?.(false);
  };
  const request = (url: string, options?: RequestInit) => fetch(`${apiBaseUrl}${url}`, {
    credentials: "include", cache: "no-store", headers: { "Content-Type": "application/json", ...auth },
    signal: signal ?? AbortSignal.timeout(15_000), ...options,
  });
  while (Date.now() < deadline) {
    try {
      if (!snapshot) {
        // Lookup first, including after a manual network retry. A missing owned
        // receipt permits only the exact same idempotent submission to be sent.
        const lookup = await request(`/api/chat/requests/${encodeURIComponent(body.request_id!)}?session_id=${encodeURIComponent(body.session_id!)}`);
        if (lookup.status === 404 && submission.resumeOnly) throw new ApiError("request_not_found", 404, "未找到原提交的受理记录，尚未自动执行。点击重试可继续原提交。");
        if (lookup.status === 404 && !posted) {
          posted = true;
          const response = await request("/api/chat", { method: "POST", body: JSON.stringify(body) });
          if (response.ok && response.status !== 202) return readResponse<ChatResponse>(response);
          accept(await readResponse<ChatRunView>(response, auth.Authorization?.slice(7)));
        } else {
          // A lost POST may not have arrived. Resubmit on the next pass with the
          // same IDs; the server's durable uniqueness constraint decides admission.
          if (lookup.status === 404) { posted = false; throw new Error("acceptance not yet found"); }
          accept(await readResponse<ChatRunView>(lookup, auth.Authorization?.slice(7)));
        }
      } else {
        accept(await readResponse<ChatRunView>(await request(`/api/chat/runs/${encodeURIComponent(snapshot.run_id)}?after=${snapshot.last_sequence}`), auth.Authorization?.slice(7)));
      }
      failures = 0;
    } catch (err) {
      if (err instanceof ApiError && err.httpStatus !== null && err.httpStatus < 500) throw err;
      if (signal?.aborted) throw err;
      submission.onConnectionChange?.(true);
      if (++failures >= 5) throw new ApiError("run_recovery_unavailable", null, "连接暂时中断，执行可能仍在继续。点击重试会找回原运行。", err);
      await new Promise(resolve => setTimeout(resolve, 1000));
      continue;
    }
    const current = snapshot as ChatRunView | undefined;
    if (current && current.status !== "accepted" && current.status !== "running") {
      if (current.result) return current.result;
      const problem = new ApiError(current.error?.code ?? `run_${current.status}`, current.error?.http_status ?? null,
        current.error?.message ?? "原运行已结束，未获得可恢复的结果。再次重试将创建新运行。");
      problem.runId = current.run_id;
      problem.terminalRun = true;
      throw problem;
    }
    await new Promise(resolve => setTimeout(resolve, 700));
  }
  throw new ApiError("run_pending", null, "本次等待已结束，执行可能仍在继续。点击重试查询原运行。");
}

export async function uploadFile(file: File, onProgress?: (percent: number) => void, sessionId?: string): Promise<FileReceipt> {
  if (!/\.(?:xls|xlsx|txt|md|pdf|doc|docx)$/i.test(file.name)) {
    throw new ApiError("unsupported_file", null, "支持 .xls、.xlsx、.txt、.md、.pdf、.doc、.docx 文件。");
  }
  if (file.size > 10 * 1024 * 1024) {
    throw new ApiError("file_too_large", null, "文件不能超过 10 MiB。");
  }
  const account = readAccount();
  if (sessionId) await ensureChatSession(account ? { Authorization: `Bearer ${account.token}` } : {});
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.withCredentials = true;
    const params = new URLSearchParams({ filename: file.name });
    if (sessionId) params.set("session_id", sessionId);
    xhr.open("POST", `${apiBaseUrl}/api/files?${params}`);
    if (account) xhr.setRequestHeader("Authorization", `Bearer ${account.token}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream"); xhr.timeout = 60000;
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress?.(Math.round(event.loaded / event.total * 100)); };
    xhr.onerror = () => reject(new ApiError("network", null, NETWORK_FAILURE));
    xhr.ontimeout = () => reject(new ApiError("upload_timeout", null, "上传超时，请检查连接后重新上传。"));
    xhr.onabort = () => reject(new ApiError("upload_cancelled", null, "上传已取消。"));
    xhr.onload = () => {
      if (!xhr.status) { reject(new ApiError("network", null, NETWORK_FAILURE)); return; }
      readResponse<FileReceipt>(new Response(xhr.responseText, { status: xhr.status }), account?.token).then(resolve, reject);
    };
    xhr.send(file);
  });
}

export async function checkSessionFiles(fileIds: string[], sessionId?: string): Promise<{ files: { file_id: string; status: "available" | "expired" }[] }> {
  const auth = accountHeaders();
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/files/status`, {
      method: "POST", credentials: "include", cache: "no-store",
      headers: { "Content-Type": "application/json", ...auth }, body: JSON.stringify({ file_ids: fileIds, session_id: sessionId }),
    });
  } catch (err) { throw new ApiError("network", null, NETWORK_FAILURE, err); }
  return readResponse(response, auth.Authorization?.slice(7));
}

export async function releaseSessionFiles(fileIds: string[], sessionId: string, onPageHide = false): Promise<void> {
  if (!fileIds.length) return;
  const url = `${apiBaseUrl}/api/files/release`;
  const body = JSON.stringify({ file_ids: fileIds, session_id: sessionId });
  if (onPageHide && !readAccount() && navigator.sendBeacon?.(url, new Blob([body], { type: "application/json" }))) return;
  try {
    await fetch(url, { method: "POST", credentials: "include", keepalive: onPageHide,
      headers: { "Content-Type": "application/json", ...accountHeaders() }, body });
  } catch { /* A failed cleanup is bounded by the server lease. */ }
}

async function readResponse<T>(response: Response, token?: string): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  if (response.status === 401 && token) expireAccount(token);
  const data = (await safeJson(response)) as
    | { detail?: BackendErrorDetail | string | Array<{ msg?: string }> }
    | null;
  if (response.status === 422 && Array.isArray(data?.detail)) {
    const msg = data?.detail?.[0]?.msg ?? "输入校验失败";
    throw new ApiError("validation_error", 422, `输入校验失败：${msg}`);
  }

  if (
    data &&
    typeof data.detail === "object" &&
    data.detail !== null &&
    !Array.isArray(data.detail) &&
    typeof data.detail.code === "string"
  ) {
    throw new ApiError(
      data.detail.code,
      response.status,
      ["case_capacity", "case_library_unavailable", "case_ai_unavailable", "case_answer_invalid", "public_demo_limit", "public_origin_denied", "invalid_result_file", "invalid_document", "too_many_files", "file_too_large", "unsupported_file", "file_not_found", "file_store_full", "file_tools_unavailable"].includes(data.detail.code)
        ? data.detail.message : translateErrorCode(data.detail.code),
    );
  }

  throw new ApiError("unknown", response.status, UNKNOWN_FAILURE);
}

export async function getHealth(signal?: AbortSignal): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/health`, { signal });
  } catch (err) {
    throw new ApiError("network", null, NETWORK_FAILURE, err);
  }
  if (!response.ok) {
    throw new ApiError("unknown", response.status, UNKNOWN_FAILURE);
  }
  return response.json();
}

async function safeJson(r: Response): Promise<unknown | null> {
  try {
    return await r.json();
  } catch {
    return null;
  }
}
