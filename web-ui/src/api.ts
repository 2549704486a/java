import type {
  ChatResponse,
  CurrentUserResponse,
  DashboardResponse,
  OrdersResponse
} from "./types";

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

function authenticatedHeaders(accessToken: string): HeadersInit {
  return {
    Authorization: `Bearer ${accessToken}`,
    "X-Request-ID": requestId()
  };
}

export async function fetchCurrentUser(
  accessToken: string
): Promise<CurrentUserResponse> {
  const response = await fetch("/v1/me", {
    headers: authenticatedHeaders(accessToken)
  });
  return readJson<CurrentUserResponse>(response);
}

export async function fetchDashboard(
  accessToken: string,
  signal?: AbortSignal
): Promise<DashboardResponse> {
  const response = await fetch("/v1/dashboard", {
    headers: authenticatedHeaders(accessToken),
    signal
  });
  return readJson<DashboardResponse>(response);
}

export async function fetchOrders(
  accessToken: string,
  signal?: AbortSignal
): Promise<OrdersResponse> {
  const response = await fetch("/v1/orders", {
    headers: authenticatedHeaders(accessToken),
    signal
  });
  return readJson<OrdersResponse>(response);
}

export async function sendChat(
  accessToken: string,
  sessionId: string | null,
  message: string
): Promise<ChatResponse> {
  const response = await fetch("/v1/chat", {
    method: "POST",
    headers: {
      ...authenticatedHeaders(accessToken),
      "Content-Type": "application/json; charset=utf-8"
    },
    body: JSON.stringify({
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
