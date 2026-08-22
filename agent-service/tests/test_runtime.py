from __future__ import annotations

import unittest

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph

from app.agent import append_agent_turn
from app.config import Settings
from app.confirmation_store import ConfirmationStatus, ConfirmationStore
from app.models import ToolEnvelope
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

    def update_state(self, config: dict, values: dict) -> None:
        self.state_updates.append((config, values))


class AgentRuntimeTest(unittest.TestCase):
    def test_append_agent_turn_updates_real_langgraph_message_history(self):
        graph = StateGraph(MessagesState)
        graph.add_node("passthrough", lambda state: {})
        graph.add_edge(START, "passthrough")
        agent = graph.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "session-history"}}
        agent.invoke(
            {"messages": [{"role": "assistant", "content": "等待确认"}]},
            config=config,
        )

        append_agent_turn(agent, "确认兑换", "兑换请求已进入处理流程", "session-history")

        messages = agent.get_state(config).values["messages"]
        self.assertEqual(
            ["等待确认", "确认兑换", "兑换请求已进入处理流程"],
            [message.content for message in messages],
        )

    def test_reuses_user_agent_and_evicts_least_recently_used_entry(self):
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
        ):
            built_user_ids.append(user_id)
            self.assertIs(checkpointer, actual_checkpointer)
            self.assertIsNone(knowledge_search)
            return {"user_id": user_id}

        def runner(agent, message, thread_id, request_id):
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

        first, _ = runtime.answer(10, "session-a", "第一次")
        second, _ = runtime.answer(10, "session-a", "第二次")
        pending = confirmation_store.create(
            user_id=10,
            session_id="user:10:session:session-a",
            award_id=6,
            award_name="手表",
            current_points=300,
            required_points=200,
            request_id="request-runtime",
        )
        runtime.answer(11, "session-b", "用户11")
        runtime.answer(12, "session-c", "用户12")

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

        runtime.answer(10, "session-d", "重新创建")
        self.assertEqual([10, 11, 12, 10], built_user_ids)
        runtime.close()

    def test_expires_idle_session_and_cancels_pending_confirmation(self):
        current_time = [100.0]
        checkpointer = FakeCheckpointer()
        store = ConfirmationStore(token_factory=lambda: "expired-session-token")

        def builder(*args):
            return {"agent": "used"}

        def runner(agent, message, thread_id, request_id):
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
        runtime.answer(10, "session-a", "第一次")
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
        runtime.answer(11, "session-b", "触发过期清理")

        self.assertIn(
            "user:10:session:session-a",
            checkpointer.deleted_thread_ids,
        )
        self.assertEqual(
            ConfirmationStatus.CANCELLED,
            store.snapshot(pending.confirmation_id).status,
        )
        self.assertEqual(1, runtime.health()["cached_sessions"])

    def test_same_session_id_is_isolated_by_user_id(self):
        thread_ids: list[str] = []

        def builder(
            settings,
            client,
            user_id,
            skill_registry,
            checkpointer,
            confirmation_store,
            knowledge_search,
        ):
            return {"user_id": user_id}

        def runner(agent, message, thread_id, request_id):
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

        runtime.answer(10, "same-session", "用户10")
        runtime.answer(11, "same-session", "用户11")

        self.assertEqual(
            [
                "user:10:session:same-session",
                "user:11:session:same-session",
            ],
            thread_ids,
        )

    def test_requires_model_key_before_serving_requests(self):
        with self.assertRaisesRegex(ValueError, "LLM_API_KEY"):
            AgentRuntime(Settings(), client=FakeClient())

    def test_explicit_confirmation_uses_deterministic_route_without_model(self):
        client = FakeClient()
        runner_calls: list[str] = []
        store = ConfirmationStore(token_factory=lambda: "runtime-confirmation-token")
        agent = FakeAgent()

        def builder(*args):
            return agent

        def runner(agent, message, thread_id, request_id):
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

        answer, _ = runtime.answer(
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

    def test_ambiguous_message_stays_with_model_and_keeps_pending(self):
        client = FakeClient()
        store = ConfirmationStore(token_factory=lambda: "runtime-confirmation-token")

        def builder(*args):
            return {"agent": "used"}

        def runner(agent, message, thread_id, request_id):
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

        answer, _ = runtime.answer(10, "session-a", "我再想想", "request-next")

        self.assertEqual("请明确确认或取消", answer)
        self.assertEqual(0, client.submit_calls)
        pending = runtime.pending_exchange(10, "session-a")
        self.assertIsNotNone(pending)
        self.assertEqual("手表", pending.award_name)


if __name__ == "__main__":
    unittest.main()
