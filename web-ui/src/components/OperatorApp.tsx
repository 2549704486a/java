import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Activity,
  BookOpenCheck,
  Bot,
  ClipboardList,
  KeyRound,
  LoaderCircle,
  LogOut,
  MessageSquareText,
  Send,
  ShieldCheck,
  Sparkles,
  RefreshCw
} from "lucide-react";

import {
  ApiError,
  actOnCampaignDraft,
  fetchCampaignActivities,
  fetchCampaignDrafts,
  fetchCurrentOperator,
  recordCampaignMetric,
  sendOperatorChat
} from "../api";
import type {
  CampaignActivityRecord,
  CampaignDraftRecord,
  ChatMessage,
  CurrentOperatorResponse
} from "../types";

const quickPrompts = [
  {
    label: "查看高积分客群",
    prompt: "请查看积分不少于 500 的客群活动规划快照，并概括可用任务、奖品和历史指标。"
  },
  {
    label: "核对预算制度",
    prompt: "活动的现金预算与积分发放上限应该如何分别约束？请查询当前有效制度并标注来源。"
  },
  {
    label: "生成活动草案",
    prompt: "我想为积分不少于 500 的用户策划提升任务参与率的活动，请告诉我还需要补充哪些参数。"
  }
];

function initialToken(): string {
  return sessionStorage.getItem("incentive-operator-token") ?? "";
}

function messageId(): string {
  return crypto.randomUUID();
}

const statusLabels: Record<string, string> = {
  DRAFT: "待提交",
  PENDING_REVIEW: "待审核",
  APPROVED: "已批准",
  REJECTED: "已驳回",
  PUBLISHED: "已发布"
};

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export default function OperatorApp() {
  const [accessToken, setAccessToken] = useState(initialToken);
  const [tokenDraft, setTokenDraft] = useState(initialToken);
  const [operator, setOperator] = useState<CurrentOperatorResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(Boolean(initialToken()));
  const [authError, setAuthError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [campaignDrafts, setCampaignDrafts] = useState<CampaignDraftRecord[]>([]);
  const [activities, setActivities] = useState<CampaignActivityRecord[]>([]);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [metricActivityId, setMetricActivityId] = useState<number | null>(null);
  const [metricName, setMetricName] = useState("participation_rate");
  const [metricValue, setMetricValue] = useState("");
  const [metricSampleSize, setMetricSampleSize] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: messageId(),
      role: "assistant",
      content: "我是智能运营助手。可以读取实时活动快照、查询运营制度，并生成一份待人工审阅的活动草案。"
    }
  ]);
  const conversationEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!accessToken) {
      setOperator(null);
      setAuthLoading(false);
      return;
    }
    let active = true;
    setAuthLoading(true);
    setAuthError(null);
    void fetchCurrentOperator(accessToken)
      .then((identity) => {
        if (active) setOperator(identity);
      })
      .catch((error) => {
        if (!active) return;
        setOperator(null);
        setAuthError(
          error instanceof ApiError ? error.message : "无法验证运营访问令牌"
        );
      })
      .finally(() => {
        if (active) setAuthLoading(false);
      });
    return () => {
      active = false;
    };
  }, [accessToken]);

  useEffect(() => {
    if (operator) void refreshWorkflow();
  }, [operator]);

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  function signIn(event: FormEvent) {
    event.preventDefault();
    const token = tokenDraft.trim();
    if (!token) {
      setAuthError("请输入运营访问令牌");
      return;
    }
    sessionStorage.setItem("incentive-operator-token", token);
    setAccessToken(token);
  }

  function signOut() {
    sessionStorage.removeItem("incentive-operator-token");
    setAccessToken("");
    setTokenDraft("");
    setOperator(null);
    setSessionId(null);
    setCampaignDrafts([]);
    setActivities([]);
  }

  async function refreshWorkflow() {
    if (!accessToken) return;
    setWorkflowLoading(true);
    setWorkflowError(null);
    try {
      const [draftEnvelope, activityEnvelope] = await Promise.all([
        fetchCampaignDrafts(accessToken),
        fetchCampaignActivities(accessToken)
      ]);
      if (!draftEnvelope.success || !activityEnvelope.success) {
        throw new Error(draftEnvelope.message || activityEnvelope.message);
      }
      setCampaignDrafts(draftEnvelope.data ?? []);
      setActivities(activityEnvelope.data ?? []);
      setMetricActivityId((current) => current ?? activityEnvelope.data?.[0]?.id ?? null);
    } catch (error) {
      setWorkflowError(error instanceof Error ? error.message : "无法刷新活动工作流");
    } finally {
      setWorkflowLoading(false);
    }
  }

  async function runDraftAction(
    item: CampaignDraftRecord,
    action: "submit" | "approve" | "reject" | "publish"
  ) {
    let comment = "";
    if (action === "reject") {
      comment = window.prompt("请填写驳回原因")?.trim() ?? "";
      if (!comment) return;
    }
    setWorkflowLoading(true);
    setWorkflowError(null);
    try {
      const result = await actOnCampaignDraft(
        accessToken,
        item.id,
        action,
        item.version,
        comment
      );
      if (!result.success) throw new Error(result.message);
      await refreshWorkflow();
    } catch (error) {
      setWorkflowError(error instanceof Error ? error.message : "工作流操作失败");
      setWorkflowLoading(false);
    }
  }

  async function submitMetric(event: FormEvent) {
    event.preventDefault();
    if (!metricActivityId || !metricName.trim() || !metricValue.trim()) return;
    setWorkflowLoading(true);
    setWorkflowError(null);
    try {
      const result = await recordCampaignMetric(accessToken, metricActivityId, {
        metric_name: metricName.trim(),
        metric_value: Number(metricValue),
        sample_size: Number(metricSampleSize),
        measured_at: new Date().toISOString(),
        source_ref: "operator-workbench"
      });
      if (!result.success) throw new Error(result.message);
      setMetricValue("");
      setMetricSampleSize("");
      await refreshWorkflow();
    } catch (error) {
      setWorkflowError(error instanceof Error ? error.message : "效果指标录入失败");
      setWorkflowLoading(false);
    }
  }

  async function submit(message: string) {
    const content = message.trim();
    if (!content || sending || !operator) return;
    setMessages((current) => [
      ...current,
      { id: messageId(), role: "user", content }
    ]);
    setDraft("");
    setSending(true);
    try {
      const response = await sendOperatorChat(accessToken, sessionId, content);
      setSessionId(response.session_id);
      setMessages((current) => [
        ...current,
        {
          id: messageId(),
          role: "assistant",
          content: response.answer,
          elapsedMs: response.elapsed_ms
        }
      ]);
      await refreshWorkflow();
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: messageId(),
          role: "assistant",
          content: error instanceof ApiError ? error.message : "运营助手暂时不可用"
        }
      ]);
    } finally {
      setSending(false);
    }
  }

  if (authLoading || operator === null) {
    return (
      <main className="operator-login-shell">
        <section className="operator-login-card">
          <span className="operator-mark"><ClipboardList size={24} /></span>
          <p className="operator-kicker">OPERATIONS CONTROL</p>
          <h1>进入智能运营工作台</h1>
          <p>运营入口使用独立令牌和服务端权限，不与普通用户身份混用。</p>
          <form onSubmit={signIn}>
            <label htmlFor="operator-token"><KeyRound size={16} /> 运营访问令牌</label>
            <textarea
              id="operator-token"
              rows={4}
              value={tokenDraft}
              onChange={(event) => setTokenDraft(event.target.value)}
              placeholder="填写 .env 中配置的 OPERATOR_ACCESS_TOKEN"
              disabled={authLoading}
            />
            {authError && <span className="operator-auth-error">{authError}</span>}
            <button type="submit" disabled={authLoading || !tokenDraft.trim()}>
              {authLoading ? <LoaderCircle className="spin" size={18} /> : <ShieldCheck size={18} />}
              {authLoading ? "正在验证" : "进入工作台"}
            </button>
          </form>
          <a href="/">返回用户端奖品中心 <ArrowUpRight size={15} /></a>
        </section>
      </main>
    );
  }

  return (
    <div className="operator-shell">
      <header className="operator-topbar">
        <div className="operator-brand">
          <span className="operator-mark"><ClipboardList size={21} /></span>
          <div><strong>增长运营台</strong><small>INCENTIVE OPERATIONS</small></div>
        </div>
        <div className="operator-identity">
          <span>{operator.operator_id}</span>
          <button type="button" onClick={signOut}><LogOut size={14} /> 退出</button>
        </div>
      </header>

      <main className="operator-workbench">
        <aside className="operator-briefing">
          <p className="operator-kicker">TODAY'S BRIEFING</p>
          <h1>先看事实，<br />再做活动。</h1>
          <p>让 Agent 负责信息聚合和草案生成，把发布决定留给运营人员。</p>
          <div className="operator-capabilities">
            <div><BookOpenCheck size={18} /><span><strong>实时事实</strong>客群、任务、奖品与库存</span></div>
            <div><MessageSquareText size={18} /><span><strong>制度依据</strong>预算口径、异常手册与案例</span></div>
            <div><Sparkles size={18} /><span><strong>活动草案</strong>生成后必须人工审阅</span></div>
          </div>
          <div className="operator-boundary">
            <ShieldCheck size={18} />
            <p><strong>权限边界</strong>活动不能绕过人工审核直接发布，工作台也不能修改线上规则。</p>
          </div>
        </aside>

        <section className="operator-conversation">
          <header>
            <div><Bot size={20} /><span><strong>运营策划 Agent</strong><small>独立会话 · Tool 结果可追踪</small></span></div>
            <span className="operator-live"><i /> READY</span>
          </header>
          <div className="operator-messages">
            {messages.map((message) => (
              <article key={message.id} className={`operator-message is-${message.role}`}>
                <span>{message.role === "assistant" ? "AI" : "YOU"}</span>
                <div>
                  <p>{message.content}</p>
                  {message.elapsedMs !== undefined && <small>{Math.round(message.elapsedMs)} ms</small>}
                </div>
              </article>
            ))}
            {sending && (
              <article className="operator-message is-assistant is-loading">
                <span>AI</span><div><LoaderCircle className="spin" size={18} /> 正在读取事实并组织方案…</div>
              </article>
            )}
            <div ref={conversationEndRef} />
          </div>
          <div className="operator-quick-actions">
            {quickPrompts.map((item) => (
              <button key={item.label} type="button" onClick={() => setDraft(item.prompt)}>
                {item.label}
              </button>
            ))}
          </div>
          <form
            className="operator-composer"
            onSubmit={(event) => {
              event.preventDefault();
              void submit(draft);
            }}
          >
            <textarea
              rows={3}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="描述活动目标、客群、现金预算、积分上限和时间…"
              disabled={sending}
            />
            <button type="submit" disabled={sending || !draft.trim()} aria-label="发送">
              <Send size={18} />
            </button>
          </form>
        </section>

        <section className="operator-workflow">
          <header className="operator-workflow-heading">
            <div>
              <p className="operator-kicker">CAMPAIGN LIFECYCLE</p>
              <h2>从草案到效果回流</h2>
              <p>Agent 负责形成建议，运营人员负责审核，系统按确定性状态机发布并沉淀效果指标。</p>
            </div>
            <button type="button" onClick={() => void refreshWorkflow()} disabled={workflowLoading}>
              <RefreshCw className={workflowLoading ? "spin" : ""} size={16} /> 刷新事实
            </button>
          </header>
          {workflowError && <p className="operator-workflow-error">{workflowError}</p>}

          <div className="operator-workflow-grid">
            <div className="operator-flow-column">
              <div className="operator-flow-title">
                <span>01</span><div><strong>草案与审核</strong><small>{campaignDrafts.length} 个记录</small></div>
              </div>
              <div className="operator-card-list">
                {campaignDrafts.length === 0 && <p className="operator-empty">通过对话生成一份活动草案后，它会出现在这里。</p>}
                {campaignDrafts.map((item) => (
                  <article className="operator-campaign-card" key={item.id}>
                    <div className="operator-card-meta">
                      <span className={`status-${item.status.toLowerCase()}`}>
                        {statusLabels[item.status] ?? item.status}
                      </span>
                      <small>v{item.version} · {formatDate(item.updatedAt)}</small>
                    </div>
                    <h3>{item.objective}</h3>
                    <p>{item.targetSegment}</p>
                    <dl>
                      <div><dt>现金预算</dt><dd>¥{(item.budgetAmountCents / 100).toFixed(2)}</dd></div>
                      <div><dt>积分上限</dt><dd>{item.pointsIssuanceCap.toLocaleString()}</dd></div>
                      <div><dt>活动时间</dt><dd>{formatDate(item.startAt)} 至 {formatDate(item.endAt)}</dd></div>
                    </dl>
                    {item.reviewComment && <p className="operator-review-note">审核意见：{item.reviewComment}</p>}
                    <div className="operator-card-actions">
                      {item.status === "DRAFT" && operator.permissions.includes("campaign:draft") && (
                        <button type="button" onClick={() => void runDraftAction(item, "submit")}>提交审核</button>
                      )}
                      {item.status === "PENDING_REVIEW" && operator.permissions.includes("campaign:review") && (
                        <>
                          <button type="button" onClick={() => void runDraftAction(item, "approve")}>批准</button>
                          <button className="is-secondary" type="button" onClick={() => void runDraftAction(item, "reject")}>驳回</button>
                        </>
                      )}
                      {item.status === "APPROVED" && operator.permissions.includes("campaign:publish") && (
                        <button type="button" onClick={() => void runDraftAction(item, "publish")}>确定发布</button>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </div>

            <div className="operator-flow-column">
              <div className="operator-flow-title">
                <span>02</span><div><strong>已发布活动</strong><small>{activities.length} 个活动</small></div>
              </div>
              <div className="operator-card-list">
                {activities.length === 0 && <p className="operator-empty">批准后的草案发布后，会形成不可重复的活动记录。</p>}
                {activities.map((item) => (
                  <article className="operator-campaign-card is-live" key={item.id}>
                    <div className="operator-card-meta"><span>已发布</span><small>活动 #{item.id}</small></div>
                    <h3>{item.objective}</h3>
                    <p>{item.targetSegmentKey} · 发布人 {item.publishedBy}</p>
                    <dl>
                      <div><dt>现金预算</dt><dd>¥{(item.budgetAmountCents / 100).toFixed(2)}</dd></div>
                      <div><dt>发布时间</dt><dd>{formatDate(item.publishedAt)}</dd></div>
                    </dl>
                  </article>
                ))}
              </div>
            </div>

            <div className="operator-flow-column operator-metric-column">
              <div className="operator-flow-title">
                <span>03</span><div><strong>效果回流</strong><small>写回下一轮规划事实</small></div>
              </div>
              <form className="operator-metric-form" onSubmit={submitMetric}>
                <Activity size={23} />
                <label>活动
                  <select value={metricActivityId ?? ""} onChange={(event) => setMetricActivityId(Number(event.target.value))}>
                    <option value="" disabled>选择已发布活动</option>
                    {activities.map((item) => <option key={item.id} value={item.id}>#{item.id} {item.objective}</option>)}
                  </select>
                </label>
                <label>指标
                  <select value={metricName} onChange={(event) => setMetricName(event.target.value)}>
                    <option value="participation_rate">参与率</option>
                    <option value="conversion_rate">兑换转化率</option>
                    <option value="completion_rate">任务完成率</option>
                  </select>
                </label>
                <label>指标值
                  <input type="number" step="0.0001" value={metricValue} onChange={(event) => setMetricValue(event.target.value)} placeholder="例如 0.325" />
                </label>
                <label>样本量
                  <input type="number" min="1" value={metricSampleSize} onChange={(event) => setMetricSampleSize(event.target.value)} placeholder="例如 1200" />
                </label>
                <button type="submit" disabled={workflowLoading || !metricActivityId || !metricValue || !metricSampleSize}>记录效果</button>
                <p>该数据同时进入活动效果表与规划历史快照，后续 Agent 生成方案时可直接引用。</p>
              </form>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
