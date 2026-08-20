from __future__ import annotations

import unittest

from app.config import Settings
from app.runtime import AgentRuntime


class FakeClient:
    def close(self) -> None:
        raise AssertionError("外部注入的 Client 不应由 Runtime 关闭")


class FakeSkillRegistry:
    def trace_metadata(self):
        return [{"skill_name": "points-planning", "skill_version": "1.0.0"}]


class AgentRuntimeTest(unittest.TestCase):
    def test_reuses_user_agent_and_evicts_least_recently_used_entry(self):
        built_user_ids: list[int] = []

        def builder(settings, client, user_id, skill_registry):
            built_user_ids.append(user_id)
            return {"user_id": user_id}

        def runner(agent, message):
            return f"user={agent['user_id']} message={message}"

        runtime = AgentRuntime(
            Settings(llm_api_key="test-key", agent_cache_size=2),
            client=FakeClient(),
            skill_registry=FakeSkillRegistry(),
            agent_builder=builder,
            agent_runner=runner,
        )

        first, _ = runtime.answer(10, "第一次")
        second, _ = runtime.answer(10, "第二次")
        runtime.answer(11, "用户11")
        runtime.answer(12, "用户12")

        self.assertEqual("user=10 message=第一次", first)
        self.assertEqual("user=10 message=第二次", second)
        self.assertEqual([10, 11, 12], built_user_ids)
        self.assertEqual(2, runtime.health()["cached_agents"])

        runtime.answer(10, "重新创建")
        self.assertEqual([10, 11, 12, 10], built_user_ids)
        runtime.close()

    def test_requires_model_key_before_serving_requests(self):
        with self.assertRaisesRegex(ValueError, "LLM_API_KEY"):
            AgentRuntime(Settings(), client=FakeClient())


if __name__ == "__main__":
    unittest.main()
