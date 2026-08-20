import type { ChatResponse, DashboardResponse } from "./types";

interface ApiErrorBody {
  code?: string;
  message?: string;
}

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number
  ) {
    super(message);
  }
}

async function readJson<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as unknown;
  if (!response.ok) {
    const errorBody = body as ApiErrorBody;
    throw new ApiError(
      errorBody.code ?? "HTTP_ERROR",
      errorBody.message ?? `请求失败，HTTP ${response.status}`,
      response.status
    );
  }
  return body as T;
}

function requestId(): string {
  return `web-${crypto.randomUUID()}`;
}

export async function fetchDashboard(
  userId: number,
  signal?: AbortSignal
): Promise<DashboardResponse> {
  const response = await fetch(`/v1/dashboard/${userId}`, {
    headers: { "X-Request-ID": requestId() },
    signal
  });
  return readJson<DashboardResponse>(response);
}

export async function sendChat(
  userId: number,
  sessionId: string | null,
  message: string
): Promise<ChatResponse> {
  const response = await fetch("/v1/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "X-Request-ID": requestId()
    },
    body: JSON.stringify({
      user_id: userId,
      session_id: sessionId,
      message
    })
  });
  return readJson<ChatResponse>(response);
}

export async function fetchHealth(): Promise<boolean> {
  try {
    const response = await fetch("/health");
    return response.ok;
  } catch {
    return false;
  }
}
