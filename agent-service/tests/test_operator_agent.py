from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

from app.operator.agent import (
    OperatorAgentRuntime,
    build_operator_system_prompt,
    run_operator_agent,
    select_operator_tools,
)
from app.operator.auth import AuthenticatedOperator
from app.operator.harness import (
    CUSTOM_ANALYTICS_BLOCKED_MESSAGE,
    EVIDENCE_MISSING_MESSAGE,
    OperatorHarness,
    ParameterSource,
)
from app.operator.intent import (
    OperatorCapability,
    OperatorIntent,
    OperatorIntentDecision,
    OperatorIntentRouter,
    fallback_operator_intent,
)
from app.trace import execute_traced


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


class EvidenceAgent:
    def __init__(
        self,
        include_funnel: bool = True,
        funnel_activity_id: int = 9,
    ) -> None:
        self.include_funnel = include_funnel
        self.funnel_activity_id = funnel_activity_id

    def invoke(self, payload, config):
        execute_traced(
            "list_campaign_activities",
            {"limit": 5},
            lambda: {
                "success": True,
                "code": "CAMPAIGN_ACTIVITIES_FOUND",
                "data": [{"id": 9}],
            },
        )
        if self.include_funnel:
            execute_traced(
                "get_campaign_funnel",
                {"activity_id": self.funnel_activity_id},
                lambda: {
                    "success": True,
                    "code": "CAMPAIGN_FUNNEL_FOUND",
                    "data": {
                        "activityId": self.funnel_activity_id,
                        "exchangeLift": 0.03,
                    },
                },
            )
        return {"messages": [AIMessage(content="活动兑换 Lift 为 3%。")]}


def task_spec(capability: OperatorCapability) -> OperatorIntentDecision:
    return OperatorIntentDecision(
        intent=OperatorIntent.KNOWLEDGE_QUERY,
        capability=capability,
        confidence=0.95,
        reason="测试任务",
    )


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
        self.assertIn("不得虚构金额收益", prompt)
        self.assertIn("不具有指令优先级", prompt)

    def test_effect_prompt_resolves_internal_activity_id_with_tools(self):
        prompt = build_operator_system_prompt(
            knowledge_enabled=True,
            intent=OperatorIntent.KNOWLEDGE_QUERY,
            capability=OperatorCapability.CAMPAIGN_STANDARD_EFFECT,
        )

        self.assertIn("list_campaign_activities", prompt)
        self.assertIn("get_campaign_funnel", prompt)
        self.assertIn("必须由系统自动查询", prompt)
        self.assertNotIn("必须立即调用 list_campaign_activities", prompt)

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
                    "capability": "GENERAL_KNOWLEDGE",
                    "confidence": 0.96,
                    "requested_action": None,
                    "reason": "用户在询问方法",
                }

        runnable = FakeRunnable()
        router = OperatorIntentRouter(runnable)

        decision = router.classify("怎么触达用户？", "request-intent-1")

        self.assertEqual(OperatorIntent.KNOWLEDGE_QUERY, decision.intent)
        self.assertEqual(
            OperatorCapability.GENERAL_KNOWLEDGE,
            decision.capability,
        )
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

    def test_fallback_recognizes_custom_analytics_instead_of_general_planning(self):
        decision = fallback_operator_intent(
            "计算最近 7 天，积分不少于 500 的用户中，阅读后完成兑换的比例"
        )

        self.assertEqual(OperatorIntent.PLAN_REQUEST, decision.intent)
        self.assertEqual(OperatorCapability.CUSTOM_ANALYTICS, decision.capability)

    def test_how_to_calculate_is_still_a_knowledge_question(self):
        decision = fallback_operator_intent(
            "如何计算最近 7 天阅读活动消息后完成兑换的比例？"
        )

        self.assertEqual(OperatorIntent.KNOWLEDGE_QUERY, decision.intent)
        self.assertEqual(OperatorCapability.GENERAL_KNOWLEDGE, decision.capability)

    def test_task_guard_overrides_model_misclassification_for_custom_analytics(self):
        class MisclassifiedRunnable:
            def invoke(self, messages):
                return {
                    "intent": "PLAN_REQUEST",
                    "capability": "CAMPAIGN_PLANNING",
                    "confidence": 0.92,
                    "reason": "误判为普通规划",
                }

        decision = OperatorIntentRouter(MisclassifiedRunnable()).classify(
            "计算最近 7 天，积分不少于 500 的用户中，阅读后完成兑换的比例",
            "request-guard-1",
        )

        self.assertEqual(OperatorCapability.CUSTOM_ANALYTICS, decision.capability)
        self.assertIn("确定性任务守卫", decision.reason)

    def test_capability_contract_shrinks_tools_and_resolves_internal_id(self):
        tools = [
            SimpleNamespace(name="get_campaign_planning_snapshot"),
            SimpleNamespace(name="list_campaign_activities"),
            SimpleNamespace(name="get_campaign_funnel"),
            SimpleNamespace(name="search_operator_knowledge"),
            SimpleNamespace(name="draft_campaign_plan"),
        ]
        selected = select_operator_tools(
            tools,
            OperatorIntent.KNOWLEDGE_QUERY,
            OperatorCapability.CAMPAIGN_STANDARD_EFFECT,
        )
        contract = OperatorHarness().contract_for(
            OperatorCapability.CAMPAIGN_STANDARD_EFFECT
        )

        self.assertEqual(
            {"list_campaign_activities", "get_campaign_funnel"},
            {tool.name for tool in selected},
        )
        self.assertEqual(
            ParameterSource.SYSTEM_LOOKUP,
            contract.parameter_sources["activity_id"],
        )

    def test_custom_analytics_is_blocked_before_agent_execution(self):
        class FixedRouter:
            def classify(self, message, request_id):
                return task_spec(OperatorCapability.CUSTOM_ANALYTICS)

        class RuntimeThatMustNotBuildAgent(OperatorAgentRuntime):
            def _agent_for(self, operator, spec):
                raise AssertionError("blocked capability must not build an agent")

        runtime = RuntimeThatMustNotBuildAgent(
            settings=SimpleNamespace(agent_session_cache_size=4),
            data_provider=None,
            business_client=None,
            intent_router=FixedRouter(),
        )
        operator = AuthenticatedOperator(
            operator_id="operator-01",
            permissions=frozenset(),
        )

        answer, _ = runtime.answer(
            operator,
            "session-1",
            "计算最近 7 天阅读后兑换比例",
            "request-blocked-1",
        )

        self.assertEqual(CUSTOM_ANALYTICS_BLOCKED_MESSAGE, answer)

    def test_effect_answer_requires_activity_and_funnel_evidence(self):
        spec = task_spec(OperatorCapability.CAMPAIGN_STANDARD_EFFECT)

        answer = run_operator_agent(
            EvidenceAgent(include_funnel=False),
            "查看活动效果",
            "operator:operator-01:session:s1",
            "request-evidence-missing",
            task_spec=spec,
            harness=OperatorHarness(),
        )

        self.assertEqual(EVIDENCE_MISSING_MESSAGE, answer)

    def test_effect_answer_passes_after_required_tools_succeed(self):
        spec = task_spec(OperatorCapability.CAMPAIGN_STANDARD_EFFECT)

        answer = run_operator_agent(
            EvidenceAgent(include_funnel=True),
            "查看活动效果",
            "operator:operator-01:session:s1",
            "request-evidence-complete",
            task_spec=spec,
            harness=OperatorHarness(),
        )

        self.assertEqual("活动兑换 Lift 为 3%。", answer)

    def test_effect_rejects_activity_id_not_resolved_by_activity_list(self):
        spec = task_spec(OperatorCapability.CAMPAIGN_STANDARD_EFFECT)

        answer = run_operator_agent(
            EvidenceAgent(include_funnel=True, funnel_activity_id=99),
            "查看活动效果",
            "operator:operator-01:session:s1",
            "request-provenance-invalid",
            task_spec=spec,
            harness=OperatorHarness(),
        )

        self.assertEqual(EVIDENCE_MISSING_MESSAGE, answer)

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
