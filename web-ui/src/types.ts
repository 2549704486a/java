export interface ToolEnvelope<T> {
  success: boolean;
  code: string;
  data: T | null;
  message: string;
  retryable: boolean;
}

export interface Award {
  awardId: number;
  name: string;
  coverUrl?: string | null;
  awardType?: number | null;
  inventory: number;
  requiredPoints: number;
  startTime?: string | null;
  endTime?: string | null;
  overSellAllowed?: boolean;
}

export interface AwardOption {
  award: Award;
  redeemable: boolean;
  pointsGap: number;
  reasonCode: string;
}

export interface DashboardResponse {
  request_id: string;
  user_id: number;
  points: number;
  awards: AwardOption[];
}

export type ExchangeStatus = "PROCESSING" | "SUCCESS" | "FAILED";

export interface ExchangeRecord {
  orderId: number;
  awardId: number;
  awardName: string;
  status: ExchangeStatus;
  statusMessage: string;
  createTime: string;
  updateTime: string;
}

export interface OrdersResponse {
  request_id: string;
  user_id: number;
  records: ExchangeRecord[];
}

export type NotificationStatus = "UNREAD" | "READ" | "CLICKED";

export interface UserNotification {
  id: number;
  activityId: number;
  title: string;
  content: string;
  status: NotificationStatus;
  readAt?: string | null;
  clickedAt?: string | null;
  createdAt: string;
}

export interface NotificationsResponse {
  request_id: string;
  user_id: number;
  notifications: UserNotification[];
}

export interface NotificationActionResponse {
  request_id: string;
  user_id: number;
  notification: UserNotification;
}

export interface CurrentUserResponse {
  user_id: number;
}

export interface CurrentOperatorResponse {
  operator_id: string;
  permissions: string[];
}

export interface ChatResponse {
  request_id: string;
  session_id: string;
  user_id: number;
  answer: string;
  elapsed_ms: number;
  pending_exchange: PendingExchange | null;
}

export interface OperatorChatResponse {
  request_id: string;
  session_id: string;
  operator_id: string;
  answer: string;
  elapsed_ms: number;
}

export type CampaignDraftStatus =
  | "DRAFT"
  | "PENDING_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "PUBLISHED";

export interface CampaignDraftRecord {
  id: number;
  draftKey: string;
  version: number;
  operatorId: string;
  objective: string;
  targetSegmentKey: string;
  targetSegment: string;
  budgetAmountCents: number;
  pointsIssuanceCap: number;
  startAt: string;
  endAt: string;
  planJson: string;
  status: CampaignDraftStatus;
  reviewerId?: string | null;
  reviewComment?: string | null;
  reviewedAt?: string | null;
  publishedBy?: string | null;
  publishedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface CampaignActivityRecord {
  id: number;
  draftId: number;
  objective: string;
  targetSegmentKey: string;
  budgetAmountCents: number;
  pointsIssuanceCap: number;
  startAt: string;
  endAt: string;
  planJson: string;
  status: string;
  publishedBy: string;
  publishedAt: string;
  createdAt: string;
  updatedAt: string;
}

export interface CampaignEffectMetricRecord {
  id: number;
  activityId: number;
  metricName: string;
  metricValue: number;
  sampleSize?: number | null;
  measuredAt: string;
  sourceRef?: string | null;
  recordedBy: string;
  createdAt: string;
}

export interface CampaignGroupFunnelRecord {
  experimentGroup: "TREATMENT" | "CONTROL";
  targetedUsers: number;
  deliveredUsers: number;
  viewedUsers: number;
  clickedUsers: number;
  taskCompletedUsers: number;
  exchangedUsers: number;
  deliveryRate: number;
  viewRate: number;
  clickRate: number;
  taskCompletionRate: number;
  exchangeRate: number;
}

export interface CampaignFunnelRecord {
  activityId: number;
  executionId: number;
  dataSource: "REAL" | "SIMULATED" | "MIXED";
  treatment: CampaignGroupFunnelRecord;
  control: CampaignGroupFunnelRecord;
  taskCompletionLift: number;
  exchangeLift: number;
  measuredAt: string;
}

export interface CampaignSimulationRecord {
  activityId: number;
  scenarioKey: "DEMO_BASELINE_V1";
  insertedEvents: number;
  dataSource: "SIMULATED";
  funnel: CampaignFunnelRecord;
}

export interface PendingExchange {
  status: "AWAITING_CONFIRMATION";
  awardId: number;
  awardName: string;
  currentPoints: number;
  requiredPoints: number;
  remainingPoints: number;
  expiresAt: string;
}

export type ChatRole = "assistant" | "user";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  elapsedMs?: number;
}

export type ObservationWindow = "24h" | "7d" | "30d";
export type AgentType = "USER" | "OPERATOR";
export type AgentRunStatus = "COMPLETED" | "FAILED";

export interface RatioMetric {
  numerator: number;
  denominator: number;
  value: number | null;
}

export interface LatencyMetric {
  average_ms: number | null;
  p95_ms: number | null;
}

export interface RequestMetric {
  total: number;
  completed: number;
  failed: number;
  completion: RatioMetric;
  latency: LatencyMetric;
}

export interface ModelUsageMetric {
  model_call_count: number;
  covered_requests: number;
  coverage: RatioMetric;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface ToolMetric {
  tool_name: string | null;
  total_calls: number;
  completed_calls: number;
  business_result_known_calls: number;
  business_successful_calls: number;
  execution_completion: RatioMetric;
  business_success: RatioMetric;
  latency: LatencyMetric;
}

export interface ObservationTrendPoint {
  started_at: string;
  ended_at: string;
  total: number;
  completed: number;
  failed: number;
}

export interface AgentObservationSummary {
  window: ObservationWindow;
  started_at: string;
  ended_at: string;
  requests: RequestMetric;
  requests_by_agent_type: Record<AgentType, RequestMetric>;
  model_usage: ModelUsageMetric;
  tools: ToolMetric;
  tools_by_name: ToolMetric[];
  trend: ObservationTrendPoint[];
}

export interface AgentRequestRecord {
  request_id: string;
  agent_type: AgentType;
  started_at: string;
  completed_at: string;
  status: AgentRunStatus;
  elapsed_ms: number;
  model_call_count: number;
  input_tokens: number | null;
  output_tokens: number | null;
  tool_call_count: number;
  error_type: string | null;
}

export interface AgentToolObservation {
  request_id: string;
  sequence: number;
  tool_name: string;
  transport: string | null;
  completed: boolean;
  business_success: boolean | null;
  result_code: string | null;
  elapsed_ms: number;
  error_type: string | null;
}

export interface AgentRequestPage {
  total: number;
  page: number;
  page_size: number;
  items: AgentRequestRecord[];
}

export interface AgentRequestDetail {
  request: AgentRequestRecord;
  tool_calls: AgentToolObservation[];
}
