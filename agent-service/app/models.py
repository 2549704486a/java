from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolEnvelope(BaseModel):
    success: bool
    code: str
    data: Any | None = None
    message: str
    retryable: bool = False


class UserPointsData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: int = Field(alias="userId")
    points: int = Field(ge=0)


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
    cover_url: str | None = Field(default=None, alias="coverUrl")
    award_type: int | None = Field(default=None, alias="awardType")
    required_points: int = Field(alias="requiredPoints")
    inventory: int
    start_time: datetime | None = Field(default=None, alias="startTime")
    end_time: datetime | None = Field(default=None, alias="endTime")
    over_sell_allowed: bool = Field(default=False, alias="overSellAllowed")


class AwardOptionData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    award: AwardData
    redeemable: bool
    points_gap: int = Field(alias="pointsGap", ge=0)
    reason_code: str = Field(alias="reasonCode")


class ExchangePreparationData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    confirmation_id: str = Field(alias="confirmationId")
    status: Literal["AWAITING_CONFIRMATION"]
    award_id: int = Field(alias="awardId")
    award_name: str = Field(alias="awardName")
    current_points: int = Field(alias="currentPoints")
    required_points: int = Field(alias="requiredPoints")
    remaining_points: int = Field(alias="remainingPoints")
    expires_at: datetime = Field(alias="expiresAt")


class PendingExchangeData(BaseModel):
    """可安全返回浏览器的待确认摘要，不包含一次性确认凭证。"""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["AWAITING_CONFIRMATION"]
    award_id: int = Field(alias="awardId")
    award_name: str = Field(alias="awardName")
    current_points: int = Field(alias="currentPoints")
    required_points: int = Field(alias="requiredPoints")
    remaining_points: int = Field(alias="remainingPoints")
    expires_at: datetime = Field(alias="expiresAt")


class RecommendedAward(BaseModel):
    award_id: int
    name: str
    required_points: int
    inventory: int
    remaining_points: int


class AwardRecommendation(BaseModel):
    status: Literal[
        "RECOMMENDATIONS_READY",
        "NO_REDEEMABLE_AWARDS",
        "QUERY_FAILED",
    ]
    reason_code: str
    message: str
    user_id: int
    current_points: int | None = None
    recommendations: list[RecommendedAward] = Field(default_factory=list)


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


class RedemptionGoalData(BaseModel):
    """用户明确确认过的跨会话兑换目标。"""

    model_config = ConfigDict(populate_by_name=True)

    user_id: int = Field(alias="userId")
    target_award_id: int = Field(alias="targetAwardId", gt=0)
    target_award_name: str = Field(alias="targetAwardName", min_length=1)
    target_date: date = Field(alias="targetDate")
    status: Literal["ACTIVE", "EXPIRED"]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    source_session: str = Field(alias="sourceSession")


class UserPreferenceData(BaseModel):
    """只保存用户确认过、跨会话仍稳定的兑换与任务偏好。"""

    model_config = ConfigDict(populate_by_name=True)

    user_id: int = Field(alias="userId")
    preferred_categories: list[str] = Field(
        default_factory=list,
        alias="preferredCategories",
    )
    disliked_categories: list[str] = Field(
        default_factory=list,
        alias="dislikedCategories",
    )
    task_preferences: list[str] = Field(
        default_factory=list,
        alias="taskPreferences",
    )
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    source_session: str = Field(alias="sourceSession")


class GrowthMemoryData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goal: RedemptionGoalData | None = None
    preferences: UserPreferenceData | None = None


class PendingMemoryChangeData(BaseModel):
    """可返回给浏览器的记忆变更摘要，不包含内部草稿标识。"""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["AWAITING_MEMORY_CONFIRMATION"]
    change_type: Literal[
        "UPSERT_GOAL",
        "REPLACE_PREFERENCES",
        "FORGET_GOAL",
        "FORGET_PREFERENCES",
        "FORGET_ALL",
    ] = Field(alias="changeType")
    summary: str
    expires_at: datetime = Field(alias="expiresAt")
