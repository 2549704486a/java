import { FormEvent, useEffect, useState } from "react";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleUserRound,
  Coins,
  Gift,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target
} from "lucide-react";

import { ApiError, fetchDashboard, fetchHealth } from "./api";
import AwardCard from "./components/AwardCard";
import ChatPanel from "./components/ChatPanel";
import type { AwardOption, DashboardResponse } from "./types";

type Filter = "all" | "ready" | "planning";

const filterLabels: Array<{ value: Filter; label: string }> = [
  { value: "all", label: "全部奖品" },
  { value: "ready", label: "现在可换" },
  { value: "planning", label: "需要规划" }
];

function readInitialUserId(): number {
  const stored = Number(localStorage.getItem("incentive-user-id"));
  return Number.isInteger(stored) && stored > 0 ? stored : 10;
}

export default function App() {
  const [userId, setUserId] = useState(readInitialUserId);
  const [userDraft, setUserDraft] = useState(String(readInitialUserId()));
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [serviceOnline, setServiceOnline] = useState<boolean | null>(null);
  const [chatDraft, setChatDraft] = useState("");

  async function loadDashboard(targetUserId: number, silent = false) {
    if (silent) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const result = await fetchDashboard(targetUserId);
      setDashboard(result);
    } catch (loadError) {
      setDashboard(null);
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : "奖品数据暂时无法加载，请确认本地服务已经启动。"
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadDashboard(userId);
    void fetchHealth().then(setServiceOnline);
  }, [userId]);

  function switchUser(event: FormEvent) {
    event.preventDefault();
    const nextUserId = Number(userDraft);
    if (!Number.isInteger(nextUserId) || nextUserId <= 0) {
      setError("用户 ID 必须是正整数");
      return;
    }
    localStorage.setItem("incentive-user-id", String(nextUserId));
    setUserId(nextUserId);
  }

  function askAboutAward(option: AwardOption) {
    const prompt = option.redeemable
      ? `我想兑换 ${option.award.awardId} 号奖品「${option.award.name}」，请发起安全确认。`
      : `我想兑换 ${option.award.awardId} 号奖品「${option.award.name}」，请帮我规划需要完成的任务。`;
    setChatDraft(prompt);
    document.getElementById("advisor")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const awards = dashboard?.awards ?? [];
  const readyCount = awards.filter((option) => option.redeemable).length;
  const visibleAwards = awards.filter((option) => {
    if (filter === "ready") return option.redeemable;
    if (filter === "planning") return !option.redeemable;
    return true;
  });

  return (
    <div className="app-shell">
      <div className="grain" aria-hidden="true" />

      <header className="topbar">
        <a className="brand" href="#top" aria-label="返回首页">
          <span className="brand-seal">拾</span>
          <span>
            <strong>拾光奖品社</strong>
            <small>REWARD SOCIETY</small>
          </span>
        </a>

        <nav aria-label="主导航">
          <a className="is-active" href="#awards">奖品中心</a>
          <a href="#advisor">兑换顾问</a>
        </nav>

        <form className="user-switcher" onSubmit={switchUser}>
          <CircleUserRound size={17} />
          <label htmlFor="user-id">用户</label>
          <input
            id="user-id"
            inputMode="numeric"
            value={userDraft}
            onChange={(event) => setUserDraft(event.target.value)}
            aria-label="用户 ID"
          />
          <button type="submit">切换</button>
        </form>
      </header>

      <main id="top">
        <section className="hero">
          <div className="hero-copy">
            <p className="hero-kicker"><Sparkles size={15} /> 让每一份活跃都有回响</p>
            <h1>
              把日常积累，
              <em>兑换成喜欢。</em>
            </h1>
            <p className="hero-lead">
              实时查看积分与奖品状态，再让兑换顾问把积分缺口变成一份清晰的行动计划。
            </p>
            <div className="hero-actions">
              <a className="primary-cta" href="#awards">
                探索奖品 <ArrowRight size={18} />
              </a>
              <a className="secondary-cta" href="#advisor">
                <Bot size={18} /> 问问兑换顾问
              </a>
            </div>
          </div>

          <div className="points-ticket">
            <div className="ticket-cut ticket-cut-top" />
            <div className="ticket-cut ticket-cut-bottom" />
            <div className="ticket-heading">
              <span>AVAILABLE POINTS</span>
              <span className={`service-state ${serviceOnline ? "is-online" : ""}`}>
                {serviceOnline === null ? "检测中" : serviceOnline ? "服务在线" : "服务离线"}
              </span>
            </div>
            <div className="points-value">
              <Coins size={30} strokeWidth={1.5} />
              {loading ? (
                <LoaderCircle className="spin" size={38} />
              ) : (
                <strong>{(dashboard?.points ?? 0).toLocaleString("zh-CN")}</strong>
              )}
            </div>
            <p>用户 {userId} 的实时积分</p>
            <div className="ticket-stats">
              <div><strong>{awards.length}</strong><span>在架奖品</span></div>
              <div><strong>{readyCount}</strong><span>当前可换</span></div>
              <div><strong>{Math.max(awards.length - readyCount, 0)}</strong><span>可做规划</span></div>
            </div>
          </div>
        </section>

        <section className="exchange-note" aria-label="兑换说明">
          <div className="note-icon"><ShieldCheck size={22} /></div>
          <div>
            <strong>先确认条件，再做兑换决定</strong>
            <p>真实兑换必须先展示奖品与积分摘要，再由你明确确认；受理后请到订单页面查看最终结果。</p>
          </div>
          <span className="note-tag">SAFE BY DESIGN</span>
        </section>

        <div className="content-layout">
          <section className="awards-section" id="awards">
            <header className="section-heading">
              <div>
                <p className="eyebrow">CURATED REWARDS</p>
                <h2>本期奖品</h2>
              </div>
              <button
                className="refresh-button"
                type="button"
                disabled={refreshing}
                onClick={() => void loadDashboard(userId, true)}
              >
                <RefreshCw size={16} className={refreshing ? "spin" : ""} />
                刷新实时状态
              </button>
            </header>

            <div className="filter-row" role="group" aria-label="奖品筛选">
              {filterLabels.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className={filter === item.value ? "is-selected" : ""}
                  onClick={() => setFilter(item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>

            {loading && (
              <div className="loading-state">
                <LoaderCircle className="spin" />
                正在读取实时奖品状态…
              </div>
            )}

            {!loading && error && (
              <div className="error-state">
                <Target size={28} />
                <div><strong>数据暂时没有到达</strong><p>{error}</p></div>
                <button type="button" onClick={() => void loadDashboard(userId)}>重新加载</button>
              </div>
            )}

            {!loading && !error && visibleAwards.length === 0 && (
              <div className="empty-state">
                <Gift size={30} />
                <strong>这个分类暂时没有奖品</strong>
                <p>换一个筛选条件看看。</p>
              </div>
            )}

            <div className="award-grid">
              {visibleAwards.map((option, index) => (
                <AwardCard
                  key={option.award.awardId}
                  option={option}
                  index={index}
                  onAsk={askAboutAward}
                />
              ))}
            </div>

            <div className="process-strip">
              <div><span>01</span><CheckCircle2 size={18} /><strong>查看资格</strong><p>读取实时积分与奖品状态</p></div>
              <div><span>02</span><Bot size={18} /><strong>制定计划</strong><p>Agent 组合任务与积分缺口</p></div>
              <div><span>03</span><ShieldCheck size={18} /><strong>安全确认</strong><p>一次性凭证确保只提交一次</p></div>
            </div>
          </section>

          <ChatPanel
            userId={userId}
            externalDraft={chatDraft}
            onExternalDraftConsumed={() => setChatDraft("")}
          />
        </div>
      </main>

      <footer>
        <span>拾光奖品社 · 本地业务演示</span>
        <span>实时事实来自 Java 服务，规划由 Agent 生成</span>
      </footer>
    </div>
  );
}
