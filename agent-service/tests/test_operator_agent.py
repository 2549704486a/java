from __future__ import annotations

import json
import unittest

from langchain_core.messages import AIMessage, ToolMessage

from app.operator_agent import build_operator_system_prompt, run_operator_agent


class FakeAgent:
    def invoke(self, payload, config):
        self.payload = payload
        self.config = config
        return {
            "messages": [
                ToolMessage(
                    name="search_operator_knowledge",
                    tool_call_id="call-1",
                    content=json.dumps(
                        {
                            "data": {
                                "matches": [
                                    {"citation": "[活动预算制度 / 现金预算]"}
                                ]
                            }
                        },
                        ensure_ascii=False,
                    ),
                ),
                AIMessage(content="现金预算与积分发放上限需要分别约束。"),
            ]
        }


class OperatorAgentTest(unittest.TestCase):
    def test_prompt_keeps_draft_and_publish_boundary(self):
        prompt = build_operator_system_prompt(knowledge_enabled=True)

        self.assertIn("人工审阅", prompt)
        self.assertIn("不能声称已经发布", prompt)
        self.assertIn("现金预算", prompt)
        self.assertIn("积分发放上限", prompt)

    def test_run_operator_agent_preserves_real_knowledge_citation(self):
        agent = FakeAgent()

        answer = run_operator_agent(
            agent,
            "预算口径是什么？",
            "operator:operator-01:session:s1",
            "request-1",
        )

        self.assertIn("现金预算与积分发放上限", answer)
        self.assertIn("[活动预算制度 / 现金预算]", answer)
        self.assertEqual(
            "operator:operator-01:session:s1",
            agent.config["configurable"]["thread_id"],
        )


if __name__ == "__main__":
    unittest.main()
