from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
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
from app.confirmation_store import ConfirmationStore
from app.execution_context import bind_execution_context
from app.prompt import SYSTEM_PROMPT
from app.skills.registry import SkillRegistry
from app.tools import build_tools
from app.trace import capture_tool_trace
from evals.fixtures import FixtureBusinessApiClient
from evals.metrics import (
    ModelTimingHandler,
    TokenPricing,
    summarize_model_timing,
    summarize_token_usage,
)


ROOT = Path(__file__).resolve().parent
TUNING_CASES_PATH = ROOT / "cases.json"
BLIND_CASES_PATH = ROOT / "blind_cases.json"
# Keep the old constant for offline result files created before dataset isolation.
CASES_PATH = TUNING_CASES_PATH
DATASET_PATHS = {
    "tuning": TUNING_CASES_PATH,
    "blind": BLIND_CASES_PATH,
}


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须是大于 0 的整数")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("必须是有限的非负数")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="积分规划 Agent 自动化评测")
    parser.add_argument(
        "--suite",
        choices=("fixture", "live", "all"),
        default="fixture",
        help="选择固定场景、真实 Java 服务或全部用例",
    )
    parser.add_argument(
        "--dataset",
        choices=tuple(DATASET_PATHS),
        default="tuning",
        help="tuning 为公开调优/回归集，blind 为冻结盲测集",
    )
    parser.add_argument(
        "--repeat",
        type=positive_int,
        default=1,
        help="每个用例重复运行次数；关键用例建议至少 3 次",
    )
    parser.add_argument("--ids", help="只运行指定编号，多个编号使用逗号分隔")
    parser.add_argument("--user-id", type=int, default=10)
    parser.add_argument("--output", help="指定结果 JSON 路径")
    parser.add_argument(
        "--input-cost-per-million",
        type=non_negative_float,
        help="每百万输入 Token 的美元单价，必须与输出单价同时配置",
    )
    parser.add_argument(
        "--output-cost-per-million",
        type=non_negative_float,
        help="每百万输出 Token 的美元单价，必须与输入单价同时配置",
    )
    return parser.parse_args()


def resolve_pricing(
    input_cost_per_million: float | None,
    output_cost_per_million: float | None,
) -> TokenPricing | None:
    if input_cost_per_million is None and output_cost_per_million is None:
        return None
    if input_cost_per_million is None or output_cost_per_million is None:
        raise SystemExit("输入和输出 Token 单价必须同时配置")
    return TokenPricing(input_cost_per_million, output_cost_per_million)


def load_cases(
    suite: str,
    ids: set[str] | None,
    dataset: str = "tuning",
) -> list[dict[str, Any]]:
    cases_path = DATASET_PATHS[dataset]
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
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
    attempt: int = 1,
) -> dict[str, Any]:
    fixture_client: FixtureBusinessApiClient | None = None
    live_client: BusinessApiClient | None = None
    model_timing = ModelTimingHandler()
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
        confirmation_store = ConfirmationStore()
        agent = create_agent(
            model=model,
            tools=build_tools(
                client,
                user_id,
                skill_registry,
                confirmation_store,
            ),
            system_prompt=SYSTEM_PROMPT,
        )
        started = time.perf_counter()
        thread_id = f"eval:{case['id']}:attempt:{attempt}:user:{user_id}"
        with capture_tool_trace(
            f"eval:{case['id']}:attempt:{attempt}"
        ) as trace_session, bind_execution_context(thread_id):
            result = agent.invoke(
                {"messages": [{"role": "user", "content": case["question"]}]},
                config={
                    "recursion_limit": 12,
                    "callbacks": [model_timing],
                },
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        messages = result["messages"]
        response = extract_text(messages[-1].content)
        # 声明轨迹表示模型“想调用什么”，主要用于排查模型决策过程。
        declared_tool_calls = find_tool_calls(messages)
        # 执行轨迹表示代码“实际执行了什么”，评测以它作为工具调用事实。
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
            "attempt": attempt,
            "category": case["category"],
            "source": case["source"],
            "fixture": case.get("fixture"),
            "question": case["question"],
            "response": response,
            "elapsed_ms": round(elapsed_ms, 2),
            "model_metrics": model_timing.summary(),
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
            "attempt": attempt,
            "category": case["category"],
            "source": case["source"],
            "fixture": case.get("fixture"),
            "question": case["question"],
            "error": f"{exc.__class__.__name__}: {exc}",
            "model_metrics": model_timing.summary(),
            "usage": {},
            "evaluation": {"passed": False, "checks": {}, "details": {}},
        }
    finally:
        if live_client is not None:
            live_client.close()


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value * len(ordered)))
    return ordered[rank - 1]


def summarize_stability(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["id"]].append(result)

    cases: dict[str, dict[str, Any]] = {}
    stable_passed = 0
    flaky = 0
    stable_failed = 0
    single_passed = 0
    single_failed = 0
    for case_id, attempts in grouped.items():
        passed = sum(bool(item["evaluation"]["passed"]) for item in attempts)
        total = len(attempts)
        if total == 1 and passed == 1:
            status = "single_pass"
            single_passed += 1
        elif total == 1:
            status = "single_fail"
            single_failed += 1
        elif passed == total:
            status = "stable_pass"
            stable_passed += 1
        elif passed == 0:
            status = "stable_fail"
            stable_failed += 1
        else:
            status = "flaky"
            flaky += 1
        elapsed_values = [
            float(item["elapsed_ms"])
            for item in attempts
            if isinstance(item.get("elapsed_ms"), (int, float))
        ]
        cases[case_id] = {
            "attempts": total,
            "passed": passed,
            "pass_rate": round(passed / total, 4),
            "status": status,
            "average_elapsed_ms": round(statistics.mean(elapsed_values), 2)
            if elapsed_values
            else 0,
            "p95_elapsed_ms": round(percentile(elapsed_values, 0.95), 2),
            "elapsed_stddev_ms": round(statistics.pstdev(elapsed_values), 2)
            if len(elapsed_values) > 1
            else 0,
        }

    return {
        "repeat_count": max((len(items) for items in grouped.values()), default=0),
        "case_count": len(grouped),
        "attempt_count": len(results),
        "attempt_pass_rate": round(
            sum(bool(result["evaluation"]["passed"]) for result in results)
            / len(results),
            4,
        )
        if results
        else 0,
        "single_passed_cases": single_passed,
        "single_failed_cases": single_failed,
        "stable_passed_cases": stable_passed,
        "flaky_cases": flaky,
        "stable_failed_cases": stable_failed,
        "cases": cases,
    }


def summarize(
    results: list[dict[str, Any]],
    pricing: TokenPricing | None = None,
) -> dict[str, Any]:
    category_results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        category_results[result["category"]].append(result)
    run_elapsed_values = [
        float(result["elapsed_ms"])
        for result in results
        if isinstance(result.get("elapsed_ms"), (int, float))
    ]

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
        tool_elapsed_values = [float(event["elapsed_ms"]) for event in events]
        tool_metrics[tool_name] = {
            "calls": len(events),
            "execution_failures": sum(
                not event.get("completed", False) for event in events
            ),
            "average_elapsed_ms": round(
                sum(tool_elapsed_values) / len(events), 2
            ),
            "max_elapsed_ms": round(max(tool_elapsed_values), 2),
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
        "token_metrics": summarize_token_usage(results, pricing),
        "model_metrics": summarize_model_timing(results),
        "average_elapsed_ms": round(statistics.mean(run_elapsed_values), 2)
        if run_elapsed_values
        else 0,
        "p95_elapsed_ms": round(
            percentile(run_elapsed_values, 0.95),
            2,
        ),
        "stability": summarize_stability(results),
    }


def redact_blind_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep release-gate evidence without leaking blind prompts or answers."""
    evaluation = result.get("evaluation", {})
    return {
        "id": result["id"],
        "attempt": result.get("attempt", 1),
        "category": result["category"],
        "source": result["source"],
        "elapsed_ms": result.get("elapsed_ms"),
        "model_metrics": result.get("model_metrics", {}),
        "usage": result.get("usage", {}),
        "error_type": result.get("error", "").partition(":")[0] or None,
        "evaluation": {
            "passed": bool(evaluation.get("passed", False)),
            "checks": evaluation.get("checks", {}),
        },
    }


def main() -> None:
    load_dotenv()
    args = parse_args()
    pricing = resolve_pricing(
        args.input_cost_per_million,
        args.output_cost_per_million,
    )
    ids = {item.strip() for item in args.ids.split(",")} if args.ids else None
    cases = load_cases(args.suite, ids, args.dataset)
    if not cases:
        raise SystemExit("没有匹配的评测用例")

    settings = Settings.from_env()
    skill_registry = SkillRegistry()
    model = build_model(settings)
    print(
        f"开始评测 model={settings.llm_model} dataset={args.dataset} "
        f"suite={args.suite} cases={len(cases)} repeat={args.repeat}",
        flush=True,
    )
    results = []
    total_runs = len(cases) * args.repeat
    completed = 0
    for attempt in range(1, args.repeat + 1):
        print(f"第 {attempt}/{args.repeat} 轮", flush=True)
        for case in cases:
            completed += 1
            label = case["id"]
            if args.dataset == "tuning":
                label = f"{label} {case['question']}"
            print(f"[{completed}/{total_runs}] {label}", flush=True)
            result = run_one(
                model,
                settings,
                case,
                args.user_id,
                skill_registry,
                attempt,
            )
            results.append(result)
            status = "PASS" if result["evaluation"]["passed"] else "FAIL"
            detail = ""
            if args.dataset == "tuning":
                detail = (
                    " tools="
                    f"{[call['name'] for call in result.get('tool_calls', [])]}"
                )
            usage = result.get("usage", {})
            model_metrics = result.get("model_metrics", {})
            print(
                f"  {status} elapsed_ms={result.get('elapsed_ms', 0)} "
                f"model_ms={model_metrics.get('total_elapsed_ms', 0)} "
                f"tokens={usage.get('total_tokens', 0)}{detail}",
                flush=True,
            )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(args.output)
        if args.output
        else ROOT
        / "results"
        / f"baseline_{args.dataset}_{args.suite}_{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "model": settings.llm_model,
            "dataset": args.dataset,
            "suite": args.suite,
            "repeat": args.repeat,
            "user_id": args.user_id,
            "temperature": 0,
            "system_prompt_sha256": hashlib.sha256(
                SYSTEM_PROMPT.encode("utf-8")
            ).hexdigest(),
            "skills": skill_registry.trace_metadata(),
            "case_ids": [case["id"] for case in cases],
            "case_set_sha256": hashlib.sha256(
                DATASET_PATHS[args.dataset].read_bytes()
            ).hexdigest(),
            "blind_details_redacted": args.dataset == "blind",
        },
        "summary": summarize(results, pricing),
        "results": (
            [redact_blind_result(result) for result in results]
            if args.dataset == "blind"
            else results
        ),
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"结果已保存：{output_path}")


if __name__ == "__main__":
    main()
