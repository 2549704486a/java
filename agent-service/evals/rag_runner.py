from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent

from app.agent import ensure_knowledge_citations
from app.config import Settings
from app.confirmation_store import ConfirmationStore
from app.execution_context import bind_execution_context
from app.knowledge_search import KnowledgeSearchResult, open_knowledge_search
from app.prompt import build_system_prompt
from app.skills.registry import SkillRegistry
from app.tools import build_tools
from app.trace import capture_tool_trace
from evals.fixtures import FixtureBusinessApiClient
from evals.runner import build_model, collect_usage, extract_text


ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "rag_cases.json"


class RecordingKnowledgeSearch:
    """保留本轮检索结果，供 Agent 引用评分使用。"""

    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls: list[dict[str, Any]] = []

    def search(self, query: str, limit: int | None = None) -> KnowledgeSearchResult:
        result = self.delegate.search(query, limit)
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "result": result.as_dict(),
            }
        )
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG 检索、路由与引用评测")
    parser.add_argument(
        "--mode",
        choices=("retrieval", "agent", "all"),
        default="all",
    )
    parser.add_argument(
        "--split",
        choices=("calibration", "evaluation", "all"),
        default="all",
        help="只影响无模型的检索评测",
    )
    parser.add_argument("--ids", help="只运行指定编号，多个编号使用逗号分隔")
    parser.add_argument("--user-id", type=int, default=10)
    parser.add_argument("--output", help="指定结果 JSON 路径")
    return parser.parse_args()


def load_case_file(path: Path = CASES_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("不支持的 RAG 评测数据版本")
    return payload


def select_cases(
    cases: list[dict[str, Any]],
    ids: set[str] | None,
    split: str | None = None,
) -> list[dict[str, Any]]:
    selected = cases
    if split and split != "all":
        selected = [case for case in selected if case.get("split") == split]
    if ids:
        selected = [case for case in selected if case["id"] in ids]
    return selected


def raw_candidates(service, query: str, limit: int = 3) -> list[dict[str, Any]]:
    rows = service.vector_store.similarity_search_with_relevance_scores(
        query,
        k=limit,
    )
    return [
        {
            "knowledge_id": str(document.metadata.get("knowledge_id", "")),
            "chunk_id": str(document.metadata.get("chunk_id", "")),
            "score": round(float(score), 4),
        }
        for document, score in rows
        if math.isfinite(score)
    ]


def evaluate_retrieval_case(service, case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    result = service.search(case["query"])
    if result.matches:
        candidates = [
            {
                "knowledge_id": match.knowledge_id,
                "chunk_id": "",
                "score": round(match.score, 4),
            }
            for match in result.matches
        ]
    else:
        # 拒答结果不暴露候选，因此额外取一次原始分数用于分析阈值边界。
        candidates = raw_candidates(service, case["query"])
    elapsed_ms = (time.perf_counter() - started) * 1000
    actual_ids = [match.knowledge_id for match in result.matches]
    expected_id = case.get("expected_knowledge_id")
    code_match = result.code == case["expected_code"]
    top1_hit = expected_id is None or bool(actual_ids and actual_ids[0] == expected_id)
    hit_at_3 = expected_id is None or expected_id in actual_ids
    citation_valid = all(
        match.citation == f"[{match.title} / {match.section}]"
        and bool(match.source_path)
        for match in result.matches
    )
    checks = {
        "result_code": code_match,
        "top1_hit": top1_hit,
        "hit_at_3": hit_at_3,
        "citation_valid": citation_valid,
    }
    # Top1 用于诊断排序质量；只要正确证据进入供 Agent 使用的 Top3，就视为检索成功。
    acceptance_checks = {
        "result_code": code_match,
        "hit_at_3": hit_at_3,
        "citation_valid": citation_valid,
    }
    return {
        "id": case["id"],
        "split": case["split"],
        "category": case["category"],
        "query": case["query"],
        "expected_code": case["expected_code"],
        "expected_knowledge_id": expected_id,
        "actual_code": result.code,
        "actual_knowledge_ids": actual_ids,
        "top_score": candidates[0]["score"] if candidates else None,
        "raw_candidates": candidates,
        "elapsed_ms": round(elapsed_ms, 2),
        "checks": checks,
        "acceptance_checks": acceptance_checks,
        "passed": all(acceptance_checks.values()),
    }


def evaluate_agent_case(
    case: dict[str, Any],
    response: str,
    tool_trace: list[dict[str, Any]],
    search_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    actual_tools = [event["tool_name"] for event in tool_trace]
    required_tools = case.get("required_tools", [])
    forbidden_tools = case.get("forbidden_tools", [])
    tool_selection = all(tool in actual_tools for tool in required_tools) and not any(
        tool in actual_tools for tool in forbidden_tools
    )
    tool_execution = all(event.get("completed", False) for event in tool_trace)

    returned_matches = [
        match
        for call in search_calls
        for match in call["result"]["data"]["matches"]
    ]
    returned_ids = [match["knowledgeId"] for match in returned_matches]
    returned_citations = [match["citation"] for match in returned_matches]
    expected_id = case.get("expected_knowledge_id")
    knowledge_hit = expected_id is None or expected_id in returned_ids
    citation_required = bool(case.get("required_citation", False))
    expected_citations = [
        match["citation"]
        for match in returned_matches
        if expected_id is None or match["knowledgeId"] == expected_id
    ]
    citation_present = any(citation in response for citation in expected_citations)
    citation_correct = citation_present if citation_required else not any(
        citation in response for citation in returned_citations
    )

    lowered = response.lower()
    missing_groups = [
        group
        for group in case.get("required_groups", [])
        if not any(str(item).lower() in lowered for item in group)
    ]
    checks = {
        "tool_selection": tool_selection,
        "tool_execution": tool_execution,
        "knowledge_hit": knowledge_hit,
        "citation": citation_correct,
        "required_content": not missing_groups,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "details": {
            "actual_tools": actual_tools,
            "returned_knowledge_ids": returned_ids,
            "returned_citations": returned_citations,
            "expected_citations": expected_citations,
            "missing_content_groups": missing_groups,
        },
    }


def run_agent_case(
    model,
    service,
    case: dict[str, Any],
    user_id: int,
) -> dict[str, Any]:
    client = FixtureBusinessApiClient(case["fixture"])
    recording_search = RecordingKnowledgeSearch(service)
    agent = create_agent(
        model=model,
        tools=build_tools(
            client,
            user_id,
            SkillRegistry(),
            ConfirmationStore(),
            recording_search,
        ),
        system_prompt=build_system_prompt(True),
    )
    started = time.perf_counter()
    thread_id = f"rag-eval:{case['id']}:user:{user_id}"
    with capture_tool_trace(
        f"rag-eval:{case['id']}"
    ) as trace_session, bind_execution_context(thread_id):
        result = agent.invoke(
            {"messages": [{"role": "user", "content": case["question"]}]},
            config={"recursion_limit": 12},
        )
    elapsed_ms = (time.perf_counter() - started) * 1000
    messages = result["messages"]
    raw_response = extract_text(messages[-1].content)
    response = ensure_knowledge_citations(messages, raw_response)
    trace = trace_session.as_dicts()
    evaluation = evaluate_agent_case(
        case,
        response,
        trace,
        recording_search.calls,
    )
    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "response": response,
        "citation_fallback_applied": response != raw_response,
        "elapsed_ms": round(elapsed_ms, 2),
        "usage": collect_usage(messages),
        "tool_execution_trace": trace,
        "knowledge_search_calls": recording_search.calls,
        "evaluation": evaluation,
    }


def rate(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 0.0


def summarize_retrieval(results: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [item for item in results if item["expected_code"] == "KNOWLEDGE_FOUND"]
    negatives = [item for item in results if item["expected_code"] == "NO_RELEVANT_KNOWLEDGE"]
    top1 = sum(item["checks"]["top1_hit"] for item in positives)
    hit3 = sum(item["checks"]["hit_at_3"] for item in positives)
    rejected = sum(item["checks"]["result_code"] for item in negatives)
    citations = sum(item["checks"]["citation_valid"] for item in positives)
    positive_scores = [item["top_score"] for item in positives if item["top_score"] is not None]
    negative_scores = [item["top_score"] for item in negatives if item["top_score"] is not None]
    return {
        "total": len(results),
        "passed": sum(item["passed"] for item in results),
        "top1_accuracy": rate(top1, len(positives)),
        "hit_at_3": rate(hit3, len(positives)),
        "negative_rejection_rate": rate(rejected, len(negatives)),
        "citation_valid_rate": rate(citations, len(positives)),
        "positive_top_score": score_summary(positive_scores),
        "negative_top_score": score_summary(negative_scores),
    }


def summarize_agent(results: list[dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, list[bool]] = defaultdict(list)
    for item in results:
        for name, passed in item["evaluation"]["checks"].items():
            checks[name].append(bool(passed))
    return {
        "total": len(results),
        "passed": sum(item["evaluation"]["passed"] for item in results),
        "check_rates": {
            name: rate(sum(values), len(values)) for name, values in checks.items()
        },
    }


def score_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "min": round(min(values), 4) if values else None,
        "average": round(statistics.mean(values), 4) if values else None,
        "max": round(max(values), 4) if values else None,
    }


def main() -> None:
    load_dotenv()
    args = parse_args()
    ids = {value.strip() for value in args.ids.split(",")} if args.ids else None
    case_file = load_case_file()
    retrieval_cases = select_cases(case_file["retrieval_cases"], ids, args.split)
    agent_cases = select_cases(case_file["agent_cases"], ids)
    if args.mode == "retrieval":
        agent_cases = []
    elif args.mode == "agent":
        retrieval_cases = []
    if not retrieval_cases and not agent_cases:
        raise SystemExit("没有匹配的 RAG 评测用例")

    settings = Settings.from_env()
    service = open_knowledge_search(settings)
    model = build_model(settings) if agent_cases else None
    retrieval_results: list[dict[str, Any]] = []
    agent_results: list[dict[str, Any]] = []
    try:
        for index, case in enumerate(retrieval_cases, 1):
            print(f"[检索 {index}/{len(retrieval_cases)}] {case['id']}", flush=True)
            result = evaluate_retrieval_case(service, case)
            retrieval_results.append(result)
            print(
                f"  {'PASS' if result['passed'] else 'FAIL'} "
                f"code={result['actual_code']} top_score={result['top_score']}",
                flush=True,
            )
        for index, case in enumerate(agent_cases, 1):
            print(f"[Agent {index}/{len(agent_cases)}] {case['id']}", flush=True)
            result = run_agent_case(model, service, case, args.user_id)
            agent_results.append(result)
            print(
                f"  {'PASS' if result['evaluation']['passed'] else 'FAIL'} "
                f"tools={result['evaluation']['details']['actual_tools']}",
                flush=True,
            )
    finally:
        service.close()

    payload = {
        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "embedding_model": settings.rag_embedding_model,
            "chat_model": settings.llm_model if agent_cases else None,
            "relevance_threshold": settings.rag_relevance_threshold,
            "split": args.split,
            "case_ids": [case["id"] for case in retrieval_cases + agent_cases],
        },
        "summary": {
            "retrieval": summarize_retrieval(retrieval_results),
            "agent": summarize_agent(agent_results),
        },
        "retrieval_results": retrieval_results,
        "agent_results": agent_results,
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = (
        Path(args.output)
        if args.output
        else ROOT / "results" / f"rag_eval_{timestamp}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"结果已保存：{output}")


if __name__ == "__main__":
    main()
