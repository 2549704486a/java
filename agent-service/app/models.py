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


class SavedGoalAwardCandidate(BaseModel):
    award_id: int
    name: str
    required_points: int
    inventory: int


class SavedGoalCandidate(BaseModel):
    raw_text: str
    subject: str | None = None
    time_expression: str | None = None
    target_date: date | None = None
    target_year: int | None = None


class SavedGoalPointsPlan(BaseModel):
    """从长期目标解析奖品后生成的实时积分规划结果。"""

    status: Literal[
        "TARGET_RESOLVED",
        "NO_SAVED_GOAL",
        "GOAL_NEEDS_SELECTION",
        "GOAL_EXPIRED",
        "AWARD_NEEDS_SELECTION",
        "TARGET_NOT_AVAILABLE",
        "QUERY_FAILED",
    ]
    reason_code: str
    message: str
    goal_raw_text: str | None = None
    goal_time_expression: str | None = None
    target_date: date | None = None
    target_year: int | None = None
    goal_candidates: list[SavedGoalCandidate] = Field(default_factory=list)
    candidates: list[SavedGoalAwardCandidate] = Field(default_factory=list)
    plan: PointsPlan | None = None


class RedemptionGoalData(BaseModel):
    """用户明确要求保存的跨会话兑换目标。"""

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
    """只保存用户明确表达、跨会话仍稳定的兑换与任务偏好。"""

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


class MemoryItem(BaseModel):
    """一条可独立新增、更新和失效的长期记忆。"""

    model_config = ConfigDict(populate_by_name=True)

    memory_id: str = Field(alias="memoryId", min_length=1)
    user_id: int = Field(alias="userId")
    memory_type: Literal["preference", "goal", "profile", "episode"] = Field(
        alias="memoryType"
    )
    memory_key: str = Field(alias="memoryKey", min_length=1)
    raw_text: str = Field(alias="rawText", min_length=1, max_length=500)
    normalized_data: dict = Field(default_factory=dict, alias="normalizedData")
    status: Literal["ACTIVE", "SUPERSEDED", "DELETED"]
    valid_from: datetime | None = Field(default=None, alias="validFrom")
    valid_to: datetime | None = Field(default=None, alias="validTo")
    source_session: str = Field(alias="sourceSession")
    source_message_id: str | None = Field(default=None, alias="sourceMessageId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class GrowthMemoryData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goal: RedemptionGoalData | None = None
    preferences: UserPreferenceData | None = None
    memories: list[MemoryItem] = Field(default_factory=list)
