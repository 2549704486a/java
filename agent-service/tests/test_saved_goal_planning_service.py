from __future__ import annotations

import unittest
from datetime import date

from app.execution_context import bind_execution_context
from app.memory.store import GrowthMemoryStore
from app.models import ToolEnvelope
from app.services.points_planning import PointsPlanningService
from app.services.saved_goal_planning import SavedGoalPlanningService
from app.tools import build_tools


def ok(code: str, data) -> ToolEnvelope:
    return ToolEnvelope(success=True, code=code, data=data, message="查询成功")


def award_option(award_id: int, name: str) -> dict:
    return {
        "award": {
            "awardId": award_id,
            "name": name,
            "requiredPoints": 500,
            "inventory": 20,
        },
        "redeemable": True,
        "pointsGap": 0,
        "reasonCode": "ELIGIBLE",
    }


class FakeClient:
    def __init__(self, awards: list[dict] | None = None) -> None:
        self.awards = awards or []
        self.calls: list[str] = []

    def list_awards(self, user_id: int, redeemable_only: bool = False):
        self.calls.append("list_awards")
        return ok("AWARDS_FOUND", self.awards)

    def check_exchange_eligibility(self, user_id: int, award_id: int):
        self.calls.append(f"eligibility:{award_id}")
        return ok(
            "ELIGIBILITY_CHECKED",
            {
                "userId": user_id,
                "awardId": award_id,
                "eligible": True,
                "reasonCode": "ELIGIBLE",
                "reason": "满足兑换条件",
                "currentPoints": 900,
                "requiredPoints": 500,
                "pointsGap": 0,
            },
        )

    def get_award_detail(self, award_id: int):
        self.calls.append(f"award:{award_id}")
        name = next(
            (
                item["award"]["name"]
                for item in self.awards
                if item["award"]["awardId"] == award_id
            ),
            "已绑定奖品",
        )
        return ok(
            "AWARD_FOUND",
            {
                "awardId": award_id,
                "name": name,
                "requiredPoints": 500,
                "inventory": 20,
            },
        )

    def list_available_tasks(self, user_id: int):
        self.calls.append("tasks")
        return ok("TASKS_FOUND", [])


class SavedGoalPlanningServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = GrowthMemoryStore()

    def service(self, client: FakeClient) -> SavedGoalPlanningService:
        return SavedGoalPlanningService(
            client,
            self.store,
            PointsPlanningService(client),
            today_provider=lambda: date(2026, 8, 22),
        )

    def remember_goal(self, raw_text: str, **normalized_data) -> None:
        self.store.remember(
            user_id=10,
            source_session="user:10:session:a",
            memory_type="goal",
            raw_text=raw_text,
            normalized_data=normalized_data,
        )

    def test_returns_without_business_query_when_no_goal_exists(self):
        client = FakeClient()

        result = self.service(client).plan(user_id=10)

        self.assertEqual("NO_SAVED_GOAL", result.status)
        self.assertEqual([], client.calls)

    def test_bound_award_id_reuses_realtime_points_plan_without_listing_awards(self):
        self.remember_goal("我计划兑换 6 号奖品", subject="6号奖品", awardId=6)
        client = FakeClient()

        result = self.service(client).plan(user_id=10)

        self.assertEqual("TARGET_RESOLVED", result.status)
        self.assertEqual(6, result.plan.award_id)
        self.assertNotIn("list_awards", client.calls)
        self.assertIn("eligibility:6", client.calls)

    def test_broad_goal_resolves_unique_current_award(self):
        self.remember_goal("我打算明年换一个手环", subject="手环", targetYear=2027)
        client = FakeClient(
            [award_option(6, "城市随行保温杯"), award_option(8, "智能手环")]
        )

        result = self.service(client).plan(user_id=10, goal_query="手环目标")

        self.assertEqual("TARGET_RESOLVED", result.status)
        self.assertEqual(8, result.plan.award_id)
        self.assertEqual("我打算明年换一个手环", result.goal_raw_text)
        self.assertEqual("list_awards", client.calls[0])

    def test_multiple_matching_awards_require_user_selection(self):
        self.remember_goal("我打算明年换一个手环", subject="手环")
        client = FakeClient(
            [award_option(8, "智能手环"), award_option(9, "运动手环")]
        )

        result = self.service(client).plan(user_id=10)

        self.assertEqual("AWARD_NEEDS_SELECTION", result.status)
        self.assertEqual([8, 9], [item.award_id for item in result.candidates])
        self.assertFalse(any(call.startswith("eligibility:") for call in client.calls))

    def test_expired_goal_stops_before_business_queries(self):
        self.remember_goal(
            "我原计划去年兑换一个手环",
            subject="手环",
            timeExpression="去年",
            targetYear=2025,
        )
        client = FakeClient([award_option(8, "智能手环")])

        result = self.service(client).plan(user_id=10)

        self.assertEqual("GOAL_EXPIRED", result.status)
        self.assertEqual(2025, result.target_year)
        self.assertEqual([], client.calls)

    def test_multiple_saved_goals_return_readable_choices(self):
        self.remember_goal("我明年想换一个手环", subject="手环", targetYear=2027)
        self.remember_goal("我年底想换一个保温杯", subject="保温杯", targetYear=2026)
        client = FakeClient()

        result = self.service(client).plan(user_id=10, goal_query="之前的目标")

        self.assertEqual("GOAL_NEEDS_SELECTION", result.status)
        self.assertEqual(2, len(result.goal_candidates))
        self.assertEqual(
            {"手环", "保温杯"},
            {item.subject for item in result.goal_candidates},
        )
        self.assertEqual([], client.calls)

    def test_tools_share_default_memory_store(self):
        client = FakeClient([award_option(8, "智能手环")])
        tools = {item.name: item for item in build_tools(client, 10)}

        with bind_execution_context("user:10:session:tool"):
            tools["remember_user_memory"].invoke(
                {
                    "memory_type": "goal",
                    "raw_text": "我打算明年换一个手环",
                    "subject": "手环",
                    "time_expression": "明年",
                    "target_year": 2027,
                }
            )
            result = tools["plan_points_for_saved_goal"].invoke(
                {"goal_query": "手环目标", "excluded_task_ids": []}
            )

        self.assertEqual("TARGET_RESOLVED", result["status"])
        self.assertEqual(8, result["plan"]["award_id"])


if __name__ == "__main__":
    unittest.main()
