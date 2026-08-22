from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api_client import BusinessApiError
from app.auth import (
    AuthenticatedUser,
    AuthenticationError,
    JwtAuthenticator,
    authenticator_from_settings,
)
from app.config import Settings
from app.campaign_data import CampaignDataProvider, HttpCampaignDataProvider
from app.models import (
    AwardOptionData,
    PendingExchangeData,
    UserPointsData,
)
from app.runtime import AgentRuntime
from app.operator_auth import (
    AuthenticatedOperator,
    OperatorAuthenticator,
    OperatorPermissionError,
    operator_authenticator_from_settings,
)
from app.operator_tools import (
    CAMPAIGN_DRAFT,
    CAMPAIGN_READ,
    CampaignDraftInput,
    build_operator_tools,
)
from app.trace import capture_tool_trace


logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
RuntimeFactory = Callable[[], AgentRuntime]
AuthenticatorFactory = Callable[[], JwtAuthenticator]
OperatorAuthenticatorFactory = Callable[[], OperatorAuthenticator]
CampaignDataProviderFactory = Callable[[AgentRuntime], CampaignDataProvider]
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


def create_app(
    runtime_factory: RuntimeFactory = default_runtime_factory,
    authenticator_factory: AuthenticatorFactory = default_authenticator_factory,
    operator_authenticator_factory: OperatorAuthenticatorFactory = (
        default_operator_authenticator_factory
    ),
    campaign_data_provider_factory: CampaignDataProviderFactory = (
        default_campaign_data_provider_factory
    ),
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        authenticator = authenticator_factory()
        runtime = runtime_factory()
        application.state.runtime = runtime
        application.state.authenticator = authenticator
        application.state.operator_authenticator = operator_authenticator_factory()
        application.state.campaign_data_provider = campaign_data_provider_factory(runtime)
        logger.info("agent_http_started health=%s", runtime.health())
        try:
            yield
        finally:
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
    def chat(
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
            answer, elapsed_ms = request.app.state.runtime.answer(
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
            pending_exchange=request.app.state.runtime.pending_exchange(
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
        )
        draft_tool = next(item for item in tools if item.name == "draft_campaign_plan")
        with capture_tool_trace(request_id):
            result = draft_tool.invoke(payload.model_dump())
        return JSONResponse(content=result, headers={"X-Request-ID": request_id})

    # API 路由必须先注册；根路径静态挂载放在最后，避免吞掉 /v1 和 /docs。
    if FRONTEND_DIST.is_dir():
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
