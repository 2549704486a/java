from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.api_client import BusinessApiClient
from app.config import Settings
from app.prompt import SYSTEM_PROMPT
from app.skills.registry import SkillRegistry
from app.tools import build_tools
from app.trace import capture_tool_trace
from evals.fixtures import FixtureBusinessApiClient


ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "cases.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="积分规划 Agent 自动化评测")
    parser.add_argument(
        "--suite",
        choices=("fixture", "live", "all"),
        default="fixture",
        help="选择固定场景、真实 Java 服务或全部用例",
    )
    parser.add_argument("--ids", help="只运行指定编号，多个编号使用逗号分隔")
    parser.add_argument("--user-id", type=int, default=10)
    parser.add_argument("--output", help="指定结果 JSON 路径")
    return parser.parse_args()


def load_cases(suite: str, ids: set[str] | None) -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if suite != "all":
        cases = [case for case in cases if case["source"] == suite]
    if ids:
        cases = [case for case in cases if case["id"] in ids]
    return cases


def build_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.require_llm_api_key(),
        base_url=settings.llm_base_url,
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return str(content)


def message_trace(message: Any) -> dict[str, Any]:
    return {
        "type": message.__class__.__name__,
        "name": getattr(message, "name", None),
        "content": extract_text(getattr(message, "content", "")),
        "tool_calls": getattr(message, "tool_calls", None) or [],
        "usage_metadata": getattr(message, "usage_metadata", None),
    }


def find_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            calls.append(
                {
                    "name": call.get("name"),
                    "args": call.get("args") or {},
                    "id": call.get("id"),
                }
            )
    return calls


def collect_usage(messages: list[Any]) -> dict[str, int]:
    usage: Counter[str] = Counter()
    for message in messages:
        metadata = getattr(message, "usage_metadata", None) or {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = metadata.get(key)
            if isinstance(value, int):
                usage[key] += value
    return dict(usage)


def args_contain(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and args_contain(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


def evaluate_case(
    case: dict[str, Any],
    response: str,
    tool_calls: list[dict[str, Any]],
    backend_calls: list[dict[str, Any]],
    execution_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    actual_tools = [call["name"] for call in tool_calls]
    actual_backend = [call["method"] for call in backend_calls]
    required_tools = case.get("required_tools", [])
    allowed_tools = case.get("allowed_tools")
    tool_pass = all(name in actual_tools for name in required_tools)
    if allowed_tools is not None:
        tool_pass = tool_pass and all(name in allowed_tools for name in actual_tools)

    argument_failures: list[str] = []
    for tool_name, expected in case.get("expected_args", {}).items():
        matching = [call for call in tool_calls if call["name"] == tool_name]
        if not matching or not any(args_contain(call["args"], expected) for call in matching):
            argument_failures.append(tool_name)

    missing_backend = [
        name
        for name in case.get("required_backend_calls", [])
        if name not in actual_backend
    ]
    forbidden_backend = [
        name
        for name in case.get("forbidden_backend_calls", [])
        if name in actual_backend
    ]

    lowered = response.lower()
    missing_groups = [
        group
        for group in case.get("required_groups", [])
        if not any(str(item).lower() in lowered for item in group)
    ]
    missing_facts = [
        fact
        for fact in case.get("required_facts", [])
        if str(fact).lower() not in lowered
    ]
    safety_violations = [
        phrase
        for phrase in case.get("forbidden_phrases", [])
        if phrase.lower() in lowered
    ]
    execution_failures = [
        event["tool_name"]
        for event in execution_trace or []
        if not event.get("completed", False)
    ]

    checks = {
        "tool_selection": tool_pass,
        "arguments": not argument_failures,
        "tool_execution": not execution_failures,
        "backend_path": not missing_backend and not forbidden_backend,
        "required_content": not missing_groups and not missing_facts,
        "safety": not safety_violations,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "details": {
            "actual_tools": actual_tools,
            "argument_failures": argument_failures,
            "tool_execution_failures": execution_failures,
            "actual_backend_calls": actual_backend,
            "missing_backend_calls": missing_backend,
            "forbidden_backend_calls": forbidden_backend,
            "missing_content_groups": missing_groups,
            "missing_facts": missing_facts,
            "safety_violations": safety_violations,
        },
    }


def run_one(
    model: ChatOpenAI,
    settings: Settings,
    case: dict[str, Any],
    user_id: int,
    skill_registry: SkillRegistry,
) -> dict[str, Any]:
    fixture_client: FixtureBusinessApiClient | None = None
    live_client: BusinessApiClient | None = None
    if case["source"] == "fixture":
        fixture_client = FixtureBusinessApiClient(case["fixture"])
        client: Any = fixture_client
    else:
        live_client = BusinessApiClient(
            base_url=settings.business_api_base_url,
            timeout_seconds=settings.business_api_timeout_seconds,
            max_retries=settings.business_api_max_retries,
        )
        client = live_client

    try:
        agent = create_agent(
            model=model,
            tools=build_tools(client, user_id, skill_registry),
            system_prompt=SYSTEM_PROMPT,
        )
        started = time.perf_counter()
        with capture_tool_trace(f"eval:{case['id']}") as trace_session:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": case["question"]}]},
                config={"recursion_limit": 12},
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        messages = result["messages"]
        response = extract_text(messages[-1].content)
        declared_tool_calls = find_tool_calls(messages)
        execution_trace = trace_session.as_dicts()
        tool_calls = [
            {
                "name": event["tool_name"],
                "args": event["arguments"],
                "id": None,
            }
            for event in execution_trace
        ]
        backend_calls = fixture_client.calls if fixture_client else []
        evaluation = evaluate_case(
            case,
            response,
            tool_calls,
            backend_calls,
            execution_trace,
        )
        return {
            "id": case["id"],
            "category": case["category"],
            "source": case["source"],
            "fixture": case.get("fixture"),
            "question": case["question"],
            "response": response,
            "elapsed_ms": round(elapsed_ms, 2),
            "usage": collect_usage(messages),
            "tool_calls": tool_calls,
            "declared_tool_calls": declared_tool_calls,
            "tool_execution_trace": execution_trace,
            "backend_calls": backend_calls,
            "evaluation": evaluation,
            "trace": [message_trace(message) for message in messages],
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "category": case["category"],
            "source": case["source"],
            "fixture": case.get("fixture"),
            "question": case["question"],
            "error": f"{exc.__class__.__name__}: {exc}",
            "evaluation": {"passed": False, "checks": {}, "details": {}},
        }
    finally:
        if live_client is not None:
            live_client.close()


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    category_results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        category_results[result["category"]].append(result)

    checks: Counter[str] = Counter()
    check_totals: Counter[str] = Counter()
    for result in results:
        for name, passed in result["evaluation"].get("checks", {}).items():
            check_totals[name] += 1
            checks[name] += int(passed)

    tool_metrics: dict[str, dict[str, float | int]] = {}
    tool_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        for event in result.get("tool_execution_trace", []):
            tool_events[event["tool_name"]].append(event)
    for tool_name, events in sorted(tool_events.items()):
        elapsed_values = [float(event["elapsed_ms"]) for event in events]
        tool_metrics[tool_name] = {
            "calls": len(events),
            "execution_failures": sum(
                not event.get("completed", False) for event in events
            ),
            "average_elapsed_ms": round(sum(elapsed_values) / len(events), 2),
            "max_elapsed_ms": round(max(elapsed_values), 2),
        }

    return {
        "total": len(results),
        "passed": sum(result["evaluation"]["passed"] for result in results),
        "failed": sum(not result["evaluation"]["passed"] for result in results),
        "by_category": {
            category: {
                "total": len(items),
                "passed": sum(item["evaluation"]["passed"] for item in items),
            }
            for category, items in category_results.items()
        },
        "check_rates": {
            name: {
                "passed": checks[name],
                "total": total,
                "rate": round(checks[name] / total, 4) if total else 0,
            }
            for name, total in check_totals.items()
        },
        "tool_metrics": tool_metrics,
        "average_elapsed_ms": round(
            sum(result.get("elapsed_ms", 0) for result in results) / len(results),
            2,
        )
        if results
        else 0,
    }


def main() -> None:
    load_dotenv()
    args = parse_args()
    ids = {item.strip() for item in args.ids.split(",")} if args.ids else None
    cases = load_cases(args.suite, ids)
    if not cases:
        raise SystemExit("没有匹配的评测用例")

    settings = Settings.from_env()
    skill_registry = SkillRegistry()
    model = build_model(settings)
    print(
        f"开始评测 model={settings.llm_model} suite={args.suite} cases={len(cases)}",
        flush=True,
    )
    results = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']} {case['question']}", flush=True)
        result = run_one(model, settings, case, args.user_id, skill_registry)
        results.append(result)
        status = "PASS" if result["evaluation"]["passed"] else "FAIL"
        print(
            f"  {status} elapsed_ms={result.get('elapsed_ms', 0)} "
            f"tools={[call['name'] for call in result.get('tool_calls', [])]}",
            flush=True,
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(args.output)
        if args.output
        else ROOT / "results" / f"baseline_{args.suite}_{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "model": settings.llm_model,
            "suite": args.suite,
            "user_id": args.user_id,
            "temperature": 0,
            "system_prompt_sha256": hashlib.sha256(
                SYSTEM_PROMPT.encode("utf-8")
            ).hexdigest(),
            "skills": skill_registry.trace_metadata(),
            "case_ids": [case["id"] for case in cases],
        },
        "summary": summarize(results),
        "results": results,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"结果已保存：{output_path}")


if __name__ == "__main__":
    main()
