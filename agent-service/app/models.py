from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolEnvelope(BaseModel):
    success: bool
    code: str
    data: Any | None = None
    message: str
    retryable: bool = False


class EligibilityData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: int = Field(alias="userId")
    award_id: int = Field(alias="awardId")
    eligible: bool
    reason_code: str = Field(alias="reasonCode")
    reason: str
    current_points: int = Field(alias="currentPoints")
    required_points: int = Field(alias="requiredPoints")
    points_gap: int = Field(alias="pointsGap")


class AwardData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    award_id: int = Field(alias="awardId")
    name: str
    required_points: int = Field(alias="requiredPoints")
    inventory: int


class TaskData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: int = Field(alias="taskId")
    task_name: str = Field(alias="taskName")
    reward_points: int = Field(alias="rewardPoints")
    status: Literal["AVAILABLE", "COMPLETED_UNCLAIMED", "REWARDED"]
    description: str | None = None


class RecommendedTask(BaseModel):
    task_id: int
    task_name: str
    reward_points: int
    status: str
    action: Literal["CLAIM_REWARD", "COMPLETE_TASK"]


class PointsPlan(BaseModel):
    status: Literal[
        "READY_TO_EXCHANGE",
        "PLAN_READY",
        "INSUFFICIENT_TASK_REWARDS",
        "BLOCKED",
        "QUERY_FAILED",
    ]
    reason_code: str
    message: str
    user_id: int
    award_id: int
    award_name: str | None = None
    current_points: int | None = None
    required_points: int | None = None
    points_gap: int | None = None
    recommended_points: int = 0
    projected_points: int | None = None
    remaining_gap: int | None = None
    recommended_tasks: list[RecommendedTask] = Field(default_factory=list)

