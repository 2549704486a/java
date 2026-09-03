import { useEffect, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Bot,
  Boxes,
  Clock3,
  Database,
  LoaderCircle,
  RefreshCw,
  TriangleAlert,
  Users
} from "lucide-react";

import {
  ApiError,
  fetchAgentObservationDetail,
  fetchAgentObservationRequests,
  fetchAgentObservationSummary
} from "../api";
import type {
  AgentObservationSummary,
  AgentRequestDetail,
  AgentRequestPage,
  AgentRunStatus,
  AgentType,
  ObservationWindow,
  RatioMetric
} from "../types";

interface Props {
  accessToken: string;
}

const windowLabels: Record<ObservationWindow, string> = {
  "24h": "最近 24 小时",
  "7d": "最近 7 天",
  "30d": "最近 30 天"
};

function formatRatio(metric: RatioMetric): string {
  return metric.value === null ? "暂无" : `${(metric.value * 100).toFixed(1)}%`;
}

function formatNumber(value: number | null): string {
  return value === null ? "暂无" : value.toLocaleString("zh-CN");
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}

function businessLabel(value: boolean | null): string {
  if (value === null) return "结果未知";
  return value ? "业务成功" : "业务拒绝";
}

function transportLabel(value: string | null): string {
  return value ? value.toUpperCase() : "未标记";
}

export default function AgentObservabilityDashboard({ accessToken }: Props) {
  const [window, setWindow] = useState<ObservationWindow>("7d");
  const [agentType, setAgentType] = useState<AgentType | "ALL">("ALL");
  const [status, setStatus] = useState<AgentRunStatus | "ALL">("ALL");
  const [page, setPage] = useState(1);
  const [summary, setSummary] = useState<AgentObservationSummary | null>(null);
  const [requests, setRequests] = useState<AgentRequestPage | null>(null);
  const [detail, setDetail] = useState<AgentRequestDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void Promise.all([
      fetchAgentObservationSummary(accessToken, window, controller.signal),
      fetchAgentObservationRequests(
        accessToken,
        { window, agentType, status, page },
        controller.signal
      )
    ])
      .then(([nextSummary, nextRequests]) => {
        setSummary(nextSummary);
        setRequests(nextRequests);
        if (
          detail &&
          !nextRequests.items.some(
            (item) => item.request_id === detail.request.request_id
          )
        ) {
          setDetail(null);
        }
      })
      .catch((reason) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(
          reason instanceof ApiError ? reason.message : "无法读取 Agent 运行数据"
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [accessToken, window, agentType, status, page, refreshKey]);

  async function openDetail(requestId: string) {
    setDetailLoading(true);
    setError(null);
    try {
      setDetail(await fetchAgentObservationDetail(accessToken, requestId));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "无法读取请求轨迹");
    } finally {
      setDetailLoading(false);
    }
  }

  const maxTrend = Math.max(1, ...(summary?.trend.map((item) => item.total) ?? [1]));
  const totalPages = requests ? Math.max(1, Math.ceil(requests.total / requests.page_size)) : 1;

  return (
    <main className="agent-observe-shell">
      <section className="agent-observe-hero">
        <div>
          <p className="operator-kicker">AGENT RUNTIME PULSE</p>
          <h1>看见每一次<br />Agent 运行。</h1>
          <p>这里展示运行完成、耗时、模型用量和 Tool 摘要，不保存对话正文或业务参数。</p>
        </div>
        <div className="agent-observe-controls">
          <div className="agent-window-tabs" aria-label="统计窗口">
            {(Object.keys(windowLabels) as ObservationWindow[]).map((item) => (
              <button
                className={window === item ? "is-active" : ""}
                key={item}
                type="button"
                onClick={() => { setWindow(item); setPage(1); }}
              >
                {windowLabels[item]}
              </button>
            ))}
          </div>
          <button
            className="agent-refresh"
            type="button"
            onClick={() => setRefreshKey((value) => value + 1)}
            disabled={loading}
          >
            <RefreshCw className={loading ? "spin" : ""} size={16} /> 手动刷新
          </button>
        </div>
      </section>

      {error && (
        <div className="agent-observe-error">
          <TriangleAlert size={18} /><span>{error}</span>
        </div>
      )}

      {loading && !summary ? (
        <div className="agent-observe-loading">
          <LoaderCircle className="spin" size={26} /> 正在汇总运行数据…
        </div>
      ) : summary ? (
        <>
          <section className="agent-metric-grid">
            <article className="is-primary">
              <Activity size={19} />
              <span>运行完成率</span>
              <strong>{formatRatio(summary.requests.completion)}</strong>
              <small>{summary.requests.completed} / {summary.requests.total} 次完成</small>
            </article>
            <article>
              <Clock3 size={19} />
              <span>P95 端到端耗时</span>
              <strong>{summary.requests.latency.p95_ms === null ? "暂无" : `${summary.requests.latency.p95_ms} ms`}</strong>
              <small>平均 {summary.requests.latency.average_ms === null ? "暂无" : `${summary.requests.latency.average_ms} ms`}</small>
            </article>
            <article>
              <Database size={19} />
              <span>模型 Token</span>
              <strong>{formatNumber(
                summary.model_usage.input_tokens === null || summary.model_usage.output_tokens === null
                  ? null
                  : summary.model_usage.input_tokens + summary.model_usage.output_tokens
              )}</strong>
              <small>覆盖 {formatRatio(summary.model_usage.coverage)} 的请求</small>
            </article>
            <article>
              <Boxes size={19} />
              <span>Tool 执行完成率</span>
              <strong>{formatRatio(summary.tools.execution_completion)}</strong>
              <small>{summary.tools.completed_calls} / {summary.tools.total_calls} 次完成</small>
            </article>
          </section>

          <section className="agent-observe-grid">
            <article className="agent-trend-panel">
              <header>
                <div><p className="operator-kicker">REQUEST TREND</p><h2>请求走势</h2></div>
                <small>{formatTime(summary.started_at)} 至 {formatTime(summary.ended_at)}</small>
              </header>
              {summary.requests.total === 0 ? (
                <p className="agent-observe-empty">这个时间窗口内还没有 Agent 请求。</p>
              ) : (
                <div className="agent-trend-chart">
                  {summary.trend.map((item) => (
                    <div className="agent-trend-item" key={item.started_at} title={`${formatTime(item.started_at)}：${item.total} 次`}>
                      <div className="agent-trend-bar">
                        <i style={{ height: `${Math.max(5, item.total / maxTrend * 100)}%` }} />
                        {item.failed > 0 && <b style={{ height: `${item.failed / maxTrend * 100}%` }} />}
                      </div>
                      <span>{window === "24h" ? new Date(item.started_at).getHours() : new Date(item.started_at).getDate()}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="agent-type-split">
                <div><Users size={17} /><span>用户助手</span><strong>{summary.requests_by_agent_type.USER.total}</strong></div>
                <div><Bot size={17} /><span>运营 Agent</span><strong>{summary.requests_by_agent_type.OPERATOR.total}</strong></div>
              </div>
            </article>

            <article className="agent-tool-panel">
              <header><p className="operator-kicker">TOOL HEALTH</p><h2>Tool 运行摘要</h2></header>
              {summary.tools_by_name.length === 0 ? (
                <p className="agent-observe-empty">这个窗口内没有 Tool 调用。</p>
              ) : (
                <div className="agent-table-scroll">
                  <table>
                    <thead><tr><th>Tool</th><th>调用</th><th>执行完成</th><th>业务成功</th><th>P95</th></tr></thead>
                    <tbody>
                      {summary.tools_by_name.map((tool) => (
                        <tr key={tool.tool_name ?? "all"}>
                          <td>{tool.tool_name}</td>
                          <td>{tool.total_calls}</td>
                          <td>{formatRatio(tool.execution_completion)}</td>
                          <td>{formatRatio(tool.business_success)}</td>
                          <td>{tool.latency.p95_ms === null ? "暂无" : `${tool.latency.p95_ms} ms`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </article>
          </section>
        </>
      ) : null}

      <section className="agent-request-panel">
        <header>
          <div><p className="operator-kicker">REQUEST EXPLORER</p><h2>请求与 Tool 轨迹</h2></div>
          <div className="agent-request-filters">
            <select value={agentType} onChange={(event) => { setAgentType(event.target.value as AgentType | "ALL"); setPage(1); }}>
              <option value="ALL">全部 Agent</option><option value="USER">用户助手</option><option value="OPERATOR">运营 Agent</option>
            </select>
            <select value={status} onChange={(event) => { setStatus(event.target.value as AgentRunStatus | "ALL"); setPage(1); }}>
              <option value="ALL">全部状态</option><option value="COMPLETED">已完成</option><option value="FAILED">运行失败</option>
            </select>
          </div>
        </header>
        <div className={`agent-request-layout ${detail ? "has-detail" : ""}`}>
          <div className="agent-request-list">
            {requests?.items.length === 0 && <p className="agent-observe-empty">当前筛选条件下没有请求。</p>}
            {requests?.items.map((item) => (
              <button key={item.request_id} type="button" onClick={() => void openDetail(item.request_id)}>
                <span className={`agent-status is-${item.status.toLowerCase()}`}>{item.status === "COMPLETED" ? "完成" : "失败"}</span>
                <div><strong>{item.request_id}</strong><small>{item.agent_type === "USER" ? "用户助手" : "运营 Agent"} · {formatTime(item.started_at)}</small></div>
                <dl><div><dt>耗时</dt><dd>{item.elapsed_ms} ms</dd></div><div><dt>模型</dt><dd>{item.model_call_count} 次</dd></div><div><dt>Tool</dt><dd>{item.tool_call_count} 次</dd></div></dl>
              </button>
            ))}
            {requests && requests.total > 0 && (
              <div className="agent-pagination">
                <button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</button>
                <span>{page} / {totalPages}</span>
                <button type="button" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>下一页</button>
              </div>
            )}
          </div>

          {(detail || detailLoading) && (
            <aside className="agent-trace-detail">
              <button className="agent-detail-close" type="button" onClick={() => setDetail(null)}><ArrowLeft size={15} /> 返回列表</button>
              {detailLoading ? <p><LoaderCircle className="spin" size={18} /> 正在读取轨迹…</p> : detail && (
                <>
                  <header><span>{detail.request.agent_type}</span><strong>{detail.request.request_id}</strong><small>{detail.request.elapsed_ms} ms · {detail.request.status}</small></header>
                  {detail.tool_calls.length === 0 ? <p className="agent-observe-empty">这次请求没有调用 Tool。</p> : (
                    <ol>
                      {detail.tool_calls.map((tool) => (
                        <li key={tool.sequence}>
                          <i>{tool.sequence}</i>
                          <div><strong>{tool.tool_name}</strong><small>{transportLabel(tool.transport)} · {tool.elapsed_ms} ms</small><span>{tool.completed ? businessLabel(tool.business_success) : `执行异常：${tool.error_type ?? "未知"}`}{tool.result_code ? ` · ${tool.result_code}` : ""}</span></div>
                        </li>
                      ))}
                    </ol>
                  )}
                </>
              )}
            </aside>
          )}
        </div>
      </section>
    </main>
  );
}
