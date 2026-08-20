from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.api_client import BusinessApiError
from app.models import ToolEnvelope


def _ok(code: str, data: Any, message: str = "查询成功") -> ToolEnvelope:
    return ToolEnvelope(
        success=True,
        code=code,
        data=deepcopy(data),
        message=message,
        retryable=False,
    )


def _failed(code: str, message: str) -> ToolEnvelope:
    return ToolEnvelope(
        success=False,
        code=code,
        data=None,
        message=message,
        retryable=False,
    )


BASE_AWARD = {
    "awardId": 6,
    "name": "手表",
    "requiredPoints": 200,
    "inventory": 100,
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "eligible": {
        "points": 300,
        "award": BASE_AWARD,
        "eligibility": {
            "userId": 10,
            "awardId": 6,
            "eligible": True,
            "reasonCode": "ELIGIBLE",
            "reason": "满足兑换条件",
            "currentPoints": 300,
            "requiredPoints": 200,
            "pointsGap": 0,
        },
        "tasks": [],
    },
    "insufficient_cover": {
        "points": 50,
        "award": BASE_AWARD,
        "eligibility": {
            "userId": 10,
            "awardId": 6,
            "eligible": False,
            "reasonCode": "INSUFFICIENT_POINTS",
            "reason": "积分不足",
            "currentPoints": 50,
            "requiredPoints": 200,
            "pointsGap": 150,
        },
        "tasks": [
            {
                "taskId": 1,
                "taskName": "浏览奖励",
                "rewardPoints": 60,
                "status": "COMPLETED_UNCLAIMED",
            },
            {
                "taskId": 2,
                "taskName": "每日签到",
                "rewardPoints": 100,
                "status": "AVAILABLE",
            },
            {
                "taskId": 3,
                "taskName": "分享活动",
                "rewardPoints": 80,
                "status": "AVAILABLE",
            },
        ],
    },
    "insufficient_no_cover": {
        "points": 50,
        "award": BASE_AWARD,
        "eligibility": {
            "userId": 10,
            "awardId": 6,
            "eligible": False,
            "reasonCode": "INSUFFICIENT_POINTS",
            "reason": "积分不足",
            "currentPoints": 50,
            "requiredPoints": 200,
            "pointsGap": 150,
        },
        "tasks": [
            {
                "taskId": 4,
                "taskName": "浏览商品",
                "rewardPoints": 20,
                "status": "AVAILABLE",
            },
            {
                "taskId": 5,
                "taskName": "每日签到",
                "rewardPoints": 30,
                "status": "AVAILABLE",
            },
        ],
    },
    "out_of_stock": {
        "points": 300,
        "award": {**BASE_AWARD, "inventory": 0},
        "eligibility": {
            "userId": 10,
            "awardId": 6,
            "eligible": False,
            "reasonCode": "OUT_OF_STOCK",
            "reason": "当前没有库存",
            "currentPoints": 300,
            "requiredPoints": 200,
            "pointsGap": 0,
        },
        "tasks": [],
    },
    "user_not_found": {
        "points": 0,
        "award": BASE_AWARD,
        "eligibility_error": ("USER_NOT_FOUND", "用户不存在"),
        "tasks": [],
    },
    "api_unavailable": {
        "points": 0,
        "award": BASE_AWARD,
        "raise_error": True,
        "tasks": [],
    },
    "malformed_eligibility": {
        "points": 50,
        "award": BASE_AWARD,
        "eligibility": {
            "userId": 10,
            "awardId": 6,
            "eligible": False,
        },
        "tasks": [],
    },
    "award_recommendation": {
        "points": 260,
        "award": BASE_AWARD,
        "eligibility": {
            "userId": 10,
            "awardId": 6,
            "eligible": True,
            "reasonCode": "ELIGIBLE",
            "reason": "满足兑换条件",
            "currentPoints": 260,
            "requiredPoints": 200,
            "pointsGap": 0,
        },
        "awards": [
            {
                "award": BASE_AWARD,
                "redeemable": True,
                "pointsGap": 0,
                "reasonCode": "ELIGIBLE",
            },
            {
                "award": {
                    "awardId": 7,
                    "name": "水杯",
                    "requiredPoints": 100,
                    "inventory": 50,
                },
                "redeemable": True,
                "pointsGap": 0,
                "reasonCode": "ELIGIBLE",
            },
            {
                "award": {
                    "awardId": 8,
                    "name": "耳机",
                    "requiredPoints": 300,
                    "inventory": 20,
                },
                "redeemable": False,
                "pointsGap": 40,
                "reasonCode": "INSUFFICIENT_POINTS",
            },
            {
                "award": {
                    "awardId": 9,
                    "name": "键盘",
                    "requiredPoints": 250,
                    "inventory": 0,
                },
                "redeemable": False,
                "pointsGap": 0,
                "reasonCode": "OUT_OF_STOCK",
            },
        ],
        "tasks": [],
    },
}


class FixtureBusinessApiClient:
    """A deterministic in-memory replacement for the Java query service."""

    def __init__(self, scenario_name: str) -> None:
        if scenario_name not in SCENARIOS:
            raise ValueError(f"未知评测场景：{scenario_name}")
        self.scenario_name = scenario_name
        self.scenario = deepcopy(SCENARIOS[scenario_name])
        self.calls: list[dict[str, Any]] = []

    def _record(self, method: str, **arguments: Any) -> None:
        self.calls.append({"method": method, "arguments": arguments})

    def _maybe_raise(self) -> None:
        if self.scenario.get("raise_error"):
            raise BusinessApiError(
                "BUSINESS_API_UNAVAILABLE",
                "业务查询服务暂时不可用",
                True,
            )

    def get_user_points(self, user_id: int) -> ToolEnvelope:
        self._record("get_user_points", user_id=user_id)
        self._maybe_raise()
        return _ok(
            "POINTS_FOUND",
            {"userId": user_id, "points": self.scenario["points"]},
        )

    def list_available_tasks(self, user_id: int) -> ToolEnvelope:
        self._record("list_available_tasks", user_id=user_id)
        self._maybe_raise()
        return _ok("TASKS_FOUND", self.scenario.get("tasks", []))

    def get_award_detail(self, award_id: int) -> ToolEnvelope:
        self._record("get_award_detail", award_id=award_id)
        self._maybe_raise()
        return _ok("AWARD_FOUND", self.scenario["award"])

    def list_awards(
        self, user_id: int, redeemable_only: bool = False
    ) -> ToolEnvelope:
        self._record(
            "list_awards", user_id=user_id, redeemable_only=redeemable_only
        )
        self._maybe_raise()
        awards = self.scenario.get("awards")
        if awards is None:
            eligibility = self.scenario.get("eligibility", {})
            awards = [
                {
                    "award": deepcopy(self.scenario["award"]),
                    "redeemable": bool(eligibility.get("eligible", False)),
                    "pointsGap": eligibility.get("pointsGap", 0),
                    "reasonCode": eligibility.get("reasonCode", "UNKNOWN"),
                }
            ]
        if redeemable_only:
            awards = [award for award in awards if award["redeemable"]]
        return _ok("AWARDS_FOUND", awards)

    def check_exchange_eligibility(
        self, user_id: int, award_id: int
    ) -> ToolEnvelope:
        self._record(
            "check_exchange_eligibility", user_id=user_id, award_id=award_id
        )
        self._maybe_raise()
        if "eligibility_error" in self.scenario:
            code, message = self.scenario["eligibility_error"]
            return _failed(code, message)
        return _ok("ELIGIBILITY_CHECKED", self.scenario["eligibility"])
