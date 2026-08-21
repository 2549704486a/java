from __future__ import annotations

import unittest

from langchain_core.documents import Document

from app.knowledge_search import KnowledgeSearchError, KnowledgeSearchService
from app.tools import build_tools
from app.trace import capture_tool_trace
from evals.fixtures import FixtureBusinessApiClient


class FakeVectorStore:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = results or []
        self.error = error
        self.queries: list[tuple[str, int]] = []

    def similarity_search_with_relevance_scores(self, query: str, k: int):
        self.queries.append((query, k))
        if self.error is not None:
            raise self.error
        return list(self.results)


def rule_document(chunk_id: str = "exchange:1.0.0:0001") -> Document:
    return Document(
        page_content="兑换请求进入处理中后，不代表最终兑换成功，应到订单页面查看结果。",
        metadata={
            "chunk_id": chunk_id,
            "knowledge_id": "exchange-rules-and-status",
            "knowledge_version": "1.0.0",
            "title": "兑换规则与状态说明",
            "heading_2": "规则说明",
            "source_path": "documents/exchange-rules-and-status.md",
            "source_refs": "incentive/src/main/java/Controller.java | agent-service/app/prompt.py",
        },
    )


class KnowledgeSearchServiceTest(unittest.TestCase):
    def test_returns_only_relevant_unique_matches_with_citations(self):
        document = rule_document()
        store = FakeVectorStore(
            [
                (document, 0.92),
                (document, 0.88),
                (rule_document("other:1.0.0:0001"), 0.20),
            ]
        )
        service = KnowledgeSearchService(store, relevance_threshold=0.50)

        result = service.search("处理中是否等于兑换成功", limit=2)
        payload = result.as_dict()

        self.assertEqual("KNOWLEDGE_FOUND", payload["code"])
        self.assertEqual(1, len(payload["data"]["matches"]))
        match = payload["data"]["matches"][0]
        self.assertEqual("[兑换规则与状态说明 / 规则说明]", match["citation"])
        self.assertEqual("documents/exchange-rules-and-status.md", match["sourcePath"])
        self.assertEqual(2, len(match["sourceRefs"]))
        self.assertEqual([("处理中是否等于兑换成功", 4)], store.queries)

    def test_returns_no_answer_when_all_candidates_are_below_threshold(self):
        service = KnowledgeSearchService(
            FakeVectorStore([(rule_document(), 0.34)]),
            relevance_threshold=0.35,
        )

        result = service.search("客服电话是什么")

        self.assertEqual("NO_RELEVANT_KNOWLEDGE", result.code)
        self.assertEqual((), result.matches)

    def test_rejects_explicit_zero_limit(self):
        service = KnowledgeSearchService(FakeVectorStore())

        with self.assertRaisesRegex(ValueError, "limit"):
            service.search("兑换规则", limit=0)

    def test_wraps_vector_store_failure_without_exposing_internal_error(self):
        service = KnowledgeSearchService(
            FakeVectorStore(error=RuntimeError("sqlite file is locked"))
        )

        with self.assertRaisesRegex(KnowledgeSearchError, "暂时不可用") as captured:
            service.search("兑换规则")

        self.assertNotIn("sqlite", str(captured.exception))

    def test_tool_returns_structured_result_and_records_trace(self):
        service = KnowledgeSearchService(
            FakeVectorStore([(rule_document(), 0.90)]),
            relevance_threshold=0.50,
        )
        tools = build_tools(
            FixtureBusinessApiClient("eligible"),
            10,
            knowledge_search=service,
        )
        search_tool = next(
            tool for tool in tools if tool.name == "search_business_knowledge"
        )

        with capture_tool_trace("knowledge-request") as trace:
            result = search_tool.invoke({"query": "兑换处理中是什么意思", "limit": 2})

        self.assertEqual("KNOWLEDGE_FOUND", result["code"])
        self.assertEqual("search_business_knowledge", trace.as_dicts()[0]["tool_name"])
        self.assertEqual("KNOWLEDGE_FOUND", trace.as_dicts()[0]["result_code"])
        self.assertEqual(
            {"query_chars": len("兑换处理中是什么意思"), "limit": 2},
            trace.as_dicts()[0]["arguments"],
        )

    def test_tool_is_absent_when_rag_is_disabled(self):
        tools = build_tools(FixtureBusinessApiClient("eligible"), 10)

        self.assertNotIn("search_business_knowledge", {tool.name for tool in tools})


if __name__ == "__main__":
    unittest.main()
