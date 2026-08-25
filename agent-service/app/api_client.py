from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx

from app.models import ToolEnvelope
from app.trace import current_correlation_id


TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
logger = logging.getLogger(__name__)


class BusinessApiError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_envelope(self) -> ToolEnvelope:
        return ToolEnvelope(
            success=False,
            code=self.code,
            data=None,
            message=self.message,
            retryable=self.retryable,
        )


class BusinessApiClient:
    """只通过 Java 业务接口获取事实，不直连数据库和中间件。"""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 3.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url.rstrip("/"))
        self._owns_client = client is None
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "BusinessApiClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def get_user_points(self, user_id: int) -> ToolEnvelope:
        return self._get(f"/agent/query/users/{user_id}/points")

    def list_available_tasks(self, user_id: int) -> ToolEnvelope:
        return self._get(f"/agent/query/users/{user_id}/tasks")

    def get_award_detail(self, award_id: int) -> ToolEnvelope:
        return self._get(f"/agent/query/awards/{award_id}")

    def list_awards(self, user_id: int, redeemable_only: bool = False) -> ToolEnvelope:
        return self._get(
            f"/agent/query/users/{user_id}/awards",
            params={"redeemableOnly": str(redeemable_only).lower()},
        )

    def check_exchange_eligibility(self, user_id: int, award_id: int) -> ToolEnvelope:
        return self._get(
            f"/agent/query/users/{user_id}/awards/{award_id}/eligibility"
        )

    def list_exchange_records(
        self,
        user_id: int,
        award_id: int | None = None,
    ) -> ToolEnvelope:
        params = {"awardId": str(award_id)} if award_id is not None else None
        return self._get(f"/agent/query/users/{user_id}/exchanges", params=params)

    def list_notifications(self, user_id: int, limit: int = 50) -> ToolEnvelope:
        return self._get(
            f"/agent/query/users/{user_id}/notifications",
            params={"limit": str(limit)},
        )

    def mark_notification_read(
        self,
        user_id: int,
        notification_id: int,
    ) -> ToolEnvelope:
        return self._post(
            f"/agent/query/users/{user_id}/notifications/{notification_id}/read",
            {},
        )

    def mark_notification_clicked(
        self,
        user_id: int,
        notification_id: int,
    ) -> ToolEnvelope:
        return self._post(
            f"/agent/query/users/{user_id}/notifications/{notification_id}/click",
            {},
        )

    def get_campaign_planning_snapshot(self, segment_key: str) -> ToolEnvelope:
        return self._get(
            f"/agent/operator/query/campaign-planning/snapshots/{segment_key}"
        )

    def create_campaign_draft(self, payload: dict) -> ToolEnvelope:
        return self._post("/agent/operator/campaigns/drafts", payload)

    def list_campaign_drafts(self, limit: int = 50) -> ToolEnvelope:
        return self._get(
            "/agent/operator/campaigns/drafts",
            params={"limit": str(limit)},
        )

    def act_on_campaign_draft(
        self,
        draft_id: int,
        action: str,
        payload: dict,
    ) -> ToolEnvelope:
        if action not in {"submit", "approve", "reject", "publish"}:
            raise ValueError(f"unsupported campaign draft action: {action}")
        return self._post(
            f"/agent/operator/campaigns/drafts/{draft_id}/{action}",
            payload,
        )

    def list_campaign_activities(self, limit: int = 50) -> ToolEnvelope:
        return self._get(
            "/agent/operator/campaigns/activities",
            params={"limit": str(limit)},
        )

    def record_campaign_metric(self, activity_id: int, payload: dict) -> ToolEnvelope:
        return self._post(
            f"/agent/operator/campaigns/activities/{activity_id}/metrics",
            payload,
        )

    def list_campaign_metrics(self, activity_id: int) -> ToolEnvelope:
        return self._get(
            f"/agent/operator/campaigns/activities/{activity_id}/metrics"
        )

    def get_campaign_funnel(self, activity_id: int) -> ToolEnvelope:
        return self._get(
            f"/agent/operator/campaigns/activities/{activity_id}/funnel"
        )

    def submit_exchange(
        self,
        *,
        user_id: int,
        award_id: int,
        request_id: str,
        idempotency_key: str,
    ) -> ToolEnvelope:
        """只提交一次非幂等写请求；网络未知状态交给上层核对，禁止自动重放。"""
        path = f"/agent/commands/users/{user_id}/awards/{award_id}/exchange"
        started = time.perf_counter()
        try:
            response = self._client.post(
                path,
                headers={
                    "X-Request-ID": request_id,
                    "Idempotency-Key": idempotency_key,
                },
                timeout=self._timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning(
                "business_api_write_unknown request_id=%s path=%s error=%s elapsed_ms=%.2f",
                request_id,
                path,
                exc.__class__.__name__,
                (time.perf_counter() - started) * 1000,
            )
            raise BusinessApiError(
                "SUBMISSION_UNKNOWN",
                "当前无法判断兑换请求是否已受理",
                False,
            ) from exc

        if response.is_error:
            raise BusinessApiError(
                "SUBMISSION_UNKNOWN",
                "当前无法判断兑换请求是否已受理",
                False,
            )
        try:
            envelope = ToolEnvelope.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise BusinessApiError(
                "SUBMISSION_UNKNOWN",
                "兑换服务返回了无法识别的数据",
                False,
            ) from exc
        logger.info(
            "business_api_write request_id=%s path=%s http_status=%s code=%s elapsed_ms=%.2f",
            request_id,
            path,
            response.status_code,
            envelope.code,
            (time.perf_counter() - started) * 1000,
        )
        return envelope

    def _post(self, path: str, payload: dict) -> ToolEnvelope:
        """Execute a state-changing request once; the caller handles unknown outcomes."""
        request_id = current_correlation_id()
        headers = {"X-Request-ID": request_id} if request_id else None
        started = time.perf_counter()
        try:
            response = self._client.post(
                path,
                json=payload,
                headers=headers,
                timeout=self._timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning(
                "business_api_write_unknown request_id=%s path=%s error=%s elapsed_ms=%.2f",
                request_id or "-",
                path,
                exc.__class__.__name__,
                (time.perf_counter() - started) * 1000,
            )
            raise BusinessApiError(
                "BUSINESS_WRITE_UNKNOWN",
                "无法确定写请求是否已经生效，请刷新事实状态后再操作",
                False,
            ) from exc
        if response.is_error:
            raise BusinessApiError(
                "BUSINESS_API_HTTP_ERROR",
                f"业务写入失败：HTTP {response.status_code}",
                False,
            )
        try:
            envelope = ToolEnvelope.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise BusinessApiError(
                "INVALID_BUSINESS_RESPONSE",
                "业务服务返回了无法识别的数据",
                False,
            ) from exc
        logger.info(
            "business_api_write request_id=%s path=%s http_status=%s code=%s elapsed_ms=%.2f",
            request_id or "-",
            path,
            response.status_code,
            envelope.code,
            (time.perf_counter() - started) * 1000,
        )
        return envelope

    def _get(self, path: str, params: dict[str, str] | None = None) -> ToolEnvelope:
        last_error: BusinessApiError | None = None
        # 从当前轨迹上下文取请求 ID，透传给 Java 服务，无需修改每个查询方法签名。
        request_id = current_correlation_id()
        headers = {"X-Request-ID": request_id} if request_id else None
        for attempt in range(self._max_retries + 1):
            started = time.perf_counter()
            try:
                response = self._client.get(
                    path,
                    params=params,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.warning(
                    "business_api_error request_id=%s path=%s attempt=%s "
                    "error=%s elapsed_ms=%.2f",
                    request_id or "-",
                    path,
                    attempt + 1,
                    exc.__class__.__name__,
                    elapsed_ms,
                )
                last_error = BusinessApiError(
                    "BUSINESS_API_UNAVAILABLE",
                    f"业务查询服务暂时不可用：{exc.__class__.__name__}",
                    True,
                )
                if attempt < self._max_retries:
                    self._backoff(attempt)
                    continue
                raise last_error from exc

            if response.status_code in TRANSIENT_STATUS_CODES:
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.warning(
                    "business_api_transient request_id=%s path=%s attempt=%s "
                    "http_status=%s elapsed_ms=%.2f",
                    request_id or "-",
                    path,
                    attempt + 1,
                    response.status_code,
                    elapsed_ms,
                )
                last_error = BusinessApiError(
                    "BUSINESS_API_TRANSIENT_ERROR",
                    f"业务查询服务暂时异常，HTTP {response.status_code}",
                    True,
                )
                if attempt < self._max_retries:
                    self._backoff(attempt)
                    continue
                raise last_error

            if response.is_error:
                raise BusinessApiError(
                    "BUSINESS_API_HTTP_ERROR",
                    f"业务查询失败，HTTP {response.status_code}",
                    False,
                )

            try:
                envelope = ToolEnvelope.model_validate(response.json())
                logger.info(
                    "business_api_call request_id=%s path=%s attempt=%s "
                    "http_status=%s code=%s elapsed_ms=%.2f",
                    request_id or "-",
                    path,
                    attempt + 1,
                    response.status_code,
                    envelope.code,
                    (time.perf_counter() - started) * 1000,
                )
                return envelope
            except (ValueError, TypeError) as exc:
                raise BusinessApiError(
                    "INVALID_BUSINESS_RESPONSE",
                    "业务查询服务返回了无法识别的数据",
                    False,
                ) from exc

        if last_error is not None:
            raise last_error
        raise BusinessApiError("UNKNOWN_ERROR", "未知业务查询错误", False)

    def _backoff(self, attempt: int) -> None:
        self._sleep(0.2 * (2**attempt))
