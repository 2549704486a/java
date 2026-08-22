import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import {
  Bot,
  CornerDownLeft,
  LoaderCircle,
  RotateCcw,
  Send,
  ShieldCheck,
  UserRound,
  X
} from "lucide-react";

import { ApiError, sendChat } from "../api";
import type { ChatMessage, PendingExchange, PendingMemoryChange } from "../types";

interface ChatPanelProps {
  accessToken: string;
  userId: number;
  externalDraft: string;
  onExternalDraftConsumed: () => void;
}

const starterPrompts = [
  "我现在能兑换什么？",
  "我有多少积分？",
  "帮我规划兑换 6 号奖品"
];

function initialMessage(): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "你好，我是你的积分兑换顾问。可以帮你查积分、挑奖品，或者把目标奖品拆成一份攒分计划。"
  };
}

export default function ChatPanel({
  accessToken,
  userId,
  externalDraft,
  onExternalDraftConsumed
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([initialMessage()]);
  const [draft, setDraft] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pendingExchange, setPendingExchange] = useState<PendingExchange | null>(null);
  const [pendingMemoryChange, setPendingMemoryChange] =
    useState<PendingMemoryChange | null>(null);
  const [sending, setSending] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!externalDraft) return;
    setDraft(externalDraft);
    onExternalDraftConsumed();
  }, [externalDraft, onExternalDraftConsumed]);

  useEffect(() => {
    setMessages([initialMessage()]);
    setSessionId(null);
    setPendingExchange(null);
    setPendingMemoryChange(null);
    setDraft("");
  }, [userId]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [messages, sending]);

  async function submit(message: string) {
    const normalized = message.trim();
    if (!normalized || sending) return;

    setDraft("");
    setSending(true);
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", content: normalized }
    ]);

    try {
      const response = await sendChat(accessToken, sessionId, normalized);
      setSessionId(response.session_id);
      setPendingExchange(response.pending_exchange);
      setPendingMemoryChange(response.pending_memory_change);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.answer,
          elapsedMs: response.elapsed_ms
        }
      ]);
    } catch (error) {
      const messageText =
        error instanceof ApiError
          ? error.message
          : "暂时无法联系兑换顾问，请确认本地 Agent 服务已经启动。";
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "assistant", content: messageText }
      ]);
    } finally {
      setSending(false);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void submit(draft);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit(draft);
    }
  }

  function resetConversation() {
    if (sending) return;
    setMessages([initialMessage()]);
    setSessionId(null);
    setPendingExchange(null);
    setPendingMemoryChange(null);
    setDraft("");
  }

  return (
    <aside className="chat-panel" id="advisor">
      <header className="chat-header">
        <div className="advisor-mark">
          <Bot size={22} />
        </div>
        <div>
          <p className="eyebrow">PERSONAL ADVISOR</p>
          <h2>兑换顾问</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          aria-label="开始新会话"
          title="开始新会话"
          onClick={resetConversation}
        >
          <RotateCcw size={17} />
        </button>
      </header>

      <div className="chat-status">
        <span className="online-dot" />
        正在服务用户 {userId}
        {sessionId && <span className="session-label">会话已延续</span>}
      </div>

      <div className="chat-viewport" ref={viewportRef}>
        {messages.map((message) => (
          <div key={message.id} className={`message-row is-${message.role}`}>
            <div className="message-avatar">
              {message.role === "assistant" ? <Bot size={16} /> : <UserRound size={16} />}
            </div>
            <div className="message-content">
              <p>{message.content}</p>
              {message.elapsedMs !== undefined && (
                <span className="message-time">回答耗时 {Math.round(message.elapsedMs)}ms</span>
              )}
            </div>
          </div>
        ))}
        {pendingExchange && (
          <section className="exchange-confirmation" aria-label="待确认兑换">
            <div className="confirmation-heading">
              <ShieldCheck size={18} />
              <div>
                <span>等待你的明确确认</span>
                <strong>{pendingExchange.awardName}</strong>
              </div>
            </div>
            <dl className="confirmation-summary">
              <div>
                <dt>当前积分</dt>
                <dd>{pendingExchange.currentPoints}</dd>
              </div>
              <div>
                <dt>需要积分</dt>
                <dd>{pendingExchange.requiredPoints}</dd>
              </div>
              <div>
                <dt>兑换后</dt>
                <dd>{pendingExchange.remainingPoints}</dd>
              </div>
            </dl>
            <p>
              凭证有效至
              {new Date(pendingExchange.expiresAt).toLocaleTimeString("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit"
              })}
            </p>
            <div className="confirmation-actions">
              <button type="button" disabled={sending} onClick={() => void submit("确认兑换")}>
                <ShieldCheck size={15} />
                确认兑换
              </button>
              <button
                className="is-secondary"
                type="button"
                disabled={sending}
                onClick={() => void submit("取消兑换")}
              >
                <X size={15} />
                取消
              </button>
            </div>
          </section>
        )}
        {pendingMemoryChange && (
          <section className="exchange-confirmation" aria-label="待确认长期记忆变更">
            <div className="confirmation-heading">
              <ShieldCheck size={18} />
              <div>
                <span>等待确认长期记忆变更</span>
                <strong>{pendingMemoryChange.summary}</strong>
              </div>
            </div>
            <p>
              草稿有效至
              {new Date(pendingMemoryChange.expiresAt).toLocaleTimeString("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit"
              })}
            </p>
            <div className="confirmation-actions">
              <button
                type="button"
                disabled={sending}
                onClick={() =>
                  void submit(
                    pendingMemoryChange.changeType.startsWith("FORGET")
                      ? "确认遗忘"
                      : "确认保存"
                  )
                }
              >
                <ShieldCheck size={15} />
                {pendingMemoryChange.changeType.startsWith("FORGET")
                  ? "确认遗忘"
                  : "确认保存"}
              </button>
              <button
                className="is-secondary"
                type="button"
                disabled={sending}
                onClick={() =>
                  void submit(
                    pendingMemoryChange.changeType.startsWith("FORGET")
                      ? "取消遗忘"
                      : "取消保存"
                  )
                }
              >
                <X size={15} />
                取消
              </button>
            </div>
          </section>
        )}
        {sending && (
          <div className="message-row is-assistant">
            <div className="message-avatar">
              <Bot size={16} />
            </div>
            <div className="message-content is-typing">
              <LoaderCircle size={16} className="spin" />
              正在查询实时业务数据…
            </div>
          </div>
        )}
      </div>

      {messages.length === 1 && (
        <div className="prompt-chips">
          {starterPrompts.map((prompt) => (
            <button key={prompt} type="button" onClick={() => void submit(prompt)}>
              {prompt}
            </button>
          ))}
        </div>
      )}

      <form className="chat-composer" onSubmit={handleSubmit}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="问问积分、任务或目标奖品…"
          rows={2}
          maxLength={2000}
          disabled={sending}
        />
        <button type="submit" disabled={sending || !draft.trim()} aria-label="发送消息">
          {sending ? <LoaderCircle size={18} className="spin" /> : <Send size={18} />}
        </button>
        <div className="composer-hint">
          <CornerDownLeft size={13} /> Enter 发送 · Shift + Enter 换行
        </div>
      </form>
    </aside>
  );
}
