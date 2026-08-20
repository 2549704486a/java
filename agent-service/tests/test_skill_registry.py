from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import ToolEnvelope
from app.skills.registry import SkillDefinitionError, SkillRegistry
from app.tools import build_tools


class EligibleClient:
    def check_exchange_eligibility(self, user_id: int, award_id: int):
        return ToolEnvelope(
            success=True,
            code="ELIGIBILITY_CHECKED",
            data={
                "userId": user_id,
                "awardId": award_id,
                "eligible": True,
                "reasonCode": "ELIGIBLE",
                "reason": "可以兑换",
                "currentPoints": 120,
                "requiredPoints": 100,
                "pointsGap": 0,
            },
            message="查询成功",
            retryable=False,
        )

    def get_award_detail(self, award_id: int):
        return ToolEnvelope(
            success=True,
            code="AWARD_FOUND",
            data={
                "awardId": award_id,
                "name": "测试奖品",
                "requiredPoints": 100,
                "inventory": 10,
            },
            message="查询成功",
            retryable=False,
        )


class SkillRegistryTest(unittest.TestCase):
    def test_discovers_and_activates_points_planning_definition(self):
        registry = SkillRegistry()

        manifest = registry.require_manifest("points-planning")
        definition = registry.activate("points-planning")

        self.assertEqual("1.0.0", manifest.version)
        self.assertIn("生成任务积分方案", manifest.description)
        self.assertIn("## 执行步骤", definition.instructions)
        self.assertEqual(64, len(manifest.sha256))
        self.assertEqual(
            {"award-recommendation", "points-planning"},
            {item.name for item in registry.manifests()},
        )

        recommendation = registry.require_manifest("award-recommendation")
        self.assertIn("推荐", recommendation.description)
        self.assertEqual("1.0.0", recommendation.version)

    def test_tool_description_comes_from_manifest_and_activation_is_traced(self):
        registry = SkillRegistry()
        manifest = registry.require_manifest("points-planning")
        tools = build_tools(EligibleClient(), 10, registry)
        plan_tool = next(tool for tool in tools if tool.name == "plan_points_for_award")

        with patch.object(registry, "activate", wraps=registry.activate) as activate:
            result = plan_tool.invoke({"award_id": 6, "excluded_task_ids": []})

        self.assertEqual(manifest.tool_description, plan_tool.description)
        self.assertEqual("points-planning", plan_tool.extras["skill_name"])
        self.assertEqual("1.0.0", plan_tool.extras["skill_version"])
        self.assertEqual("READY_TO_EXCHANGE", result["status"])
        activate.assert_called_once_with("points-planning")

    def test_rejects_skill_missing_required_section(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "broken-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                """---
name: broken-skill
description: 测试损坏的 Skill
trigger: 测试时触发
version: 1.0.0
tags: [test]
---

# Broken Skill

## 何时使用

仅用于测试。
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SkillDefinitionError, "缺少章节"):
                SkillRegistry(skill_dir.parent)


if __name__ == "__main__":
    unittest.main()
