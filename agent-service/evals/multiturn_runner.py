from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from app.config import Settings
from app.confirmation_store import ConfirmationStore
from app.execution_context import bind_execution_context
from app.prompt import SYSTEM_PROMPT
from app.skills.registry import SkillRegistry
from app.tools import build_tools
from evals.fixtures import FixtureBusinessApiClient
from evals.runner import (
    build_model,
    collect_usage,
    evaluate_case,
    extract_text,
    find_tool_calls,
    message_trace,
)


ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "multiturn_cases.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="积分规划 Agent 多轮记忆评测")
    parser.add_argument("--ids", help="只运行指定编号，多个编号使用逗号分隔")
    parser.add_argument("--user-id", type=int, default=10)
    parser.add_argument("--output", help="指定结果 JSON 路径")
    return parser.parse_args()


def load_cases(ids: set[str] | None) -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if ids:
        cases = [case for case in cases if case["id"] in ids]
    return cases


def run_case(model, case: dict[str, Any], user_id: int, registry: SkillRegistry):
    client = FixtureBusinessApiClient(case["fixture"])
    confirmation_store = ConfirmationStore()
    agent = create_agent(
        model=model,
        tools=build_tools(client, user_id, registry, confirmation_store),
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )
    config = {
        "recursion_limit": 12,
        "configurable": {"thread_id": f"multiturn:{case['id']}:user:{user_id}"},
    }
    previous_message_count = 0
    previous_backend_count = 0
    turns = []

    for index, turn in enumerate(case["turns"], start=1):
        started = time.perf_counter()
        with bind_execution_context(config["configurable"]["thread_id"]):
            result = agent.invoke(
                {"messages": [{"role": "user", "content": turn["question"]}]},
                config=config,
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        all_messages = result["messages"]
        new_messages = all_messages[previous_message_count:]
        backend_calls = client.calls[previous_backend_count:]
        previous_message_count = len(all_messages)
        previous_backend_count = len(client.calls)

        response = extract_text(all_messages[-1].content)
        tool_calls = find_tool_calls(new_messages)
        evaluation = evaluate_case(turn, response, tool_calls, backend_calls)
        turns.append(
            {
                "turn": index,
                "question": turn["question"],
                "response": response,
                "elapsed_ms": round(elapsed_ms, 2),
                "usage": collect_usage(new_messages),
                "tool_calls": tool_calls,
                "backend_calls": backend_calls,
                "evaluation": evaluation,
                "trace": [message_trace(message) for message in new_messages],
            }
        )

    return {
        "id": case["id"],
        "category": case["category"],
        "fixture": case["fixture"],
        "passed": all(turn["evaluation"]["passed"] for turn in turns),
        "turns": turns,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, int]:
    turns = [turn for result in results for turn in result["turns"]]
    return {
        "total_cases": len(results),
        "passed_cases": sum(1 for result in results if result["passed"]),
        "total_turns": len(turns),
        "passed_turns": sum(1 for turn in turns if turn["evaluation"]["passed"]),
    }


def main() -> None:
    load_dotenv()
    args = parse_args()
    ids = set(args.ids.split(",")) if args.ids else None
    cases = load_cases(ids)
    if not cases:
        raise SystemExit("没有匹配的多轮评测用例")

    settings = Settings.from_env()
    registry = SkillRegistry()
    model = build_model(settings)
    results = []
    for case in cases:
        print(f"开始多轮评测 {case['id']} turns={len(case['turns'])}", flush=True)
        result = run_case(model, case, args.user_id, registry)
        results.append(result)
        for turn in result["turns"]:
            status = "PASS" if turn["evaluation"]["passed"] else "FAIL"
            tools = [call["name"] for call in turn["tool_calls"]]
            print(
                f"  turn={turn['turn']} {status} elapsed_ms={turn['elapsed_ms']} "
                f"tools={tools}",
                flush=True,
            )

    payload = {
        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "model": settings.llm_model,
            "user_id": args.user_id,
            "system_prompt_sha256": hashlib.sha256(
                SYSTEM_PROMPT.encode("utf-8")
            ).hexdigest(),
            "skills": registry.trace_metadata(),
            "case_ids": [case["id"] for case in cases],
        },
        "summary": summarize(results),
        "results": results,
    }
    output = (
        Path(args.output)
        if args.output
        else ROOT
        / "results"
        / f"multiturn_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"结果已保存：{output}")


if __name__ == "__main__":
    main()
