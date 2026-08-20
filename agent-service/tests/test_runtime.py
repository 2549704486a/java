from __future__ import annotations

import unittest

from app.config import Settings
from app.confirmation_store import ConfirmationStatus, ConfirmationStore
from app.runtime import AgentRuntime


class FakeClient:
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


class AgentRuntimeTest(unittest.TestCase):
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
        ):
            built_user_ids.append(user_id)
            self.assertIs(checkpointer, actual_checkpointer)
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

    def test_same_session_id_is_isolated_by_user_id(self):
        thread_ids: list[str] = []

        def builder(
            settings,
            client,
            user_id,
            skill_registry,
            checkpointer,
            confirmation_store,
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


if __name__ == "__main__":
    unittest.main()
