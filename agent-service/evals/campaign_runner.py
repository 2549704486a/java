from __future__ import annotations

import argparse
import copy
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from app.operator.campaign_data import StaticCampaignDataProvider
from app.models import CampaignBrief, CampaignPlanDraft, CampaignPlanningSnapshot
from app.operator.auth import AuthenticatedOperator
from app.operator.tools import CAMPAIGN_DRAFT, CAMPAIGN_READ, build_operator_tools
from app.services.campaign_planning import CampaignPlanningService


ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_PATH = ROOT / "campaign_cases.json"
DEFAULT_OUTPUT_PATH = ROOT / "results" / "campaign_planning_baseline_20260822.json"
CATEGORIES = (
    "permission_isolation",
    "data_reference_correctness",
    "constraint_satisfaction",
    "draft_completeness",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运营活动草案确定性评测")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--ids", help="只运行指定用例，多个编号使用逗号分隔")
    return parser.parse_args()


def load_suite(path: Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    expanded: dict[str, CampaignPlanningSnapshot] = {}
    for name, snapshot_data in raw["snapshots"].items():
        source = copy.deepcopy(snapshot_data)
        parent = source.pop("copy_from", None)
        if parent:
            if parent not in expanded:
                raise ValueError(f"快照 {name} 引用了尚未定义的父快照 {parent}")
            # Fixture inheritance uses Python field names so a child snapshot can
            # reliably override fields even when the HTTP model has Java aliases.
            merged = expanded[parent].model_dump(mode="json")
            merged.update(source)
            source = merged
        expanded[name] = CampaignPlanningSnapshot.model_validate(source)
    return {
        "schema_version": raw["schema_version"],
        "frozen_at": datetime.fromisoformat(raw["frozen_at"]),
        "snapshots": expanded,
        "cases": raw["cases"],
    }


def evaluate_suite(
    suite: dict[str, Any],
    ids: set[str] | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    cases = [case for case in suite["cases"] if not ids or case["id"] in ids]
    for case in cases:
        result = evaluate_case(case, suite["snapshots"], suite["frozen_at"])
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {case['id']} {case['category']}")
    return {
        "metadata": {
            "suite": "campaign_planning_fixture",
            "schema_version": suite["schema_version"],
            "frozen_at": suite["frozen_at"].isoformat(),
            "deterministic": True,
            "model_calls": 0,
        },
        "summary": summarize(results),
        "results": results,
    }


def evaluate_case(
    case: dict[str, Any],
    snapshots: dict[str, CampaignPlanningSnapshot],
    frozen_at: datetime,
) -> dict[str, Any]:
    snapshot = snapshots[case["snapshot"]].model_copy(deep=True)
    provider = StaticCampaignDataProvider(
        {snapshot.segment.segment_key: snapshot}
    )
    operator = AuthenticatedOperator(
        operator_id=f"fixture-{case['id'].lower()}",
        permissions=frozenset(case["permissions"]),
    )
    checks: list[dict[str, Any]] = []
    tools = []
    build_error: Exception | None = None
    try:
        tools = build_operator_tools(
            provider,
            operator,
            planning_service=CampaignPlanningService(now_provider=lambda: frozen_at),
        )
    except Exception as exc:  # The expected permission exception is scored below.
        build_error = exc

    expected = case["expected"]
    if "error_type" in expected:
        _add_check(
            checks,
            "permission_isolation",
            "缺少读取权限时拒绝构建运营工具",
            build_error is not None
            and build_error.__class__.__name__ == expected["error_type"],
            expected["error_type"],
            build_error.__class__.__name__ if build_error else None,
        )
        return _case_result(case, checks, output=None)

    _add_check(
        checks,
        "permission_isolation",
        "具有读取权限时暴露只读快照工具",
        build_error is None
        and "get_campaign_planning_snapshot" in _tool_names(tools),
        True,
        build_error.__class__.__name__ if build_error else True,
    )
    _add_check(
        checks,
        "permission_isolation",
        "草案工具严格服从服务端草案权限",
        ("draft_campaign_plan" in _tool_names(tools))
        == (CAMPAIGN_DRAFT in operator.permissions),
        CAMPAIGN_DRAFT in operator.permissions,
        "draft_campaign_plan" in _tool_names(tools),
    )

    if case["operation"] == "tool_inventory":
        actual = sorted(_tool_names(tools))
        wanted = sorted(expected["tool_names"])
        _add_check(
            checks,
            "permission_isolation",
            "只读运营身份不能获得草案工具",
            actual == wanted,
            wanted,
            actual,
        )
        return _case_result(case, checks, output={"tool_names": actual})

    if case["operation"] == "snapshot":
        tool = next(item for item in tools if item.name == "get_campaign_planning_snapshot")
        output = tool.invoke(
            {"target_segment_key": case["target_segment_key"]}
        )
        _add_check(
            checks,
            "data_reference_correctness",
            "未知客群返回明确结果而非猜测数据",
            output.get("success") == expected["success"]
            and output.get("code") == expected["code"],
            {"success": expected["success"], "code": expected["code"]},
            {"success": output.get("success"), "code": output.get("code")},
        )
        return _case_result(case, checks, output=output)

    draft_tool = next(item for item in tools if item.name == "draft_campaign_plan")
    output = draft_tool.invoke(case["brief"])
    draft = CampaignPlanDraft.model_validate(output)
    checks.extend(score_draft(case, snapshot, draft))
    return _case_result(case, checks, output=draft.model_dump(mode="json"))


def score_draft(
    case: dict[str, Any],
    snapshot: CampaignPlanningSnapshot,
    draft: CampaignPlanDraft,
) -> list[dict[str, Any]]:
    """Independently audit a draft instead of trusting only expected status text."""

    checks: list[dict[str, Any]] = []
    expected = case["expected"]
    brief = CampaignBrief(
        target_segment=snapshot.segment.description,
        **case["brief"],
    )

    _add_check(
        checks,
        "data_reference_correctness",
        "草案引用本次输入快照",
        draft.source_snapshot_id == snapshot.snapshot_id
        and draft.source_generated_at == snapshot.generated_at,
        {
            "snapshot_id": snapshot.snapshot_id,
            "generated_at": snapshot.generated_at.isoformat(),
        },
        {
            "snapshot_id": draft.source_snapshot_id,
            "generated_at": draft.source_generated_at.isoformat(),
        },
    )
    _add_check(
        checks,
        "data_reference_correctness",
        "客群键和说明来自同一事实快照",
        draft.target_segment_key == snapshot.segment.segment_key
        and draft.target_segment == snapshot.segment.description,
        {
            "key": snapshot.segment.segment_key,
            "description": snapshot.segment.description,
        },
        {"key": draft.target_segment_key, "description": draft.target_segment},
    )
    _add_check(
        checks,
        "data_reference_correctness",
        "任务字段和来源可回查到快照",
        _task_references_match(snapshot, draft),
        True,
        _task_reference_view(draft),
    )
    _add_check(
        checks,
        "data_reference_correctness",
        "奖品字段和来源可回查到快照",
        _award_references_match(snapshot, draft),
        True,
        _award_reference_view(draft),
    )

    _add_check(
        checks,
        "constraint_satisfaction",
        "状态和原因码符合冻结用例",
        draft.status == expected["status"]
        and draft.reason_code == expected["reason_code"],
        {"status": expected["status"], "reason_code": expected["reason_code"]},
        {"status": draft.status, "reason_code": draft.reason_code},
    )
    _add_check(
        checks,
        "constraint_satisfaction",
        "候选任务与奖品符合冻结预期",
        [item.task_id for item in draft.suggested_tasks]
        == expected.get("task_ids", [])
        and [item.award_id for item in draft.suggested_awards]
        == expected.get("award_ids", []),
        {
            "task_ids": expected.get("task_ids", []),
            "award_ids": expected.get("award_ids", []),
        },
        {
            "task_ids": [item.task_id for item in draft.suggested_tasks],
            "award_ids": [item.award_id for item in draft.suggested_awards],
        },
    )
    _add_check(
        checks,
        "constraint_satisfaction",
        "候选数量不超过运营简报上限",
        len(draft.suggested_tasks) <= brief.max_tasks
        and len(draft.suggested_awards) <= brief.max_awards,
        {"max_tasks": brief.max_tasks, "max_awards": brief.max_awards},
        {
            "task_count": len(draft.suggested_tasks),
            "award_count": len(draft.suggested_awards),
        },
    )
    _add_check(
        checks,
        "constraint_satisfaction",
        "入选任务和奖品在完整活动窗口内可用",
        _selected_candidates_are_available(snapshot, draft, brief),
        True,
        {
            "task_ids": [item.task_id for item in draft.suggested_tasks],
            "award_ids": [item.award_id for item in draft.suggested_awards],
        },
    )
    _add_check(
        checks,
        "constraint_satisfaction",
        "积分发放量与奖品金额分别重算且不越过各自约束",
        _costs_are_valid(draft, brief),
        {
            "points_issuance_cap": brief.points_issuance_cap,
            "budget_amount_cents": brief.budget_amount_cents,
        },
        {
            "estimated_participants": draft.estimated_participants,
            "estimated_points_issued": draft.estimated_points_issued,
            "planned_award_cost_cents": draft.planned_award_cost_cents,
        },
    )
    for field in (
        "estimated_participants",
        "estimated_points_issued",
        "planned_award_cost_cents",
    ):
        if field in expected:
            _add_check(
                checks,
                "constraint_satisfaction",
                f"{field} 符合冻结预期",
                getattr(draft, field) == expected[field],
                expected[field],
                getattr(draft, field),
            )
    if "risk_codes" in expected:
        actual_codes = {risk.code for risk in draft.risks}
        _add_check(
            checks,
            "constraint_satisfaction",
            "关键风险没有遗漏",
            set(expected["risk_codes"]).issubset(actual_codes),
            expected["risk_codes"],
            sorted(actual_codes),
        )

    blocking = any(risk.severity == "BLOCKING" for risk in draft.risks)
    _add_check(
        checks,
        "draft_completeness",
        "草案固定为可编辑、不可发布、必须人工审核",
        draft.lifecycle_status == "DRAFT"
        and draft.editable
        and not draft.publishable
        and draft.review_required,
        {
            "lifecycle_status": "DRAFT",
            "editable": True,
            "publishable": False,
            "review_required": True,
        },
        {
            "lifecycle_status": draft.lifecycle_status,
            "editable": draft.editable,
            "publishable": draft.publishable,
            "review_required": draft.review_required,
        },
    )
    _add_check(
        checks,
        "draft_completeness",
        "阻断风险与草案状态一致",
        (draft.status == "DRAFT_READY" and not blocking)
        or (draft.status != "DRAFT_READY" and blocking),
        "DRAFT_READY 无阻断风险；其他状态至少一个阻断风险",
        {"status": draft.status, "blocking": blocking},
    )
    _add_check(
        checks,
        "draft_completeness",
        "核心说明、目标和来源字段完整",
        bool(
            draft.message.strip()
            and draft.reason_code.strip()
            and draft.objective.strip()
            and draft.target_segment.strip()
            and draft.source_snapshot_id.strip()
        ),
        True,
        {
            "message": bool(draft.message.strip()),
            "reason_code": bool(draft.reason_code.strip()),
            "objective": bool(draft.objective.strip()),
            "target_segment": bool(draft.target_segment.strip()),
            "source_snapshot_id": bool(draft.source_snapshot_id.strip()),
        },
    )
    _add_check(
        checks,
        "draft_completeness",
        "可用草案包含估算和候选，待补数据草案不伪造估算",
        _status_payload_is_complete(draft),
        True,
        {
            "status": draft.status,
            "estimated_participants": draft.estimated_participants,
            "estimated_points_issued": draft.estimated_points_issued,
            "planned_award_cost_cents": draft.planned_award_cost_cents,
            "task_count": len(draft.suggested_tasks),
            "award_count": len(draft.suggested_awards),
        },
    )
    return checks


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    categories = {}
    for category in CATEGORIES:
        checks = [
            check
            for result in results
            for check in result["checks"]
            if check["category"] == category
        ]
        passed = sum(check["passed"] for check in checks)
        categories[category] = {
            "passed": passed,
            "total": len(checks),
            "rate": round(passed / len(checks), 4) if checks else None,
        }
    passed_cases = sum(result["passed"] for result in results)
    return {
        "passed_cases": passed_cases,
        "total_cases": len(results),
        "case_pass_rate": round(passed_cases / len(results), 4) if results else 0,
        "categories": categories,
    }


def _task_references_match(
    snapshot: CampaignPlanningSnapshot,
    draft: CampaignPlanDraft,
) -> bool:
    facts = {item.task_id: item for item in snapshot.tasks}
    return all(
        item.task_id in facts
        and item.task_name == facts[item.task_id].task_name
        and item.max_reward_per_user == facts[item.task_id].max_reward_per_user
        and item.source_ref == facts[item.task_id].source_ref
        for item in draft.suggested_tasks
    )


def _award_references_match(
    snapshot: CampaignPlanningSnapshot,
    draft: CampaignPlanDraft,
) -> bool:
    facts = {item.award_id: item for item in snapshot.awards}
    return all(
        item.award_id in facts
        and item.award_name == facts[item.award_id].award_name
        and item.required_points == facts[item.award_id].required_points
        and item.unit_cost_cents == facts[item.award_id].unit_cost_cents
        and item.cost_source_ref == facts[item.award_id].cost_source_ref
        and item.inventory == facts[item.award_id].inventory
        and 0 < item.planned_quantity <= facts[item.award_id].inventory
        and item.planned_cost_cents
        == item.planned_quantity * item.unit_cost_cents
        and item.source_ref == facts[item.award_id].source_ref
        for item in draft.suggested_awards
    )


def _selected_candidates_are_available(
    snapshot: CampaignPlanningSnapshot,
    draft: CampaignPlanDraft,
    brief: CampaignBrief,
) -> bool:
    tasks = {item.task_id: item for item in snapshot.tasks}
    awards = {item.award_id: item for item in snapshot.awards}
    for selected in draft.suggested_tasks:
        task = tasks.get(selected.task_id)
        if task is None or not task.active:
            return False
        if task.available_from and task.available_from > brief.start_at:
            return False
        if task.available_until and task.available_until < brief.end_at:
            return False
    for selected in draft.suggested_awards:
        award = awards.get(selected.award_id)
        if award is None or not award.active or award.inventory <= 0:
            return False
        if award.available_from and award.available_from > brief.start_at:
            return False
        if award.available_until and award.available_until < brief.end_at:
            return False
    return True


def _costs_are_valid(draft: CampaignPlanDraft, brief: CampaignBrief) -> bool:
    if (
        draft.estimated_points_issued is None
        or draft.planned_award_cost_cents is None
    ):
        return draft.status == "NEEDS_DATA"
    if draft.estimated_participants is None:
        return False
    recomputed_points = draft.estimated_participants * sum(
        item.max_reward_per_user for item in draft.suggested_tasks
    )
    recomputed_amount = sum(
        item.planned_quantity * item.unit_cost_cents
        for item in draft.suggested_awards
    )
    return (
        draft.estimated_points_issued == recomputed_points
        and draft.estimated_points_issued <= brief.points_issuance_cap
        and draft.planned_award_cost_cents == recomputed_amount
        and draft.planned_award_cost_cents <= brief.budget_amount_cents
    )


def _status_payload_is_complete(draft: CampaignPlanDraft) -> bool:
    if draft.status == "DRAFT_READY":
        return (
            draft.estimated_participants is not None
            and draft.estimated_points_issued is not None
            and draft.planned_award_cost_cents is not None
            and bool(draft.suggested_tasks)
            and bool(draft.suggested_awards)
        )
    if draft.status == "NEEDS_DATA":
        return (
            draft.estimated_participants is None
            and draft.estimated_points_issued is None
            and draft.planned_award_cost_cents is None
            and not draft.suggested_tasks
            and not draft.suggested_awards
        )
    return (
        draft.estimated_participants is not None
        and draft.estimated_points_issued is not None
        and draft.planned_award_cost_cents is not None
    )


def _tool_names(tools: list[Any]) -> list[str]:
    return [item.name for item in tools]


def _task_reference_view(draft: CampaignPlanDraft) -> list[dict[str, Any]]:
    return [
        {"task_id": item.task_id, "source_ref": item.source_ref}
        for item in draft.suggested_tasks
    ]


def _award_reference_view(draft: CampaignPlanDraft) -> list[dict[str, Any]]:
    return [
        {"award_id": item.award_id, "source_ref": item.source_ref}
        for item in draft.suggested_awards
    ]


def _add_check(
    checks: list[dict[str, Any]],
    category: str,
    name: str,
    passed: bool,
    expected: Any,
    actual: Any,
) -> None:
    checks.append(
        {
            "category": category,
            "name": name,
            "passed": bool(passed),
            "expected": expected,
            "actual": actual,
        }
    )


def _case_result(
    case: dict[str, Any],
    checks: list[dict[str, Any]],
    output: Any,
) -> dict[str, Any]:
    return {
        "id": case["id"],
        "category": case["category"],
        "operation": case["operation"],
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "output": output,
    }


def main() -> None:
    args = parse_args()
    ids = {item.strip() for item in args.ids.split(",")} if args.ids else None
    report = evaluate_suite(load_suite(args.cases), ids)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = report["summary"]
    print(
        f"完成：{summary['passed_cases']}/{summary['total_cases']}，"
        f"结果已写入 {args.output}"
    )
    if summary["passed_cases"] != summary["total_cases"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
