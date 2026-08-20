from __future__ import annotations

import unittest

from app.models import ToolEnvelope
from app.skills.points_plan import PointsPlanningSkill


def ok(code: str, data) -> ToolEnvelope:
    return ToolEnvelope(
        success=True,
        code=code,
        data=data,
        message="查询成功",
        retryable=False,
    )


class FakeClient:
    def __init__(self, eligibility: ToolEnvelope, tasks: list[dict] | None = None):
        self.eligibility = eligibility
        self.tasks = tasks or []
        self.task_calls = 0

    def check_exchange_eligibility(self, user_id: int, award_id: int):
        return self.eligibility

    def get_award_detail(self, award_id: int):
        return ok(
            "AWARD_FOUND",
            {
                "awardId": award_id,
                "name": "测试奖品",
                "requiredPoints": 100,
                "inventory": 10,
            },
        )

    def list_available_tasks(self, user_id: int):
        self.task_calls += 1
        return ok("TASKS_FOUND", self.tasks)


def eligibility(
    eligible: bool = False,
    reason_code: str = "INSUFFICIENT_POINTS",
    current: int = 30,
    required: int = 100,
) -> ToolEnvelope:
    return ok(
        "ELIGIBILITY_CHECKED",
        {
            "userId": 10,
            "awardId": 6,
            "eligible": eligible,
            "reasonCode": reason_code,
            "reason": reason_code,
            "currentPoints": current,
            "requiredPoints": required,
            "pointsGap": max(0, required - current),
        },
    )


class PointsPlanningSkillTest(unittest.TestCase):
    def test_returns_ready_without_querying_tasks_when_eligible(self):
        client = FakeClient(eligibility(True, "ELIGIBLE", 120, 100))

        plan = PointsPlanningSkill(client).plan(10, 6)

        self.assertEqual("READY_TO_EXCHANGE", plan.status)
        self.assertEqual(0, client.task_calls)
        self.assertEqual([], plan.recommended_tasks)

    def test_prefers_completed_unclaimed_reward(self):
        client = FakeClient(
            eligibility(),
            tasks=[
                {
                    "taskId": 1,
                    "taskName": "签到",
                    "rewardPoints": 20,
                    "status": "AVAILABLE",
                },
                {
                    "taskId": 2,
                    "taskName": "浏览奖励",
                    "rewardPoints": 70,
                    "status": "COMPLETED_UNCLAIMED",
                },
            ],
        )

        plan = PointsPlanningSkill(client).plan(10, 6)

        self.assertEqual("PLAN_READY", plan.status)
        self.assertEqual([2], [task.task_id for task in plan.recommended_tasks])
        self.assertEqual("CLAIM_REWARD", plan.recommended_tasks[0].action)
        self.assertEqual(0, plan.remaining_gap)

    def test_chooses_fewest_tasks_then_smallest_overshoot(self):
        client = FakeClient(
            eligibility(),
            tasks=[
                {
                    "taskId": 1,
                    "taskName": "任务一",
                    "rewardPoints": 50,
                    "status": "AVAILABLE",
                },
                {
                    "taskId": 2,
                    "taskName": "任务二",
                    "rewardPoints": 20,
                    "status": "AVAILABLE",
                },
                {
                    "taskId": 3,
                    "taskName": "任务三",
                    "rewardPoints": 80,
                    "status": "AVAILABLE",
                },
            ],
        )

        plan = PointsPlanningSkill(client).plan(10, 6)

        self.assertEqual([3], [task.task_id for task in plan.recommended_tasks])
        self.assertEqual(80, plan.recommended_points)

    def test_reports_remaining_gap_when_tasks_are_insufficient(self):
        client = FakeClient(
            eligibility(),
            tasks=[
                {
                    "taskId": 1,
                    "taskName": "签到",
                    "rewardPoints": 20,
                    "status": "AVAILABLE",
                }
            ],
        )

        plan = PointsPlanningSkill(client).plan(10, 6)

        self.assertEqual("INSUFFICIENT_TASK_REWARDS", plan.status)
        self.assertEqual(50, plan.remaining_gap)

    def test_stops_on_non_points_business_blocker(self):
        client = FakeClient(eligibility(False, "OUT_OF_STOCK"))

        plan = PointsPlanningSkill(client).plan(10, 6)

        self.assertEqual("BLOCKED", plan.status)
        self.assertEqual(0, client.task_calls)

    def test_honors_excluded_tasks(self):
        client = FakeClient(
            eligibility(),
            tasks=[
                {
                    "taskId": 1,
                    "taskName": "分享",
                    "rewardPoints": 80,
                    "status": "AVAILABLE",
                },
                {
                    "taskId": 2,
                    "taskName": "浏览",
                    "rewardPoints": 50,
                    "status": "AVAILABLE",
                },
            ],
        )

        plan = PointsPlanningSkill(client).plan(10, 6, excluded_task_ids=[1])

        self.assertEqual([2], [task.task_id for task in plan.recommended_tasks])
        self.assertEqual(20, plan.remaining_gap)

    def test_rejects_malformed_business_data_instead_of_guessing(self):
        client = FakeClient(
            ok(
                "ELIGIBILITY_CHECKED",
                {"userId": 10, "awardId": 6, "eligible": False},
            )
        )

        plan = PointsPlanningSkill(client).plan(10, 6)

        self.assertEqual("QUERY_FAILED", plan.status)
        self.assertEqual("INVALID_BUSINESS_RESPONSE", plan.reason_code)


if __name__ == "__main__":
    unittest.main()
