from __future__ import annotations

import asyncio
import logging
import re
import threading
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.api_client import BusinessApiError
from app.auth import (
    AuthenticatedUser,
    AuthenticationError,
    JwtAuthenticator,
    authenticator_from_settings,
)
from app.config import Settings
from app.operator.campaign_data import CampaignDataProvider, HttpCampaignDataProvider
from app.models import (
    AwardOptionData,
    ExchangeRecordData,
    PendingExchangeData,
    UserNotificationData,
    UserPointsData,
)
from app.runtime import AgentRuntime
from app.operator.auth import (
    AuthenticatedOperator,
    OperatorAuthenticator,
    OperatorPermissionError,
    operator_authenticator_from_settings,
)
from app.operator.agent import OperatorAgentRuntime
from app.operator.tools import (
    CAMPAIGN_DRAFT,
    CAMPAIGN_METRIC,
    CAMPAIGN_PUBLISH,
    CAMPAIGN_READ,
    CAMPAIGN_REVIEW,
    CampaignDraftInput,
    OperatorKnowledgeSearchInput,
    build_operator_tools,
)
from app.trace import capture_tool_trace


logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
RuntimeFactory = Callable[[], AgentRuntime]
AuthenticatorFactory = Callable[[], JwtAuthenticator]
OperatorAuthenticatorFactory = Callable[[], OperatorAuthenticator]
CampaignDataProviderFactory = Callable[[AgentRuntime], CampaignDataProvider]
OperatorAgentRuntimeFactory = Callable[
    [AgentRuntime, CampaignDataProvider],
    OperatorAgentRuntime,
]
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "web-ui" / "dist"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=128)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message 不能为空")
        return stripped

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not REQUEST_ID_PATTERN.fullmatch(stripped):
            raise ValueError("session_id 格式不合法")
        return stripped


class ChatResponse(BaseModel):
    request_id: str
    session_id: str
    user_id: int
    answer: str
    elapsed_ms: float
    pending_exchange: PendingExchangeData | None = None


class ErrorResponse(BaseModel):
    request_id: str
    session_id: str
    code: str
    message: str


class DashboardResponse(BaseModel):
    request_id: str
    user_id: int
    points: int
    awards: list[AwardOptionData]


class OrdersResponse(BaseModel):
    request_id: str
    user_id: int
    records: list[ExchangeRecordData]


class NotificationsResponse(BaseModel):
    request_id: str
    user_id: int
    notifications: list[UserNotificationData]


class NotificationActionResponse(BaseModel):
    request_id: str
    user_id: int
    notification: UserNotificationData


class DashboardErrorResponse(BaseModel):
    request_id: str
    code: str
    message: str


class CurrentUserResponse(BaseModel):
    user_id: int


class AuthenticationErrorResponse(BaseModel):
    request_id: str
    code: str
    message: str


class OperatorErrorResponse(BaseModel):
    request_id: str
    code: str
    message: str


class OperatorCurrentResponse(BaseModel):
    operator_id: str
    permissions: list[str]


class OperatorChatResponse(BaseModel):
    request_id: str
    session_id: str
    operator_id: str
    answer: str
    elapsed_ms: float


class CampaignWorkflowActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0)
    comment: str | None = Field(default=None, max_length=500)


class CampaignEffectMetricRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: str = Field(min_length=1, max_length=64)
    metric_value: float
    sample_size: int = Field(ge=1)
    measured_at: AwareDatetime
    source_ref: str | None = Field(default=None, max_length=255)


class CampaignSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_key: str = Field(
        default="DEMO_BASELINE_V1",
        min_length=1,
        max_length=64,
    )


def default_runtime_factory() -> AgentRuntime:
    load_dotenv()
    return AgentRuntime(Settings.from_env())


def default_authenticator_factory() -> JwtAuthenticator:
    load_dotenv()
    return authenticator_from_settings(Settings.from_env())


def default_operator_authenticator_factory() -> OperatorAuthenticator:
    load_dotenv()
    return operator_authenticator_from_settings(Settings.from_env())


def default_campaign_data_provider_factory(
    runtime: AgentRuntime,
) -> CampaignDataProvider:
    return HttpCampaignDataProvider(runtime.client)


def default_operator_agent_runtime_factory(
    runtime: AgentRuntime,
    data_provider: CampaignDataProvider,
) -> OperatorAgentRuntime:
    return OperatorAgentRuntime(
        settings=runtime.settings,
        data_provider=data_provider,
        business_client=runtime.client,
        knowledge_search=runtime.operator_knowledge_search,
    )


def create_app(
    runtime_factory: RuntimeFactory = default_runtime_factory,
    authenticator_factory: AuthenticatorFactory = default_authenticator_factory,
    operator_authenticator_factory: OperatorAuthenticatorFactory = (
        default_operator_authenticator_factory
    ),
    campaign_data_provider_factory: CampaignDataProviderFactory = (
        default_campaign_data_provider_factory
    ),
    operator_agent_runtime_factory: OperatorAgentRuntimeFactory = (
        default_operator_agent_runtime_factory
    ),
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        authenticator = authenticator_factory()
        runtime = runtime_factory()
        try:
            # MCP 模式必须在 ready 前完成 Tool 发现；失败会直接终止应用启动。
            await runtime.initialize()
            application.state.runtime = runtime
            application.state.authenticator = authenticator
            application.state.operator_authenticator = (
                operator_authenticator_factory()
            )
            application.state.campaign_data_provider = (
                campaign_data_provider_factory(runtime)
            )
            application.state.operator_agent_runtime = None
            application.state.operator_agent_runtime_factory = (
                operator_agent_runtime_factory
            )
            application.state.operator_agent_runtime_lock = threading.Lock()
            logger.info("agent_http_started health=%s", runtime.health())
            yield
        finally:
            # 初始化失败发生在 yield 之前，也必须释放 Runtime 已装配的资源。
            operator_runtime = getattr(
                application.state,
                "operator_agent_runtime",
                None,
            )
            if operator_runtime is not None:
                operator_runtime.close()
            runtime.close()
            logger.info("agent_http_stopped")

    application = FastAPI(
        title="积分规划 Agent API",
        version="1.0.0",
        lifespan=lifespan,
    )

    @application.exception_handler(AuthenticationError)
    def authentication_error_handler(
        request: Request,
        exc: AuthenticationError,
    ) -> JSONResponse:
        request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        body = AuthenticationErrorResponse(
            request_id=request_id,
            code=exc.code,
            message=exc.message,
        )
        return JSONResponse(
            status_code=(
                503 if exc.code == "OPERATOR_AUTH_NOT_CONFIGURED" else 401
            ),
            content=body.model_dump(),
            headers={"X-Request-ID": request_id, "WWW-Authenticate": "Bearer"},
        )

    @application.exception_handler(OperatorPermissionError)
    def operator_permission_error_handler(
        request: Request,
        exc: OperatorPermissionError,
    ) -> JSONResponse:
        request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        body = OperatorErrorResponse(
            request_id=request_id,
            code="OPERATOR_PERMISSION_DENIED",
            message=str(exc),
        )
        return JSONResponse(
            status_code=403,
            content=body.model_dump(),
            headers={"X-Request-ID": request_id},
        )

    @application.get("/health")
    def health(request: Request) -> dict[str, Any]:
        return request.app.state.runtime.health()

    @application.get(
        "/v1/me",
        response_model=CurrentUserResponse,
        responses={401: {"model": AuthenticationErrorResponse}},
    )
    def current_user(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> CurrentUserResponse:
        identity = authenticate_request(request, authorization)
        return CurrentUserResponse(user_id=identity.user_id)

    @application.post(
        "/v1/chat",
        response_model=ChatResponse,
        responses={
            401: {"model": AuthenticationErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def chat(
        payload: ChatRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        identity = authenticate_request(request, authorization)
        user_id = identity.user_id
        # 优先沿用网关传入的请求 ID，否则生成一个，作为整条调用链的关联键。
        request_id = normalize_request_id(x_request_id)
        session_id = payload.session_id or uuid.uuid4().hex
        logger.info(
            "agent_request_started request_id=%s session_id=%s user_id=%s "
            "message_length=%s",
            request_id,
            session_id,
            user_id,
            len(payload.message),
        )
        try:
            answer, elapsed_ms = await request.app.state.runtime.answer(
                user_id,
                session_id,
                payload.message,
                request_id,
            )
        except Exception:
            logger.exception(
                "agent_request_failed request_id=%s user_id=%s",
                request_id,
                user_id,
            )
            error = ErrorResponse(
                request_id=request_id,
                session_id=session_id,
                code="AGENT_SERVICE_UNAVAILABLE",
                message="Agent 服务暂时不可用，请稍后重试",
            )
            return JSONResponse(
                status_code=503,
                content=error.model_dump(),
                headers={"X-Request-ID": request_id},
            )

        logger.info(
            "agent_request_completed request_id=%s session_id=%s user_id=%s "
            "elapsed_ms=%.2f",
            request_id,
            session_id,
            user_id,
            elapsed_ms,
        )
        response = ChatResponse(
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            answer=answer,
            elapsed_ms=round(elapsed_ms, 2),
            pending_exchange=await asyncio.to_thread(
                request.app.state.runtime.pending_exchange,
                user_id,
                session_id,
            ),
        )
        return JSONResponse(
            content=response.model_dump(mode="json", by_alias=True),
            headers={"X-Request-ID": request_id},
        )

    @application.get(
        "/v1/dashboard",
        response_model=DashboardResponse,
        responses={
            401: {"model": AuthenticationErrorResponse},
            404: {"model": DashboardErrorResponse},
            502: {"model": DashboardErrorResponse},
            503: {"model": DashboardErrorResponse},
        },
    )
    def dashboard(
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        """聚合奖品中心首屏数据，避免浏览器理解两个 Java 接口的信封协议。"""
        user_id = authenticate_request(request, authorization).user_id
        request_id = normalize_request_id(x_request_id)
        try:
            # 绑定请求 ID 后，BusinessApiClient 会自动将它透传给 Java 服务。
            with capture_tool_trace(request_id):
                points_envelope = request.app.state.runtime.client.get_user_points(
                    user_id
                )
                awards_envelope = request.app.state.runtime.client.list_awards(user_id)

            failed_envelope = next(
                (
                    envelope
                    for envelope in (points_envelope, awards_envelope)
                    if not envelope.success
                ),
                None,
            )
            if failed_envelope is not None:
                status_code = 404 if failed_envelope.code == "USER_NOT_FOUND" else 502
                return dashboard_error(
                    request_id,
                    failed_envelope.code,
                    failed_envelope.message,
                    status_code,
                )

            points = UserPointsData.model_validate(points_envelope.data)
            awards = [
                AwardOptionData.model_validate(item)
                for item in (awards_envelope.data or [])
            ]
        except BusinessApiError as exc:
            logger.warning(
                "dashboard_business_api_failed request_id=%s user_id=%s code=%s",
                request_id,
                user_id,
                exc.code,
            )
            return dashboard_error(
                request_id,
                exc.code,
                "业务查询服务暂时不可用，请稍后重试",
                503 if exc.retryable else 502,
            )
        except (TypeError, ValueError):
            logger.exception(
                "dashboard_invalid_response request_id=%s user_id=%s",
                request_id,
                user_id,
            )
            return dashboard_error(
                request_id,
                "INVALID_BUSINESS_RESPONSE",
                "业务查询数据格式异常",
                502,
            )

        response = DashboardResponse(
            request_id=request_id,
            user_id=user_id,
            points=points.points,
            awards=awards,
        )
        return JSONResponse(
            content=response.model_dump(mode="json", by_alias=True),
            headers={"X-Request-ID": request_id},
        )

    @application.get(
        "/v1/orders",
        response_model=OrdersResponse,
        responses={
            401: {"model": AuthenticationErrorResponse},
            502: {"model": DashboardErrorResponse},
            503: {"model": DashboardErrorResponse},
        },
    )
    def orders(
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        """读取当前登录用户的真实兑换记录，不接受客户端指定 user_id。"""
        user_id = authenticate_request(request, authorization).user_id
        request_id = normalize_request_id(x_request_id)
        try:
            with capture_tool_trace(request_id):
                envelope = request.app.state.runtime.client.list_exchange_records(user_id)
            if not envelope.success:
                status_code = 404 if envelope.code == "USER_NOT_FOUND" else 502
                return dashboard_error(
                    request_id,
                    envelope.code,
                    envelope.message,
                    status_code,
                )
            records = [
                ExchangeRecordData.model_validate(item)
                for item in (envelope.data or [])
            ]
        except BusinessApiError as exc:
            return dashboard_error(
                request_id,
                exc.code,
                "兑换记录服务暂时不可用，请稍后重试",
                503 if exc.retryable else 502,
            )
        except (TypeError, ValueError):
            logger.exception(
                "orders_invalid_response request_id=%s user_id=%s",
                request_id,
                user_id,
            )
            return dashboard_error(
                request_id,
                "INVALID_BUSINESS_RESPONSE",
                "兑换记录数据格式异常",
                502,
            )

        response = OrdersResponse(
            request_id=request_id,
            user_id=user_id,
            records=records,
        )
        return JSONResponse(
            content=response.model_dump(mode="json", by_alias=True),
            headers={"X-Request-ID": request_id},
        )

    @application.get(
        "/v1/notifications",
        response_model=NotificationsResponse,
        responses={401: {"model": AuthenticationErrorResponse}},
    )
    def notifications(
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        user_id = authenticate_request(request, authorization).user_id
        request_id = normalize_request_id(x_request_id)
        try:
            envelope = request.app.state.runtime.client.list_notifications(user_id)
            if not envelope.success:
                return dashboard_error(request_id, envelope.code, envelope.message, 502)
            items = [
                UserNotificationData.model_validate(item)
                for item in (envelope.data or [])
            ]
        except BusinessApiError as exc:
            return dashboard_error(
                request_id,
                exc.code,
                "站内消息服务暂时不可用，请稍后重试",
                503 if exc.retryable else 502,
            )
        response = NotificationsResponse(
            request_id=request_id,
            user_id=user_id,
            notifications=items,
        )
        return JSONResponse(
            content=response.model_dump(mode="json", by_alias=True),
            headers={"X-Request-ID": request_id},
        )

    @application.post(
        "/v1/notifications/{notification_id}/{action}",
        response_model=NotificationActionResponse,
        responses={401: {"model": AuthenticationErrorResponse}},
    )
    def change_notification_status(
        notification_id: int,
        action: str,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        user_id = authenticate_request(request, authorization).user_id
        request_id = normalize_request_id(x_request_id)
        if action not in {"read", "click"}:
            return dashboard_error(
                request_id,
                "INVALID_NOTIFICATION_ACTION",
                "不支持的站内消息操作",
                400,
            )
        try:
            if action == "read":
                envelope = request.app.state.runtime.client.mark_notification_read(
                    user_id,
                    notification_id,
                )
            else:
                envelope = request.app.state.runtime.client.mark_notification_clicked(
                    user_id,
                    notification_id,
                )
            if not envelope.success:
                status = 404 if envelope.code == "NOTIFICATION_NOT_FOUND" else 502
                return dashboard_error(request_id, envelope.code, envelope.message, status)
            item = UserNotificationData.model_validate(envelope.data)
        except BusinessApiError as exc:
            return dashboard_error(
                request_id,
                exc.code,
                "站内消息状态暂时无法更新，请稍后重试",
                503 if exc.retryable else 502,
            )
        response = NotificationActionResponse(
            request_id=request_id,
            user_id=user_id,
            notification=item,
        )
        return JSONResponse(
            content=response.model_dump(mode="json", by_alias=True),
            headers={"X-Request-ID": request_id},
        )

    @application.get(
        "/v1/operator/me",
        response_model=OperatorCurrentResponse,
        responses={401: {"model": AuthenticationErrorResponse}},
    )
    def current_operator(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> OperatorCurrentResponse:
        operator = authenticate_operator_request(request, authorization)
        return OperatorCurrentResponse(
            operator_id=operator.operator_id,
            permissions=sorted(operator.permissions),
        )

    @application.post(
        "/v1/operator/chat",
        response_model=OperatorChatResponse,
        responses={
            401: {"model": AuthenticationErrorResponse},
            403: {"model": OperatorErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def operator_chat(
        payload: ChatRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_READ)
        request_id = normalize_request_id(x_request_id)
        session_id = payload.session_id or uuid.uuid4().hex
        logger.info(
            "operator_agent_request_started request_id=%s session_id=%s operator_id=%s message_length=%s",
            request_id,
            session_id,
            operator.operator_id,
            len(payload.message),
        )
        try:
            answer, elapsed_ms = get_operator_agent_runtime(request).answer(
                operator=operator,
                session_id=session_id,
                message=payload.message,
                request_id=request_id,
            )
        except Exception:
            logger.exception(
                "operator_agent_request_failed request_id=%s session_id=%s operator_id=%s",
                request_id,
                session_id,
                operator.operator_id,
            )
            return JSONResponse(
                status_code=503,
                content=ErrorResponse(
                    request_id=request_id,
                    session_id=session_id,
                    code="OPERATOR_AGENT_UNAVAILABLE",
                    message="运营助手暂时不可用，请稍后再试",
                ).model_dump(),
                headers={"X-Request-ID": request_id},
            )
        response = OperatorChatResponse(
            request_id=request_id,
            session_id=session_id,
            operator_id=operator.operator_id,
            answer=answer,
            elapsed_ms=elapsed_ms,
        )
        return JSONResponse(
            content=response.model_dump(),
            headers={"X-Request-ID": request_id},
        )

    @application.get(
        "/v1/operator/campaign/snapshots/{segment_key}",
        responses={
            401: {"model": AuthenticationErrorResponse},
            403: {"model": OperatorErrorResponse},
            503: {"model": OperatorErrorResponse},
        },
    )
    def campaign_snapshot(
        segment_key: str,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_READ)
        tool = build_operator_tools(
            request.app.state.campaign_data_provider,
            operator,
            knowledge_search=getattr(
                request.app.state.runtime,
                "operator_knowledge_search",
                None,
            ),
        )[0]
        with capture_tool_trace(request_id):
            result = tool.invoke({"target_segment_key": segment_key})
        return JSONResponse(content=result, headers={"X-Request-ID": request_id})

    @application.post(
        "/v1/operator/campaign/drafts",
        responses={
            401: {"model": AuthenticationErrorResponse},
            403: {"model": OperatorErrorResponse},
            503: {"model": OperatorErrorResponse},
        },
    )
    def draft_campaign(
        payload: CampaignDraftInput,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_READ, CAMPAIGN_DRAFT)
        tools = build_operator_tools(
            request.app.state.campaign_data_provider,
            operator,
            knowledge_search=getattr(
                request.app.state.runtime,
                "operator_knowledge_search",
                None,
            ),
            business_client=(
                request.app.state.runtime.client
                if hasattr(
                    request.app.state.runtime.client,
                    "create_campaign_draft",
                )
                else None
            ),
        )
        draft_tool = next(item for item in tools if item.name == "draft_campaign_plan")
        with capture_tool_trace(request_id):
            result = draft_tool.invoke(payload.model_dump())
        return JSONResponse(content=result, headers={"X-Request-ID": request_id})

    @application.get("/v1/operator/campaign/drafts")
    def list_campaign_drafts(
        request: Request,
        limit: int = 50,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_READ)
        return operator_business_response(
            request_id,
            lambda: request.app.state.runtime.client.list_campaign_drafts(limit),
        )

    @application.post("/v1/operator/campaign/drafts/{draft_id}/submit")
    def submit_campaign_draft(
        draft_id: int,
        payload: CampaignWorkflowActionRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_DRAFT)
        return campaign_draft_action_response(
            request, request_id, operator, draft_id, "submit", payload
        )

    @application.post("/v1/operator/campaign/drafts/{draft_id}/approve")
    def approve_campaign_draft(
        draft_id: int,
        payload: CampaignWorkflowActionRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_REVIEW)
        return campaign_draft_action_response(
            request, request_id, operator, draft_id, "approve", payload
        )

    @application.post("/v1/operator/campaign/drafts/{draft_id}/reject")
    def reject_campaign_draft(
        draft_id: int,
        payload: CampaignWorkflowActionRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_REVIEW)
        return campaign_draft_action_response(
            request, request_id, operator, draft_id, "reject", payload
        )

    @application.post("/v1/operator/campaign/drafts/{draft_id}/publish")
    def publish_campaign_draft(
        draft_id: int,
        payload: CampaignWorkflowActionRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_PUBLISH)
        return campaign_draft_action_response(
            request, request_id, operator, draft_id, "publish", payload
        )

    @application.get("/v1/operator/campaign/activities")
    def list_campaign_activities(
        request: Request,
        limit: int = 50,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_READ)
        return operator_business_response(
            request_id,
            lambda: request.app.state.runtime.client.list_campaign_activities(limit),
        )

    @application.post("/v1/operator/campaign/activities/{activity_id}/metrics")
    def record_campaign_metric(
        activity_id: int,
        payload: CampaignEffectMetricRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_METRIC)
        return operator_business_response(
            request_id,
            lambda: request.app.state.runtime.client.record_campaign_metric(
                activity_id,
                {
                    "operatorId": operator.operator_id,
                    "metricName": payload.metric_name,
                    "metricValue": payload.metric_value,
                    "sampleSize": payload.sample_size,
                    "measuredAt": payload.measured_at.isoformat(),
                    "sourceRef": payload.source_ref,
                },
            ),
        )

    @application.get("/v1/operator/campaign/activities/{activity_id}/metrics")
    def list_campaign_metrics(
        activity_id: int,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_READ)
        return operator_business_response(
            request_id,
            lambda: request.app.state.runtime.client.list_campaign_metrics(activity_id),
        )

    @application.get("/v1/operator/campaign/activities/{activity_id}/funnel")
    def get_campaign_funnel(
        activity_id: int,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_READ)
        return operator_business_response(
            request_id,
            lambda: request.app.state.runtime.client.get_campaign_funnel(activity_id),
        )

    @application.post("/v1/operator/campaign/activities/{activity_id}/simulate")
    def simulate_campaign(
        activity_id: int,
        payload: CampaignSimulationRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_METRIC)
        return operator_business_response(
            request_id,
            lambda: request.app.state.runtime.client.simulate_campaign(
                activity_id,
                payload.scenario_key,
            ),
        )

    @application.post(
        "/v1/operator/knowledge/search",
        responses={
            401: {"model": AuthenticationErrorResponse},
            403: {"model": OperatorErrorResponse},
            503: {"model": OperatorErrorResponse},
        },
    )
    def search_operator_knowledge(
        payload: OperatorKnowledgeSearchInput,
        request: Request,
        x_request_id: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        request_id = normalize_request_id(x_request_id)
        operator = authenticate_operator_request(request, authorization)
        require_operator_permission(operator, CAMPAIGN_READ)
        tools = build_operator_tools(
            request.app.state.campaign_data_provider,
            operator,
            knowledge_search=getattr(
                request.app.state.runtime,
                "operator_knowledge_search",
                None,
            ),
        )
        knowledge_tool = next(
            (item for item in tools if item.name == "search_operator_knowledge"),
            None,
        )
        if knowledge_tool is None:
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "code": "OPERATOR_KNOWLEDGE_NOT_CONFIGURED",
                    "data": None,
                    "message": "运营知识检索未启用",
                    "retryable": True,
                },
                headers={"X-Request-ID": request_id},
            )
        with capture_tool_trace(request_id):
            result = knowledge_tool.invoke(payload.model_dump())
        return JSONResponse(content=result, headers={"X-Request-ID": request_id})

    # React 的客户端路由需要显式回退到同一份 index.html；StaticFiles
    # 的 html 模式只处理真实目录，不会自动处理 /operator 深链接。
    if FRONTEND_DIST.is_dir():
        @application.get("/operator", include_in_schema=False)
        @application.get("/operator/", include_in_schema=False)
        def operator_page() -> FileResponse:
            return FileResponse(FRONTEND_DIST / "index.html")

        # API 路由必须先注册；根路径静态挂载放在最后，避免吞掉 /v1 和 /docs。
        application.mount(
            "/",
            StaticFiles(directory=FRONTEND_DIST, html=True),
            name="web-ui",
        )

    return application


def normalize_request_id(candidate: str | None) -> str:
    if candidate and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def authenticate_request(
    request: Request,
    authorization: str | None,
) -> AuthenticatedUser:
    return request.app.state.authenticator.authenticate(authorization)


def authenticate_operator_request(
    request: Request,
    authorization: str | None,
) -> AuthenticatedOperator:
    return request.app.state.operator_authenticator.authenticate(authorization)


def require_operator_permission(
    operator: AuthenticatedOperator,
    *required: str,
) -> None:
    missing = [permission for permission in required if permission not in operator.permissions]
    if missing:
        raise OperatorPermissionError(f"运营身份缺少权限：{', '.join(missing)}")


def campaign_draft_action_response(
    request: Request,
    request_id: str,
    operator: AuthenticatedOperator,
    draft_id: int,
    action: str,
    payload: CampaignWorkflowActionRequest,
) -> JSONResponse:
    # Operator identity comes from the token, never from browser-controlled JSON.
    return operator_business_response(
        request_id,
        lambda: request.app.state.runtime.client.act_on_campaign_draft(
            draft_id,
            action,
            {
                "operatorId": operator.operator_id,
                "version": payload.version,
                "comment": payload.comment,
            },
        ),
    )


def operator_business_response(
    request_id: str,
    operation: Callable[[], Any],
) -> JSONResponse:
    try:
        result = operation()
    except BusinessApiError as exc:
        return JSONResponse(
            status_code=503 if exc.retryable else 409,
            content={
                "success": False,
                "code": exc.code,
                "data": None,
                "message": exc.message,
                "retryable": exc.retryable,
            },
            headers={"X-Request-ID": request_id},
        )
    return JSONResponse(
        content=result.model_dump(mode="json"),
        headers={"X-Request-ID": request_id},
    )


def get_operator_agent_runtime(request: Request) -> OperatorAgentRuntime:
    runtime = request.app.state.operator_agent_runtime
    if runtime is not None:
        return runtime
    # 首次运营对话时再创建模型运行时，避免只使用用户端时增加启动成本。
    with request.app.state.operator_agent_runtime_lock:
        runtime = request.app.state.operator_agent_runtime
        if runtime is None:
            runtime = request.app.state.operator_agent_runtime_factory(
                request.app.state.runtime,
                request.app.state.campaign_data_provider,
            )
            request.app.state.operator_agent_runtime = runtime
        return runtime


def dashboard_error(
    request_id: str,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    error = DashboardErrorResponse(
        request_id=request_id,
        code=code,
        message=message,
    )
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(),
        headers={"X-Request-ID": request_id},
    )


app = create_app()
