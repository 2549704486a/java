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

export interface ChatResponse {
  request_id: string;
  session_id: string;
  user_id: number;
  answer: string;
  elapsed_ms: number;
}

export type ChatRole = "assistant" | "user";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  elapsedMs?: number;
}
