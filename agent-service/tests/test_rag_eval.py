from __future__ import annotations

import unittest
from types import SimpleNamespace

from evals.rag_runner import (
    evaluate_agent_case,
    evaluate_retrieval_case,
    load_case_file,
    select_cases,
    summarize_agent,
    summarize_retrieval,
)


class RagEvalTest(unittest.TestCase):
    def test_case_file_has_unique_ids_and_both_retrieval_splits(self):
        payload = load_case_file()
        retrieval = payload["retrieval_cases"]
        agent = payload["agent_cases"]
        ids = [case["id"] for case in retrieval + agent]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            {"calibration", "evaluation"},
            {case["split"] for case in retrieval},
        )
        self.assertTrue(select_cases(retrieval, None, "evaluation"))

    def test_agent_evaluation_requires_returned_citation_in_answer(self):
        case = {
            "required_tools": ["search_business_knowledge"],
            "forbidden_tools": [],
            "expected_knowledge_id": "exchange-rules-and-status",
            "required_citation": True,
            "required_groups": [["不代表"]],
        }
        trace = [
            {
                "tool_name": "search_business_knowledge",
                "completed": True,
            }
        ]
        search_calls = [
            {
                "result": {
                    "data": {
                        "matches": [
                            {
                                "knowledgeId": "exchange-rules-and-status",
                                "citation": "[奖品兑换规则与状态 / 规则说明]",
                            }
                        ]
                    }
                }
            }
        ]

        passed = evaluate_agent_case(
            case,
            "处理中不代表成功。[奖品兑换规则与状态 / 规则说明]",
            trace,
            search_calls,
        )
        failed = evaluate_agent_case(
            case,
            "处理中不代表成功。",
            trace,
            search_calls,
        )

        self.assertTrue(passed["passed"])
        self.assertFalse(failed["checks"]["citation"])

    def test_retrieval_accepts_expected_document_in_top3_but_reports_top1_miss(self):
        wrong = SimpleNamespace(
            knowledge_id="exchange-rules-and-status",
            score=0.7,
            citation="[奖品兑换规则与状态 / 规则说明]",
            title="奖品兑换规则与状态",
            section="规则说明",
            source_path="documents/exchange-rules-and-status.md",
        )
        expected = SimpleNamespace(
            knowledge_id="points-and-tasks",
            score=0.6,
            citation="[积分与任务规则 / 规则说明]",
            title="积分与任务规则",
            section="规则说明",
            source_path="documents/points-and-tasks.md",
        )
        result = SimpleNamespace(
            code="KNOWLEDGE_FOUND",
            matches=(wrong, expected),
        )
        service = SimpleNamespace(search=lambda query: result)
        case = {
            "id": "RR00",
            "split": "evaluation",
            "category": "积分规则",
            "query": "任务奖励是什么意思",
            "expected_code": "KNOWLEDGE_FOUND",
            "expected_knowledge_id": "points-and-tasks",
        }

        evaluation = evaluate_retrieval_case(service, case)

        self.assertTrue(evaluation["passed"])
        self.assertFalse(evaluation["checks"]["top1_hit"])
        self.assertTrue(evaluation["checks"]["hit_at_3"])

    def test_summaries_separate_retrieval_and_agent_metrics(self):
        retrieval = [
            {
                "expected_code": "KNOWLEDGE_FOUND",
                "top_score": 0.7,
                "passed": True,
                "checks": {
                    "top1_hit": True,
                    "hit_at_3": True,
                    "citation_valid": True,
                    "result_code": True,
                },
            },
            {
                "expected_code": "NO_RELEVANT_KNOWLEDGE",
                "top_score": 0.1,
                "passed": True,
                "checks": {
                    "top1_hit": True,
                    "hit_at_3": True,
                    "citation_valid": True,
                    "result_code": True,
                },
            },
        ]
        agent = [
            {
                "evaluation": {
                    "passed": True,
                    "checks": {"tool_selection": True, "citation": True},
                }
            }
        ]

        retrieval_summary = summarize_retrieval(retrieval)
        agent_summary = summarize_agent(agent)

        self.assertEqual(1.0, retrieval_summary["top1_accuracy"])
        self.assertEqual(1.0, retrieval_summary["negative_rejection_rate"])
        self.assertEqual(1.0, agent_summary["check_rates"]["citation"])


if __name__ == "__main__":
    unittest.main()
