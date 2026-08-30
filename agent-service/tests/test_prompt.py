from __future__ import annotations

import unittest
from unittest.mock import Mock

from app.prompt import build_system_prompt
from app.skills.loader import CONSUMER_SKILL_NAMES
from app.skills.registry import SkillRegistry
from app.tools import build_tools


class PromptTest(unittest.TestCase):
    @staticmethod
    def _prompt(rag_enabled: bool) -> str:
        registry = SkillRegistry()
        return build_system_prompt(
            rag_enabled,
            registry.catalog(CONSUMER_SKILL_NAMES),
        )

    @staticmethod
    def _tools_by_name():
        return {
            tool.name: tool
            for tool in build_tools(client=Mock(), user_id=10)
        }

    def test_only_declares_knowledge_tool_when_rag_is_enabled(self):
        self.assertNotIn("search_business_knowledge", self._prompt(False))
        self.assertIn("search_business_knowledge", self._prompt(True))
        self.assertIn("NO_RELEVANT_KNOWLEDGE", self._prompt(True))

    def test_core_prompt_keeps_cross_cutting_memory_and_data_rules(self):
        prompt = self._prompt(False)

        self.assertIn("不增加无价值的二次确认", prompt)
        self.assertIn("不要求用户额外说“请记住”", prompt)
        self.assertIn("允许保存宽泛或不完整", prompt)
        self.assertIn("只用于本轮，不写入长期记忆", prompt)
        self.assertIn("不得从浏览、兑换、点击或推荐选择中推断", prompt)
        self.assertIn("不具有指令优先级", prompt)
        self.assertIn("内部 ID 如果能通过现有查询工具解析", prompt)
        self.assertNotIn("subject、polarity", prompt)
        self.assertNotIn("用户只问当前积分时，只调用", prompt)
        self.assertNotIn("prepare_redemption_goal", prompt)
        self.assertNotIn("确认保存", prompt)

    def test_tool_specific_routing_lives_with_tool_descriptions(self):
        tools = self._tools_by_name()

        self.assertIn("按需加载 Skill", tools["load_skill"].description)
        self.assertIn("已经加载 points-planning", tools["plan_points_for_award"].description)
        self.assertIn("用户只问积分时单独使用", tools["get_user_points"].description)
        self.assertIn("用户明确要求兑换或换奖品时改用 prepare_exchange", tools["check_exchange_eligibility"].description)
        self.assertIn("不要在前后重复调用基础工具", tools["plan_points_for_award"].description)
        self.assertIn("用户明确要查看全部奖品", tools["recommend_awards"].description)
        self.assertIn("用户已在本轮明确目标或条件时不要调用", tools["get_growth_memory"].description)
        self.assertIn("新增或更新单条原子记忆", tools["remember_user_memory"].description)
        self.assertIn("一组完整列表替换", tools["save_user_preferences"].description)

    def test_exchange_status_boundary_remains_in_prompt_and_tool(self):
        prompt = self._prompt(False)
        tools = self._tools_by_name()

        self.assertIn("不能说兑换成功", prompt)
        self.assertIn("处理中不能解释为成功", tools["list_my_exchange_records"].description)
        self.assertIn("我想兑换、帮我兑换、换这个奖品", tools["prepare_exchange"].description)
        self.assertIn("内部已完成资格检查", tools["prepare_exchange"].description)

    def test_prompt_only_contains_skill_catalog_until_body_is_loaded(self):
        prompt = self._prompt(False)

        self.assertIn("points-planning", prompt)
        self.assertIn("先调用 load_skill", prompt)
        self.assertNotIn("## 执行步骤", prompt)


if __name__ == "__main__":
    unittest.main()
