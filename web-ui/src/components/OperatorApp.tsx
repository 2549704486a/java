import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  BookOpenCheck,
  Bot,
  ClipboardList,
  KeyRound,
  LoaderCircle,
  LogOut,
  MessageSquareText,
  Send,
  ShieldCheck,
  Sparkles
} from "lucide-react";

import {
  ApiError,
  fetchCurrentOperator,
  sendOperatorChat
} from "../api";
import type { ChatMessage, CurrentOperatorResponse } from "../types";

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

export default function OperatorApp() {
  const [accessToken, setAccessToken] = useState(initialToken);
  const [tokenDraft, setTokenDraft] = useState(initialToken);
  const [operator, setOperator] = useState<CurrentOperatorResponse | null>(null);
  const [authLoading, setAuthLoading] = useState(Boolean(initialToken()));
  const [authError, setAuthError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
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
            <p><strong>权限边界</strong>当前工作台不能发布活动，也不能修改线上规则。</p>
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
      </main>
    </div>
  );
}
