from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph

from app.agent import append_agent_turn
from app.config import Settings
from app.exchange.confirmation_store import ConfirmationStatus, ConfirmationStore
from app.models import ToolEnvelope
from app.mcp_award_tool import McpAwardToolBinding
from app.runtime import AgentRuntime


class FakeClient:
    def __init__(self) -> None:
        self.submit_calls = 0

    def submit_exchange(self, **kwargs) -> ToolEnvelope:
        self.submit_calls += 1
        return ToolEnvelope(
            success=True,
            code="EXCHANGE_PROCESSING",
            data=None,
            message="兑换请求已进入处理流程",
            retryable=False,
        )

    def close(self) -> None:
        raise AssertionError("外部注入的 Client 不应由 Runtime 关闭")


class FakeSkillRegistry:
    def trace_metadata(self):
        return [{"skill_name": "points-planning", "skill_version": "1.0.0"}]


class FakeCheckpointer:
    def __init__(self) -> None:
        self.deleted_thread_ids: list[str] = []

    def delete_thread(self, thread_id: str) -> None:
        self.deleted_thread_ids.append(thread_id)


class FakeAgent:
    def __init__(self) -> None:
        self.state_updates: list[tuple[dict, dict]] = []

    async def aupdate_state(self, config: dict, values: dict) -> None:
        self.state_updates.append((config, values))


class AgentRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_append_agent_turn_updates_real_langgraph_message_history(self):
        graph = StateGraph(MessagesState)
        graph.add_node("passthrough", lambda state: {})
        graph.add_edge(START, "passthrough")
        agent = graph.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "session-history"}}
        await agent.ainvoke(
            {"messages": [{"role": "assistant", "content": "等待确认"}]},
            config=config,
        )

        await append_agent_turn(
            agent,
            "确认兑换",
            "兑换请求已进入处理流程",
            "session-history",
        )

        messages = agent.get_state(config).values["messages"]
        self.assertEqual(
            ["等待确认", "确认兑换", "兑换请求已进入处理流程"],
            [message.content for message in messages],
        )

    async def test_reuses_user_agent_and_evicts_least_recently_used_entry(self):
        built_user_ids: list[int] = []

        checkpointer = FakeCheckpointer()
        confirmation_store = ConfirmationStore(
            token_factory=lambda: "runtime-confirmation-token"
        )

        def builder(
            settings,
            client,
            user_id,
            skill_registry,
            actual_checkpointer,
            confirmation_store,
            knowledge_search,
            growth_memory_store,
        ):
            built_user_ids.append(user_id)
            self.assertIs(checkpointer, actual_checkpointer)
            self.assertIsNone(knowledge_search)
            return {"user_id": user_id}

        async def runner(agent, message, thread_id, request_id):
            return f"user={agent['user_id']} thread={thread_id} message={message}"

        runtime = AgentRuntime(
            Settings(
                llm_api_key="test-key",
                agent_cache_size=2,
                agent_session_cache_size=2,
            ),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
            checkpointer=checkpointer,
            agent_builder=builder,
            agent_runner=runner,
            confirmation_store=confirmation_store,
        )

        first, _ = await runtime.answer(10, "session-a", "第一次")
        second, _ = await runtime.answer(10, "session-a", "第二次")
        pending = confirmation_store.create(
            user_id=10,
            session_id="user:10:session:session-a",
            award_id=6,
            award_name="手表",
            current_points=300,
            required_points=200,
            request_id="request-runtime",
        )
        await runtime.answer(11, "session-b", "用户11")
        await runtime.answer(12, "session-c", "用户12")

        self.assertEqual(
            "user=10 thread=user:10:session:session-a message=第一次",
            first,
        )
        self.assertEqual(
            "user=10 thread=user:10:session:session-a message=第二次",
            second,
        )
        self.assertEqual([10, 11, 12], built_user_ids)
        self.assertEqual(2, runtime.health()["cached_agents"])
        self.assertEqual(2, runtime.health()["cached_sessions"])
        self.assertEqual(3600, runtime.health()["session_ttl_seconds"])
        self.assertEqual(6000, runtime.health()["context_max_tokens"])
        self.assertEqual(12, runtime.health()["context_max_turns"])
        self.assertEqual(
            ["user:10:session:session-a"],
            checkpointer.deleted_thread_ids,
        )
        self.assertEqual(
            ConfirmationStatus.CANCELLED,
            confirmation_store.snapshot(pending.confirmation_id).status,
        )

        await runtime.answer(10, "session-d", "重新创建")
        self.assertEqual([10, 11, 12, 10], built_user_ids)
        runtime.close()

    async def test_expires_idle_session_and_cancels_pending_confirmation(self):
        current_time = [100.0]
        checkpointer = FakeCheckpointer()
        store = ConfirmationStore(token_factory=lambda: "expired-session-token")

        def builder(*args):
            return {"agent": "used"}

        async def runner(agent, message, thread_id, request_id):
            return "ok"

        runtime = AgentRuntime(
            Settings(
                llm_api_key="test-key",
                agent_session_ttl_seconds=5,
            ),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
            checkpointer=checkpointer,
            agent_builder=builder,
            agent_runner=runner,
            confirmation_store=store,
            clock=lambda: current_time[0],
        )
        await runtime.answer(10, "session-a", "第一次")
        pending = store.create(
            user_id=10,
            session_id="user:10:session:session-a",
            award_id=6,
            award_name="智能手表",
            current_points=900,
            required_points=600,
            request_id="request-prepare",
        )

        current_time[0] = 106.0
        await runtime.answer(11, "session-b", "触发过期清理")

        self.assertIn(
            "user:10:session:session-a",
            checkpointer.deleted_thread_ids,
        )
        self.assertEqual(
            ConfirmationStatus.CANCELLED,
            store.snapshot(pending.confirmation_id).status,
        )
        self.assertEqual(1, runtime.health()["cached_sessions"])

    async def test_same_session_id_is_isolated_by_user_id(self):
        thread_ids: list[str] = []

        def builder(
            settings,
            client,
            user_id,
            skill_registry,
            checkpointer,
            confirmation_store,
            knowledge_search,
            growth_memory_store,
        ):
            return {"user_id": user_id}

        async def runner(agent, message, thread_id, request_id):
            thread_ids.append(thread_id)
            return "ok"

        runtime = AgentRuntime(
            Settings(llm_api_key="test-key"),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
            checkpointer=FakeCheckpointer(),
            agent_builder=builder,
            agent_runner=runner,
        )

        await runtime.answer(10, "same-session", "用户10")
        await runtime.answer(11, "same-session", "用户11")

        self.assertEqual(
            [
                "user:10:session:same-session",
                "user:11:session:same-session",
            ],
            thread_ids,
        )

    async def test_requires_model_key_before_serving_requests(self):
        with self.assertRaisesRegex(ValueError, "LLM_API_KEY"):
            AgentRuntime(Settings(), client=FakeClient())

    async def test_explicit_confirmation_uses_deterministic_route_without_model(self):
        client = FakeClient()
        runner_calls: list[str] = []
        store = ConfirmationStore(token_factory=lambda: "runtime-confirmation-token")
        agent = FakeAgent()

        def builder(*args):
            return agent

        async def runner(agent, message, thread_id, request_id):
            runner_calls.append(message)
            return "不应调用模型"

        runtime = AgentRuntime(
            Settings(llm_api_key="test-key"),
            client=client,
            skill_registry=FakeSkillRegistry(),
            checkpointer=FakeCheckpointer(),
            agent_builder=builder,
            agent_runner=runner,
            confirmation_store=store,
        )
        record = store.create(
            user_id=10,
            session_id="user:10:session:session-a",
            award_id=6,
            award_name="手表",
            current_points=300,
            required_points=200,
            request_id="request-prepare",
        )

        answer, _ = await runtime.answer(
            10,
            "session-a",
            "确认兑换！",
            "request-confirm",
        )

        self.assertEqual("兑换请求已进入处理流程", answer)
        self.assertEqual(1, client.submit_calls)
        self.assertEqual([], runner_calls)
        self.assertEqual(1, len(agent.state_updates))
        config, values = agent.state_updates[0]
        self.assertEqual(
            "user:10:session:session-a",
            config["configurable"]["thread_id"],
        )
        self.assertEqual("确认兑换！", values["messages"][0].content)
        self.assertEqual("兑换请求已进入处理流程", values["messages"][1].content)
        self.assertEqual(
            ConfirmationStatus.PROCESSING,
            store.snapshot(record.confirmation_id).status,
        )
        self.assertIsNone(runtime.pending_exchange(10, "session-a"))

    async def test_ambiguous_message_stays_with_model_and_keeps_pending(self):
        client = FakeClient()
        store = ConfirmationStore(token_factory=lambda: "runtime-confirmation-token")

        def builder(*args):
            return {"agent": "used"}

        async def runner(agent, message, thread_id, request_id):
            return "请明确确认或取消"

        runtime = AgentRuntime(
            Settings(llm_api_key="test-key"),
            client=client,
            skill_registry=FakeSkillRegistry(),
            checkpointer=FakeCheckpointer(),
            agent_builder=builder,
            agent_runner=runner,
            confirmation_store=store,
        )
        store.create(
            user_id=10,
            session_id="user:10:session:session-a",
            award_id=6,
            award_name="手表",
            current_points=300,
            required_points=200,
            request_id="request-prepare",
        )

        answer, _ = await runtime.answer(
            10,
            "session-a",
            "我再想想",
            "request-next",
        )

        self.assertEqual("请明确确认或取消", answer)
        self.assertEqual(0, client.submit_calls)
        pending = runtime.pending_exchange(10, "session-a")
        self.assertIsNotNone(pending)
        self.assertEqual("手表", pending.award_name)

    async def test_same_session_requests_run_in_order(self):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        events: list[str] = []

        async def runner(agent, message, thread_id, request_id):
            events.append(f"start:{message}")
            if message == "first":
                first_started.set()
                await release_first.wait()
            events.append(f"end:{message}")
            return message

        runtime = AgentRuntime(
            Settings(llm_api_key="test-key"),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
            checkpointer=FakeCheckpointer(),
            agent_builder=lambda *args: {"agent": "used"},
            agent_runner=runner,
        )

        first = asyncio.create_task(runtime.answer(10, "same", "first"))
        await first_started.wait()
        second = asyncio.create_task(runtime.answer(10, "same", "second"))
        await asyncio.sleep(0)
        self.assertEqual(["start:first"], events)

        release_first.set()
        await asyncio.gather(first, second)
        self.assertEqual(
            ["start:first", "end:first", "start:second", "end:second"],
            events,
        )

    async def test_agent_failure_releases_session_lock(self):
        calls = 0

        async def runner(agent, message, thread_id, request_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("model failed")
            return "recovered"

        runtime = AgentRuntime(
            Settings(llm_api_key="test-key"),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
            checkpointer=FakeCheckpointer(),
            agent_builder=lambda *args: {"agent": "used"},
            agent_runner=runner,
        )

        with self.assertRaisesRegex(RuntimeError, "model failed"):
            await runtime.answer(10, "same", "first")
        answer, _ = await runtime.answer(10, "same", "second")

        self.assertEqual("recovered", answer)

    async def test_cancelled_waiter_releases_session_reference(self):
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def runner(agent, message, thread_id, request_id):
            if message == "first":
                first_started.set()
                await release_first.wait()
            return message

        runtime = AgentRuntime(
            Settings(llm_api_key="test-key"),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
            checkpointer=FakeCheckpointer(),
            agent_builder=lambda *args: {"agent": "used"},
            agent_runner=runner,
        )

        first = asyncio.create_task(runtime.answer(10, "same", "first"))
        await first_started.wait()
        cancelled = asyncio.create_task(runtime.answer(10, "same", "cancelled"))
        await asyncio.sleep(0)
        cancelled.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled

        release_first.set()
        await first
        self.assertEqual(0, runtime._sessions["user:10:session:same"].in_use)

    async def test_rest_initialization_does_not_discover_mcp(self):
        runtime = AgentRuntime(
            Settings(llm_api_key="test-key"),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
        )
        discover = AsyncMock()

        with patch("app.runtime.discover_award_detail_mcp_tool", discover):
            await runtime.initialize()

        discover.assert_not_awaited()
        self.assertEqual("rest", runtime.health()["award_detail_transport"])
        self.assertFalse(runtime.health()["mcp_award_tool_ready"])

    async def test_mcp_initialization_injects_remote_tool_into_user_agent(self):
        remote_tool = type("RemoteTool", (), {"name": "get_award_detail"})()
        binding = McpAwardToolBinding(
            tool=remote_tool,
            server_name="java-business",
            discovered_tool_count=1,
        )
        received_tools = []

        def builder(*args, award_detail_tool=None):
            received_tools.append(award_detail_tool)
            return {"agent": "used"}

        async def runner(agent, message, thread_id, request_id):
            return "ok"

        runtime = AgentRuntime(
            Settings(
                llm_api_key="test-key",
                award_detail_transport="mcp",
            ),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
            agent_builder=builder,
            agent_runner=runner,
        )

        with patch(
            "app.runtime.discover_award_detail_mcp_tool",
            new=AsyncMock(return_value=binding),
        ):
            await runtime.initialize()
        await runtime.answer(10, "session-a", "查询奖品")

        self.assertEqual([remote_tool], received_tools)
        self.assertTrue(runtime.health()["mcp_award_tool_ready"])

    async def test_mcp_initialization_failure_is_not_replaced_by_rest(self):
        runtime = AgentRuntime(
            Settings(
                llm_api_key="test-key",
                award_detail_transport="mcp",
            ),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
        )

        with patch(
            "app.runtime.discover_award_detail_mcp_tool",
            new=AsyncMock(side_effect=RuntimeError("mcp offline")),
        ):
            with self.assertRaisesRegex(RuntimeError, "mcp offline"):
                await runtime.initialize()

        with self.assertRaisesRegex(RuntimeError, "尚未初始化"):
            await runtime.answer(10, "session-a", "查询奖品")

if __name__ == "__main__":
    unittest.main()
