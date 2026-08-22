from __future__ import annotations

import unittest

from app.prompt import build_system_prompt


class PromptTest(unittest.TestCase):
    def test_only_declares_knowledge_tool_when_rag_is_enabled(self):
        self.assertNotIn("search_business_knowledge", build_system_prompt(False))
        self.assertIn("search_business_knowledge", build_system_prompt(True))
        self.assertIn("NO_RELEVANT_KNOWLEDGE", build_system_prompt(True))

    def test_stable_memory_statement_writes_without_second_confirmation(self):
        prompt = build_system_prompt(False)

        self.assertIn("save_redemption_goal", prompt)
        self.assertIn("save_user_preferences", prompt)
        self.assertIn("forget_growth_memory", prompt)
        self.assertIn("不再要求二次确认", prompt)
        self.assertIn("我喜欢数码类奖品", prompt)
        self.assertIn("即使没有说“请记住”", prompt)
        self.assertIn("这次想看数码类", prompt)
        self.assertIn("只作为本轮条件，不写入长期记忆", prompt)
        self.assertIn("不得从用户浏览、兑换或推荐选择中推断偏好", prompt)
        self.assertNotIn("prepare_redemption_goal", prompt)
        self.assertNotIn("确认保存", prompt)


if __name__ == "__main__":
    unittest.main()
