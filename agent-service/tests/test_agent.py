from __future__ import annotations

import unittest

from app.agent import run_agent


class FakeAgent:
    def __init__(self) -> None:
        self.config = None

    def invoke(self, payload, config):
        self.config = config
        return {"messages": [type("Message", (), {"content": "ok"})()]}


class RunAgentTest(unittest.TestCase):
    def test_passes_thread_id_to_checkpointer_config(self):
        agent = FakeAgent()

        answer = run_agent(agent, "继续规划", "user:10:session:session-a")

        self.assertEqual("ok", answer)
        self.assertEqual(12, agent.config["recursion_limit"])
        self.assertEqual(
            "user:10:session:session-a",
            agent.config["configurable"]["thread_id"],
        )


if __name__ == "__main__":
    unittest.main()
