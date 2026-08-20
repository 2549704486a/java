from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.runtime import AgentRuntime


logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
RuntimeFactory = Callable[[], AgentRuntime]


class ChatRequest(BaseModel):
    user_id: int = Field(gt=0)
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


class ErrorResponse(BaseModel):
    request_id: str
    session_id: str
    code: str
    message: str


def default_runtime_factory() -> AgentRuntime:
    load_dotenv()
    return AgentRuntime(Settings.from_env())


def create_app(runtime_factory: RuntimeFactory = default_runtime_factory) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        runtime = runtime_factory()
        application.state.runtime = runtime
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

    @application.get("/health")
    def health(request: Request) -> dict[str, Any]:
        return request.app.state.runtime.health()

    @application.post(
        "/v1/chat",
        response_model=ChatResponse,
        responses={503: {"model": ErrorResponse}},
    )
    def chat(
        payload: ChatRequest,
        request: Request,
        x_request_id: str | None = Header(default=None),
    ):
        # 优先沿用网关传入的请求 ID，否则生成一个，作为整条调用链的关联键。
        request_id = normalize_request_id(x_request_id)
        session_id = payload.session_id or uuid.uuid4().hex
        logger.info(
            "agent_request_started request_id=%s session_id=%s user_id=%s "
            "message_length=%s",
            request_id,
            session_id,
            payload.user_id,
            len(payload.message),
        )
        try:
            answer, elapsed_ms = request.app.state.runtime.answer(
                payload.user_id,
                session_id,
                payload.message,
                request_id,
            )
        except Exception:
            logger.exception(
                "agent_request_failed request_id=%s user_id=%s",
                request_id,
                payload.user_id,
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
            payload.user_id,
            elapsed_ms,
        )
        response = ChatResponse(
            request_id=request_id,
            session_id=session_id,
            user_id=payload.user_id,
            answer=answer,
            elapsed_ms=round(elapsed_ms, 2),
        )
        return JSONResponse(
            content=response.model_dump(),
            headers={"X-Request-ID": request_id},
        )

    return application


def normalize_request_id(candidate: str | None) -> str:
    if candidate and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


app = create_app()
