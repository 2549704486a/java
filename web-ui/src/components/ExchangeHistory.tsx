import { useEffect, useState } from "react";
import { CheckCircle2, Clock3, LoaderCircle, RefreshCw, XCircle } from "lucide-react";

import { ApiError, fetchOrders } from "../api";
import type { ExchangeRecord, ExchangeStatus } from "../types";

interface ExchangeHistoryProps {
  accessToken: string;
  refreshKey: number;
}

const statusLabels: Record<ExchangeStatus, string> = {
  PROCESSING: "处理中",
  SUCCESS: "兑换成功",
  FAILED: "兑换失败"
};

function StatusIcon({ status }: { status: ExchangeStatus }) {
  if (status === "SUCCESS") return <CheckCircle2 size={18} />;
  if (status === "FAILED") return <XCircle size={18} />;
  return <Clock3 size={18} />;
}

export default function ExchangeHistory({ accessToken, refreshKey }: ExchangeHistoryProps) {
  const [records, setRecords] = useState<ExchangeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(silent = false) {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const response = await fetchOrders(accessToken);
      setRecords(response.records);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "兑换记录暂时无法加载");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [accessToken, refreshKey]);

  useEffect(() => {
    // 只有处理中订单继续轮询；全部终态后不再产生后台请求。
    if (!records.some((record) => record.status === "PROCESSING")) return;
    const timer = window.setTimeout(() => void load(true), 2000);
    return () => window.clearTimeout(timer);
  }, [records]);

  return (
    <section className="order-section" id="orders">
      <header className="section-heading">
        <div>
          <p className="eyebrow">EXCHANGE TIMELINE</p>
          <h2>我的兑换</h2>
        </div>
        <button className="refresh-button" type="button" disabled={loading} onClick={() => void load()}>
          <RefreshCw size={16} className={loading ? "spin" : ""} />
          刷新订单
        </button>
      </header>

      {loading && records.length === 0 && (
        <div className="order-empty"><LoaderCircle className="spin" size={20} /> 正在读取兑换记录…</div>
      )}
      {error && <div className="order-error">{error}</div>}
      {!loading && !error && records.length === 0 && (
        <div className="order-empty">还没有兑换记录，先去奖品中心看看。</div>
      )}
      <div className="order-list">
        {records.map((record) => (
          <article className={`order-card is-${record.status.toLowerCase()}`} key={record.orderId}>
            <div className="order-status"><StatusIcon status={record.status} /></div>
            <div>
              <span>订单 {record.orderId} · 奖品 {record.awardId}</span>
              <strong>{record.awardName}</strong>
              <small>{new Date(record.createTime).toLocaleString("zh-CN")}</small>
            </div>
            <div className="order-result">
              <strong>{statusLabels[record.status]}</strong>
              <span>{record.statusMessage}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
