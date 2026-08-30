from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import PrivateAttr

from app.models import ToolEnvelope
from app.skills.loader import build_load_skill_tool
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


class ToolCallingFakeModel(FakeMessagesListChatModel):
    """记录每次模型调用收到的消息，用于验证正文是否真正进入上下文。"""

    _received_messages: list[list] = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._received_messages.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


class SkillRegistryTest(unittest.TestCase):
    def test_discovers_and_loads_points_planning_definition(self):
        registry = SkillRegistry()

        manifest = registry.require_manifest("points-planning")
        definition = registry.load("points-planning")

        self.assertEqual("2.0.0", manifest.version)
        self.assertIn("实时攒分方案", manifest.description)
        self.assertIn("## 执行步骤", definition.instructions)
        self.assertEqual(
            {
                "award-recommendation",
                "campaign-planning",
                "controlled-exchange",
                "growth-memory",
                "points-planning",
            },
            {item.name for item in registry.manifests()},
        )

        recommendation = registry.require_manifest("award-recommendation")
        self.assertIn("推荐", recommendation.description)
        self.assertEqual("2.0.0", recommendation.version)

    def test_load_tool_returns_real_body_and_restricts_skill_scope(self):
        registry = SkillRegistry()
        manifest = registry.require_manifest("points-planning")
        tools = build_tools(EligibleClient(), 10, registry)
        load_tool = next(tool for tool in tools if tool.name == "load_skill")
        plan_tool = next(tool for tool in tools if tool.name == "plan_points_for_award")
        self.assertNotIn("draft_campaign_plan", {tool.name for tool in tools})

        with patch.object(registry, "load", wraps=registry.load) as load:
            loaded = load_tool.invoke({"skill_name": "points-planning"})

        self.assertEqual("SKILL_LOADED", loaded["code"])
        self.assertIn("## 执行步骤", loaded["data"]["instructions"])
        self.assertIn(manifest.tool_description, plan_tool.description)
        self.assertEqual("points-planning", plan_tool.extras["skill_name"])
        self.assertEqual("2.0.0", plan_tool.extras["skill_version"])
        load.assert_called_once()

        denied = load_tool.invoke({"skill_name": "campaign-planning"})
        self.assertFalse(denied["success"])
        self.assertEqual("SKILL_NOT_AVAILABLE", denied["code"])

    def test_business_tool_still_uses_deterministic_service(self):
        tools = build_tools(EligibleClient(), 10, SkillRegistry())
        plan_tool = next(tool for tool in tools if tool.name == "plan_points_for_award")

        result = plan_tool.invoke({"award_id": 6, "excluded_task_ids": []})

        self.assertEqual("READY_TO_EXCHANGE", result["status"])

    def test_loaded_body_becomes_tool_message_for_next_model_call(self):
        registry = SkillRegistry()
        model = ToolCallingFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "load_skill",
                            "args": {"skill_name": "points-planning"},
                            "id": "load-skill-1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Skill 已加载"),
            ]
        )
        agent = create_agent(
            model=model,
            tools=[build_load_skill_tool(registry, ("points-planning",))],
            system_prompt="按需加载 Skill。",
        )

        result = agent.invoke(
            {"messages": [HumanMessage(content="帮我规划兑换所需积分")]}
        )

        self.assertEqual(2, len(model._received_messages))
        loaded_message = next(
            message
            for message in model._received_messages[1]
            if isinstance(message, ToolMessage) and message.name == "load_skill"
        )
        payload = json.loads(loaded_message.content)
        self.assertEqual("SKILL_LOADED", payload["code"])
        self.assertIn(
            "plan_points_for_award",
            payload["data"]["instructions"],
        )
        self.assertIn(loaded_message, result["messages"])

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
