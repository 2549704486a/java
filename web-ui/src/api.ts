import type {
  ChatResponse,
  CurrentUserResponse,
  DashboardResponse,
  CurrentOperatorResponse,
  CampaignActivityRecord,
  CampaignDraftRecord,
  CampaignEffectMetricRecord,
  CampaignFunnelRecord,
  CampaignSimulationRecord,
  OperatorChatResponse,
  OrdersResponse,
  NotificationActionResponse,
  NotificationsResponse,
  AgentObservationSummary,
  AgentRequestDetail,
  AgentRequestPage,
  AgentRunStatus,
  AgentType,
  ObservationWindow,
  ToolEnvelope
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

export async function fetchCurrentOperator(
  accessToken: string
): Promise<CurrentOperatorResponse> {
  const response = await fetch("/v1/operator/me", {
    headers: authenticatedHeaders(accessToken)
  });
  return readJson<CurrentOperatorResponse>(response);
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

export async function fetchNotifications(
  accessToken: string,
  signal?: AbortSignal
): Promise<NotificationsResponse> {
  const response = await fetch("/v1/notifications", {
    headers: authenticatedHeaders(accessToken),
    signal
  });
  return readJson<NotificationsResponse>(response);
}

export async function updateNotification(
  accessToken: string,
  notificationId: number,
  action: "read" | "click"
): Promise<NotificationActionResponse> {
  const response = await fetch(`/v1/notifications/${notificationId}/${action}`, {
    method: "POST",
    headers: authenticatedHeaders(accessToken)
  });
  return readJson<NotificationActionResponse>(response);
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

export async function sendOperatorChat(
  accessToken: string,
  sessionId: string | null,
  message: string
): Promise<OperatorChatResponse> {
  const response = await fetch("/v1/operator/chat", {
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
  return readJson<OperatorChatResponse>(response);
}

export async function fetchCampaignDrafts(
  accessToken: string
): Promise<ToolEnvelope<CampaignDraftRecord[]>> {
  const response = await fetch("/v1/operator/campaign/drafts?limit=50", {
    headers: authenticatedHeaders(accessToken)
  });
  return readJson<ToolEnvelope<CampaignDraftRecord[]>>(response);
}

export async function actOnCampaignDraft(
  accessToken: string,
  draftId: number,
  action: "submit" | "approve" | "reject" | "publish",
  version: number,
  comment?: string
): Promise<ToolEnvelope<CampaignDraftRecord | CampaignActivityRecord>> {
  const response = await fetch(
    `/v1/operator/campaign/drafts/${draftId}/${action}`,
    {
      method: "POST",
      headers: {
        ...authenticatedHeaders(accessToken),
        "Content-Type": "application/json; charset=utf-8"
      },
      body: JSON.stringify({ version, comment: comment || null })
    }
  );
  return readJson<ToolEnvelope<CampaignDraftRecord | CampaignActivityRecord>>(response);
}

export async function fetchCampaignActivities(
  accessToken: string
): Promise<ToolEnvelope<CampaignActivityRecord[]>> {
  const response = await fetch("/v1/operator/campaign/activities?limit=50", {
    headers: authenticatedHeaders(accessToken)
  });
  return readJson<ToolEnvelope<CampaignActivityRecord[]>>(response);
}

export async function recordCampaignMetric(
  accessToken: string,
  activityId: number,
  payload: {
    metric_name: string;
    metric_value: number;
    sample_size: number;
    measured_at: string;
    source_ref: string | null;
  }
): Promise<ToolEnvelope<CampaignEffectMetricRecord>> {
  const response = await fetch(
    `/v1/operator/campaign/activities/${activityId}/metrics`,
    {
      method: "POST",
      headers: {
        ...authenticatedHeaders(accessToken),
        "Content-Type": "application/json; charset=utf-8"
      },
      body: JSON.stringify(payload)
    }
  );
  return readJson<ToolEnvelope<CampaignEffectMetricRecord>>(response);
}

export async function fetchCampaignFunnel(
  accessToken: string,
  activityId: number
): Promise<ToolEnvelope<CampaignFunnelRecord>> {
  const response = await fetch(
    `/v1/operator/campaign/activities/${activityId}/funnel`,
    { headers: authenticatedHeaders(accessToken) }
  );
  return readJson<ToolEnvelope<CampaignFunnelRecord>>(response);
}

export async function simulateCampaignActivity(
  accessToken: string,
  activityId: number
): Promise<ToolEnvelope<CampaignSimulationRecord>> {
  const response = await fetch(
    `/v1/operator/campaign/activities/${activityId}/simulate`,
    {
      method: "POST",
      headers: {
        ...authenticatedHeaders(accessToken),
        "Content-Type": "application/json; charset=utf-8"
      },
      body: JSON.stringify({ scenario_key: "DEMO_BASELINE_V1" })
    }
  );
  return readJson<ToolEnvelope<CampaignSimulationRecord>>(response);
}

export async function fetchAgentObservationSummary(
  accessToken: string,
  window: ObservationWindow,
  signal?: AbortSignal
): Promise<AgentObservationSummary> {
  const response = await fetch(
    `/v1/operator/agent-observability/summary?window=${window}`,
    { headers: authenticatedHeaders(accessToken), signal }
  );
  return readJson<AgentObservationSummary>(response);
}

export async function fetchAgentObservationRequests(
  accessToken: string,
  options: {
    window: ObservationWindow;
    agentType: AgentType | "ALL";
    status: AgentRunStatus | "ALL";
    page: number;
    pageSize?: number;
  },
  signal?: AbortSignal
): Promise<AgentRequestPage> {
  const query = new URLSearchParams({
    window: options.window,
    page: String(options.page),
    page_size: String(options.pageSize ?? 20)
  });
  if (options.agentType !== "ALL") query.set("agent_type", options.agentType);
  if (options.status !== "ALL") query.set("status", options.status);
  const response = await fetch(
    `/v1/operator/agent-observability/requests?${query.toString()}`,
    { headers: authenticatedHeaders(accessToken), signal }
  );
  return readJson<AgentRequestPage>(response);
}

export async function fetchAgentObservationDetail(
  accessToken: string,
  observationRequestId: string,
  signal?: AbortSignal
): Promise<AgentRequestDetail> {
  const response = await fetch(
    `/v1/operator/agent-observability/requests/${encodeURIComponent(observationRequestId)}`,
    { headers: authenticatedHeaders(accessToken), signal }
  );
  return readJson<AgentRequestDetail>(response);
}

export async function fetchHealth(): Promise<boolean> {
  try {
    const response = await fetch("/health");
    return response.ok;
  } catch {
    return false;
  }
}
