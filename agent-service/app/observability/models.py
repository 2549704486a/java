from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


AgentType = Literal["USER", "OPERATOR"]
AgentRunStatus = Literal["COMPLETED", "FAILED"]


class AgentToolObservation(BaseModel):
    """一次 Tool 调用的最小观测摘要，不包含参数和业务返回正文。"""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    sequence: int = Field(ge=1)
    tool_name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    transport: str | None = Field(default=None, max_length=32)
    completed: bool
    business_success: bool
    result_code: str | None = Field(default=None, max_length=64)
    elapsed_ms: int = Field(ge=0)
    error_type: str | None = Field(default=None, max_length=128)


class AgentRequestObservation(BaseModel):
    """一次已认证 Agent 请求的终态摘要及其有序 Tool 轨迹。"""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    agent_type: AgentType
    started_at: AwareDatetime
    completed_at: AwareDatetime
    status: AgentRunStatus
    elapsed_ms: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    error_type: str | None = Field(default=None, max_length=128)
    tool_calls: tuple[AgentToolObservation, ...] = ()

    @model_validator(mode="after")
    def validate_consistency(self) -> "AgentRequestObservation":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at 不能早于 started_at")
        if (self.input_tokens is None) != (self.output_tokens is None):
            raise ValueError("input_tokens 与 output_tokens 必须同时已知或同时未知")
        if self.model_call_count == 0 and (
            self.input_tokens != 0 or self.output_tokens != 0
        ):
            raise ValueError("没有模型调用时 Token 必须为 0")

        expected_sequences = list(range(1, len(self.tool_calls) + 1))
        actual_sequences = [item.sequence for item in self.tool_calls]
        if actual_sequences != expected_sequences:
            raise ValueError("Tool sequence 必须从 1 开始并连续递增")
        if any(item.request_id != self.request_id for item in self.tool_calls):
            raise ValueError("Tool 轨迹的 request_id 必须与请求一致")
        return self

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)
