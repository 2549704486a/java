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
