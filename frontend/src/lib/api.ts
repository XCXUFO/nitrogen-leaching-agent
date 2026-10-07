import type {
  BackendErrorDetail,
  ChatHistoryMessage,
  ChatRequest,
  ChatResponse,
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
  constructor(
    public readonly code: string,
    public readonly httpStatus: number | null,
    public readonly userMessage: string,
    cause?: unknown,
  ) {
    super(userMessage, { cause });
    this.name = "ApiError";
  }
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
): Promise<ChatResponse> {
  const body: ChatRequest = { query };
  if (history.length > 0) body.history = history;
  if (k !== undefined) body.k = k;
  if (sessionId !== undefined) body.session_id = sessionId;
  if (fileId !== undefined) body.file_id = fileId;
  if (fileIds !== undefined) body.file_ids = fileIds;
  if (operatorId !== undefined) body.operator_id = operatorId;

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/chat`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    throw new ApiError("network", null, NETWORK_FAILURE, err);
  }

  if (response.ok) {
    return (await response.json()) as ChatResponse;
  }

  return readResponse<ChatResponse>(response);
}

export async function uploadFile(file: File, onProgress?: (percent: number) => void): Promise<FileReceipt> {
  if (!/\.xlsx?$/i.test(file.name)) {
    throw new ApiError("unsupported_file", null, "请选择 .xls 或 .xlsx 文件。");
  }
  if (file.size > 10 * 1024 * 1024) {
    throw new ApiError("file_too_large", null, "文件不能超过 10 MiB。");
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.withCredentials = true;
    xhr.open("POST", `${apiBaseUrl}/api/files?filename=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream"); xhr.timeout = 60000;
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress?.(Math.round(event.loaded / event.total * 100)); };
    xhr.onerror = () => reject(new ApiError("network", null, NETWORK_FAILURE));
    xhr.ontimeout = () => reject(new ApiError("upload_timeout", null, "上传超时，请检查连接后重新上传。"));
    xhr.onabort = () => reject(new ApiError("upload_cancelled", null, "上传已取消。"));
    xhr.onload = () => {
      if (!xhr.status) { reject(new ApiError("network", null, NETWORK_FAILURE)); return; }
      readResponse<FileReceipt>(new Response(xhr.responseText, { status: xhr.status })).then(resolve, reject);
    };
    xhr.send(file);
  });
}

export async function checkSessionFiles(fileIds: string[]): Promise<{ files: { file_id: string; status: "available" | "expired" }[] }> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/files/status`, {
      method: "POST", credentials: "include", cache: "no-store",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_ids: fileIds }),
    });
  } catch (err) { throw new ApiError("network", null, NETWORK_FAILURE, err); }
  return readResponse(response);
}

async function readResponse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
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
      ["public_demo_limit", "public_origin_denied", "invalid_result_file", "file_too_large", "unsupported_file", "file_not_found", "file_store_full", "file_tools_unavailable"].includes(data.detail.code)
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
