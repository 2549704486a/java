from __future__ import annotations

from pydantic import ValidationError

from app.api_client import BusinessApiClient, BusinessApiError
from app.models import (
    AwardOptionData,
    AwardRecommendation,
    RecommendedAward,
    ToolEnvelope,
    UserPointsData,
)


class AwardRecommendationSkill:
    """根据实时积分和奖品状态，确定性地推荐当前可兑换奖品。"""

    def __init__(self, client: BusinessApiClient) -> None:
        self._client = client

    def recommend(self, user_id: int, limit: int = 3) -> AwardRecommendation:
        if user_id <= 0 or not 1 <= limit <= 5:
            return AwardRecommendation(
                status="QUERY_FAILED",
                reason_code="INVALID_ARGUMENT",
                message="用户 ID 必须为正整数，推荐数量必须在 1 到 5 之间",
                user_id=user_id,
            )

        # Step 1: 同时需要积分和奖品状态，任一查询失败都停止推荐。
        try:
            points_envelope = self._client.get_user_points(user_id)
            awards_envelope = self._client.list_awards(user_id, False)
        except BusinessApiError as exc:
            return self._query_failed(user_id, exc.as_envelope())

        if not points_envelope.success:
            return self._query_failed(user_id, points_envelope)
        if not awards_envelope.success:
            return self._query_failed(user_id, awards_envelope)

        # Step 2: 将 Java JSON 校验成稳定对象，避免模型基于残缺数据猜测。
        try:
            points = UserPointsData.model_validate(points_envelope.data)
            award_items = awards_envelope.data or []
            options = [AwardOptionData.model_validate(item) for item in award_items]
        except (ValidationError, TypeError):
            return AwardRecommendation(
                status="QUERY_FAILED",
                reason_code="INVALID_BUSINESS_RESPONSE",
                message="积分或奖品查询返回了无法识别的数据",
                user_id=user_id,
            )

        # Step 3: 只保留后端判定可兑换的奖品，再按积分利用率稳定排序。
        candidates = [
            option.award
            for option in options
            if option.redeemable
            and option.award.inventory > 0
            and 0 < option.award.required_points <= points.points
        ]
        candidates.sort(key=lambda award: (-award.required_points, award.award_id))
        recommendations = [
            RecommendedAward(
                award_id=award.award_id,
                name=award.name,
                required_points=award.required_points,
                inventory=award.inventory,
                remaining_points=points.points - award.required_points,
            )
            for award in candidates[:limit]
        ]

        if not recommendations:
            return AwardRecommendation(
                status="NO_REDEEMABLE_AWARDS",
                reason_code="NO_REDEEMABLE_AWARDS",
                message="当前没有满足全部兑换条件的奖品",
                user_id=user_id,
                current_points=points.points,
            )

        return AwardRecommendation(
            status="RECOMMENDATIONS_READY",
            reason_code="RECOMMENDATIONS_READY",
            message="已按所需积分从高到低推荐当前可兑换奖品",
            user_id=user_id,
            current_points=points.points,
            recommendations=recommendations,
        )

    @staticmethod
    def _query_failed(
        user_id: int, envelope: ToolEnvelope
    ) -> AwardRecommendation:
        return AwardRecommendation(
            status="QUERY_FAILED",
            reason_code=envelope.code,
            message=envelope.message,
            user_id=user_id,
        )
