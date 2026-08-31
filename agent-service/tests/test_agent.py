from __future__ import annotations

import json
import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import ensure_knowledge_citations, run_agent


class FakeAgent:
    def __init__(self) -> None:
        self.config = None

    async def ainvoke(self, payload, config):
        self.config = config
        return {"messages": [type("Message", (), {"content": "ok"})()]}


class RunAgentTest(unittest.IsolatedAsyncioTestCase):
    async def test_passes_thread_id_to_checkpointer_config(self):
        agent = FakeAgent()

        answer = await run_agent(
            agent,
            "继续规划",
            "user:10:session:session-a",
            "request-001",
        )

        self.assertEqual("ok", answer)
        self.assertEqual(12, agent.config["recursion_limit"])
        self.assertEqual(
            "user:10:session:session-a",
            agent.config["configurable"]["thread_id"],
        )

    def test_appends_real_tool_citations_when_model_omits_them(self):
        payload = {
            "data": {
                "matches": [
                    {"citation": "[积分与任务规则 / 规则说明]"},
                    {"citation": "[兑换规则与状态 / 实时信息边界]"},
                ]
            }
        }
        messages = [
            ToolMessage(
                content=json.dumps(payload, ensure_ascii=False),
                tool_call_id="call-1",
                name="search_business_knowledge",
            ),
            AIMessage(content="任务完成后仍需要领取奖励。"),
        ]

        answer = ensure_knowledge_citations(messages, messages[-1].content)

        self.assertIn("检索来源：", answer)
        self.assertIn("[积分与任务规则 / 规则说明]", answer)
        self.assertNotIn("[兑换规则与状态 / 实时信息边界]", answer)

    def test_does_not_duplicate_existing_tool_citation(self):
        citation = "[积分与任务规则 / 规则说明]"
        payload = {"data": {"matches": [{"citation": citation}]}}
        messages = [
            ToolMessage(
                content=json.dumps(payload, ensure_ascii=False),
                tool_call_id="call-1",
                name="search_business_knowledge",
            ),
            AIMessage(content=f"任务完成后仍需要领取奖励。{citation}{citation}"),
        ]

        answer = ensure_knowledge_citations(messages, messages[-1].content)

        self.assertEqual(1, answer.count(citation))

    def test_reads_citations_from_block_tool_content(self):
        citation = "[积分与任务规则 / 规则说明]"
        payload = json.dumps(
            {"data": {"matches": [{"citation": citation}]}},
            ensure_ascii=False,
        )
        messages = [
            ToolMessage(
                content=[{"type": "text", "text": payload}],
                tool_call_id="call-1",
                name="search_business_knowledge",
            ),
            AIMessage(content="任务完成后仍需要领取奖励。"),
        ]

        answer = ensure_knowledge_citations(messages, messages[-1].content)

        self.assertIn(citation, answer)

    def test_does_not_reuse_previous_turn_citation(self):
        stale_citation = "[活动预算口径变更通知 / 适用问题]"
        historical_payload = {
            "data": {"matches": [{"citation": stale_citation}]}
        }
        messages = [
            HumanMessage(content="活动预算口径是什么？"),
            ToolMessage(
                content=json.dumps(historical_payload, ensure_ascii=False),
                tool_call_id="call-old",
                name="search_business_knowledge",
            ),
            AIMessage(content=f"现金预算使用人民币。{stale_citation}"),
            HumanMessage(content="怎么触达用户？"),
            AIMessage(content=f"可以使用站内信。\n\n检索来源：{stale_citation}"),
        ]

        answer = ensure_knowledge_citations(messages, messages[-1].content)

        self.assertEqual("可以使用站内信。", answer)


if __name__ == "__main__":
    unittest.main()
