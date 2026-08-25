from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

from app.operator.agent import (
    build_operator_system_prompt,
    run_operator_agent,
    select_operator_tools,
)
from app.operator.intent import (
    OperatorIntent,
    OperatorIntentRouter,
    fallback_operator_intent,
)


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

        self.assertIn("工作台提交、审核和发布", prompt)
        self.assertIn("不能声称已经修改线上规则或触达用户", prompt)
        self.assertIn("现金预算", prompt)
        self.assertIn("积分发放上限", prompt)

    def test_knowledge_prompt_answers_question_before_capability_boundary(self):
        prompt = build_operator_system_prompt(
            knowledge_enabled=True,
            intent=OperatorIntent.KNOWLEDGE_QUERY,
        )

        self.assertIn("直接回答用户询问", prompt)
        self.assertIn("不得把能力边界声明当作答案", prompt)
        self.assertIn("发布活动记录不等于", prompt)
        self.assertIn("list_campaign_activities", prompt)
        self.assertIn("不得要求用户提供内部活动 ID", prompt)
        self.assertIn("不得虚构金额收益", prompt)
        self.assertIn("禁止返回功能菜单", prompt)
        self.assertIn("必须立即调用 list_campaign_activities", prompt)

    def test_intent_selects_only_required_tools(self):
        tools = [
            SimpleNamespace(name="get_campaign_planning_snapshot"),
            SimpleNamespace(name="list_campaign_activities"),
            SimpleNamespace(name="get_campaign_funnel"),
            SimpleNamespace(name="search_operator_knowledge"),
            SimpleNamespace(name="draft_campaign_plan"),
        ]

        knowledge_tools = select_operator_tools(
            tools,
            OperatorIntent.KNOWLEDGE_QUERY,
        )
        action_tools = select_operator_tools(tools, OperatorIntent.ACTION_REQUEST)

        self.assertEqual(
            {
                "get_campaign_planning_snapshot",
                "list_campaign_activities",
                "get_campaign_funnel",
                "search_operator_knowledge",
            },
            {tool.name for tool in knowledge_tools},
        )
        self.assertEqual(
            {"search_operator_knowledge"},
            {tool.name for tool in action_tools},
        )

    def test_structured_router_returns_validated_decision(self):
        class FakeRunnable:
            def invoke(self, messages):
                self.messages = messages
                return {
                    "intent": "KNOWLEDGE_QUERY",
                    "confidence": 0.96,
                    "requested_action": None,
                    "reason": "用户在询问方法",
                }

        runnable = FakeRunnable()
        router = OperatorIntentRouter(runnable)

        decision = router.classify("怎么触达用户？", "request-intent-1")

        self.assertEqual(OperatorIntent.KNOWLEDGE_QUERY, decision.intent)
        self.assertEqual(0.96, decision.confidence)
        self.assertEqual("怎么触达用户？", runnable.messages[-1].content)

    def test_fallback_only_treats_explicit_execution_as_action(self):
        self.assertEqual(
            OperatorIntent.KNOWLEDGE_QUERY,
            fallback_operator_intent("怎么触达用户？").intent,
        )
        self.assertEqual(
            OperatorIntent.PLAN_REQUEST,
            fallback_operator_intent("帮我设计用户触达方案").intent,
        )
        self.assertEqual(
            OperatorIntent.ACTION_REQUEST,
            fallback_operator_intent("现在向这些用户发送通知").intent,
        )

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
