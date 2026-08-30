from __future__ import annotations

import unittest

from app.api_client import BusinessApiError
from app.models import ToolEnvelope
from app.services.award_recommendation import AwardRecommendationService


def ok(code: str, data) -> ToolEnvelope:
    return ToolEnvelope(
        success=True,
        code=code,
        data=data,
        message="查询成功",
        retryable=False,
    )


def award_option(
    award_id: int,
    name: str,
    required_points: int,
    *,
    inventory: int = 10,
    redeemable: bool = True,
    reason_code: str = "ELIGIBLE",
) -> dict:
    return {
        "award": {
            "awardId": award_id,
            "name": name,
            "requiredPoints": required_points,
            "inventory": inventory,
        },
        "redeemable": redeemable,
        "pointsGap": max(0, required_points - 300),
        "reasonCode": reason_code,
    }


class FakeClient:
    def __init__(self, points=300, awards=None, *, raise_error=False):
        self.points = points
        self.awards = awards or []
        self.raise_error = raise_error
        self.calls: list[str] = []

    def get_user_points(self, user_id: int):
        self.calls.append("get_user_points")
        if self.raise_error:
            raise BusinessApiError("BUSINESS_API_UNAVAILABLE", "服务不可用", True)
        return ok("POINTS_FOUND", {"userId": user_id, "points": self.points})

    def list_awards(self, user_id: int, redeemable_only: bool = False):
        self.calls.append("list_awards")
        return ok("AWARDS_FOUND", self.awards)


class AwardRecommendationServiceTest(unittest.TestCase):
    def test_recommends_highest_affordable_award_first_and_honors_limit(self):
        client = FakeClient(
            awards=[
                award_option(1, "水杯", 100),
                award_option(2, "手表", 200),
                award_option(3, "耳机", 200),
            ]
        )

        result = AwardRecommendationService(client).recommend(10, limit=2)

        self.assertEqual("RECOMMENDATIONS_READY", result.status)
        self.assertEqual([2, 3], [item.award_id for item in result.recommendations])
        self.assertEqual([100, 100], [item.remaining_points for item in result.recommendations])
        self.assertEqual(["get_user_points", "list_awards"], client.calls)

    def test_filters_backend_blocked_and_out_of_stock_awards(self):
        client = FakeClient(
            awards=[
                award_option(
                    1,
                    "积分不足奖品",
                    400,
                    redeemable=False,
                    reason_code="INSUFFICIENT_POINTS",
                ),
                award_option(
                    2,
                    "缺货奖品",
                    200,
                    inventory=0,
                    redeemable=False,
                    reason_code="OUT_OF_STOCK",
                ),
            ]
        )

        result = AwardRecommendationService(client).recommend(10)

        self.assertEqual("NO_REDEEMABLE_AWARDS", result.status)
        self.assertEqual([], result.recommendations)
        self.assertEqual(300, result.current_points)

    def test_rejects_malformed_nested_award_data(self):
        client = FakeClient(awards=[{"award": {"awardId": 1}}])

        result = AwardRecommendationService(client).recommend(10)

        self.assertEqual("QUERY_FAILED", result.status)
        self.assertEqual("INVALID_BUSINESS_RESPONSE", result.reason_code)

    def test_preserves_business_api_error(self):
        result = AwardRecommendationService(FakeClient(raise_error=True)).recommend(10)

        self.assertEqual("QUERY_FAILED", result.status)
        self.assertEqual("BUSINESS_API_UNAVAILABLE", result.reason_code)

    def test_rejects_invalid_limit_before_querying_backend(self):
        client = FakeClient()

        result = AwardRecommendationService(client).recommend(10, limit=6)

        self.assertEqual("QUERY_FAILED", result.status)
        self.assertEqual("INVALID_ARGUMENT", result.reason_code)
        self.assertEqual([], client.calls)


if __name__ == "__main__":
    unittest.main()
