import type { CSSProperties } from "react";
import { ArrowUpRight, Clock3, Gift, Sparkles } from "lucide-react";

import type { AwardOption } from "../types";

interface AwardCardProps {
  option: AwardOption;
  index: number;
  onAsk: (option: AwardOption) => void;
}

const reasonLabels: Record<string, string> = {
  ELIGIBLE: "现在可兑换",
  INSUFFICIENT_POINTS: "积分待补齐",
  OUT_OF_STOCK: "暂时缺货",
  AWARD_NOT_STARTED: "活动未开始",
  AWARD_EXPIRED: "活动已结束",
  EXCHANGE_PROCESSING: "兑换处理中",
  ALREADY_REDEEMED: "已经兑换"
};

function formatDate(value?: string | null): string {
  if (!value) return "长期有效";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric"
  }).format(date);
}

export default function AwardCard({ option, index, onAsk }: AwardCardProps) {
  const { award } = option;
  const label = reasonLabels[option.reasonCode] ?? "条件待确认";

  return (
    <article
      className={`award-card award-theme-${index % 4}`}
      style={{ "--card-delay": `${index * 70}ms` } as CSSProperties}
    >
      <div className="award-visual" aria-hidden="true">
        <span className="award-index">0{index + 1}</span>
        <div className="award-orbit" />
        <Gift size={42} strokeWidth={1.35} />
      </div>

      <div className="award-body">
        <div className="award-heading">
          <div>
            <p className="eyebrow">AWARD {award.awardId}</p>
            <h3>{award.name}</h3>
          </div>
          <span className={`status-pill ${option.redeemable ? "is-ready" : ""}`}>
            {label}
          </span>
        </div>

        <div className="award-price-row">
          <div className="award-price">
            <Sparkles size={16} />
            <strong>{award.requiredPoints.toLocaleString("zh-CN")}</strong>
            <span>积分</span>
          </div>
          {!option.redeemable && option.pointsGap > 0 && (
            <span className="points-gap">还差 {option.pointsGap}</span>
          )}
        </div>

        <div className="award-meta">
          <span>库存 {award.inventory}</span>
          <span className="meta-divider" />
          <Clock3 size={14} />
          <span>至 {formatDate(award.endTime)}</span>
        </div>

        <button className="award-action" type="button" onClick={() => onAsk(option)}>
          <span>{option.redeemable ? "咨询兑换" : "让顾问规划"}</span>
          <ArrowUpRight size={17} />
        </button>
      </div>
    </article>
  );
}
