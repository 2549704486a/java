from __future__ import annotations

import unittest

from app.prompt import build_system_prompt


class PromptTest(unittest.TestCase):
    def test_only_declares_knowledge_tool_when_rag_is_enabled(self):
        self.assertNotIn("search_business_knowledge", build_system_prompt(False))
        self.assertIn("search_business_knowledge", build_system_prompt(True))
        self.assertIn("NO_RELEVANT_KNOWLEDGE", build_system_prompt(True))


if __name__ == "__main__":
    unittest.main()
