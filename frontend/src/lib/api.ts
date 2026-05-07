import type {
  BackendErrorDetail,
  ChatRequest,
  ChatResponse,
} from "./types";
import {
  NETWORK_FAILURE,
  UNKNOWN_FAILURE,
  translateErrorCode,
} from "./error-messages";

const RAW_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const apiBaseUrl = RAW_BASE_URL.replace(/\/+$/, "");

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
  k?: number,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const body: ChatRequest = { query };
  if (k !== undefined) body.k = k;

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/chat`, {
      method: "POST",
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

  if (response.status === 422) {
    const data = (await safeJson(response)) as
      | { detail?: Array<{ msg?: string }> }
      | null;
    const msg = data?.detail?.[0]?.msg ?? "输入校验失败";
    throw new ApiError("validation_error", 422, `输入校验失败：${msg}`);
  }

  const data = (await safeJson(response)) as
    | { detail?: BackendErrorDetail | string }
    | null;
  if (
    data &&
    typeof data.detail === "object" &&
    data.detail !== null &&
    typeof data.detail.code === "string"
  ) {
    throw new ApiError(
      data.detail.code,
      response.status,
      translateErrorCode(data.detail.code),
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
