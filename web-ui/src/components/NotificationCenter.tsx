import { useEffect, useState } from "react";
import { Bell, BellRing, Check, LoaderCircle, MousePointerClick, RefreshCw } from "lucide-react";

import { ApiError, fetchNotifications, updateNotification } from "../api";
import type { UserNotification } from "../types";

interface NotificationCenterProps {
  accessToken: string;
}

function replaceNotification(
  notifications: UserNotification[],
  updated: UserNotification
): UserNotification[] {
  return notifications.map((item) => (item.id === updated.id ? updated : item));
}

export default function NotificationCenter({ accessToken }: NotificationCenterProps) {
  const [notifications, setNotifications] = useState<UserNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<number | null>(null);

  async function load(silent = false) {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const response = await fetchNotifications(accessToken);
      setNotifications(response.notifications);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "站内消息暂时无法加载");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // 活动投放是异步链路，低频轮询让新消息无需刷新整页即可出现。
    const timer = window.setInterval(() => void load(true), 15000);
    return () => window.clearInterval(timer);
  }, [accessToken]);

  async function changeStatus(notification: UserNotification, action: "read" | "click") {
    setUpdatingId(notification.id);
    setError(null);
    try {
      const response = await updateNotification(accessToken, notification.id, action);
      setNotifications((current) => replaceNotification(current, response.notification));
      if (action === "click") {
        document.getElementById("awards")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "消息状态暂时无法更新");
    } finally {
      setUpdatingId(null);
    }
  }

  const unreadCount = notifications.filter((item) => item.status === "UNREAD").length;

  return (
    <section className="notification-section" id="notifications">
      <header className="section-heading">
        <div>
          <p className="eyebrow">ACTIVITY INBOX</p>
          <h2>活动消息</h2>
        </div>
        <div className="notification-heading-actions">
          <span className={unreadCount > 0 ? "unread-count has-unread" : "unread-count"}>
            {unreadCount > 0 ? `${unreadCount} 条未读` : "全部已读"}
          </span>
          <button className="refresh-button" type="button" disabled={loading} onClick={() => void load()}>
            <RefreshCw size={16} className={loading ? "spin" : ""} />
            刷新消息
          </button>
        </div>
      </header>

      {loading && notifications.length === 0 && (
        <div className="notification-empty"><LoaderCircle className="spin" size={20} /> 正在读取活动消息…</div>
      )}
      {error && <div className="notification-error">{error}</div>}
      {!loading && !error && notifications.length === 0 && (
        <div className="notification-empty"><Bell size={20} /> 暂时没有新的活动消息。</div>
      )}

      <div className="notification-list">
        {notifications.map((notification) => (
          <article
            className={`notification-card is-${notification.status.toLowerCase()}`}
            key={notification.id}
          >
            <div className="notification-icon">
              {notification.status === "UNREAD" ? <BellRing size={20} /> : <Check size={20} />}
            </div>
            <div className="notification-copy">
              <span>活动 {notification.activityId} · {new Date(notification.createdAt).toLocaleString("zh-CN")}</span>
              <strong>{notification.title}</strong>
              <p>{notification.content}</p>
            </div>
            <div className="notification-actions">
              {notification.status === "UNREAD" && (
                <button
                  type="button"
                  disabled={updatingId === notification.id}
                  onClick={() => void changeStatus(notification, "read")}
                >
                  <Check size={15} /> 标为已读
                </button>
              )}
              {notification.status !== "CLICKED" && (
                <button
                  className="is-primary"
                  type="button"
                  disabled={updatingId === notification.id}
                  onClick={() => void changeStatus(notification, "click")}
                >
                  <MousePointerClick size={15} /> 查看活动
                </button>
              )}
              {notification.status === "CLICKED" && <span className="viewed-label">已查看活动</span>}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
