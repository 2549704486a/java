from __future__ import annotations

import unittest

from langchain_core.documents import Document

from app.knowledge_search import (
    KnowledgeSearchError,
    KnowledgeSearchService,
    normalized_euclidean_relevance,
    validate_index_freshness,
)
from app.knowledge_catalog import KnowledgeCatalog
from app.query_normalization import normalize_business_query
from app.tools import build_tools
from app.trace import capture_tool_trace
from evals.fixtures import FixtureBusinessApiClient


class FakeVectorStore:
    def __init__(
        self,
        results=None,
        error: Exception | None = None,
        metadatas: list[dict] | None = None,
        results_by_query: dict[str, list] | None = None,
    ) -> None:
        self.results = results or []
        self.error = error
        self.metadatas = metadatas or []
        self.results_by_query = results_by_query or {}
        self.queries: list[tuple[str, int]] = []

    def similarity_search_with_relevance_scores(self, query: str, k: int):
        self.queries.append((query, k))
        if self.error is not None:
            raise self.error
        return list(self.results_by_query.get(query, self.results))

    def get(self, **kwargs):
        return {
            "ids": [str(index) for index in range(len(self.metadatas))],
            "metadatas": list(self.metadatas),
        }


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
    @classmethod
    def setUpClass(cls):
        cls.snapshot = KnowledgeCatalog().load()

    def _fresh_metadatas(self) -> list[dict]:
        return [
            {
                "catalog_version": self.snapshot.version,
                "knowledge_id": document.metadata.knowledge_id,
                "knowledge_version": document.metadata.version,
            }
            for document in self.snapshot.documents
        ]

    def test_accepts_index_matching_catalog_and_document_versions(self):
        validate_index_freshness(
            FakeVectorStore(metadatas=self._fresh_metadatas()),
            self.snapshot,
        )

    def test_rejects_stale_catalog_version(self):
        metadatas = self._fresh_metadatas()
        metadatas[0]["catalog_version"] = "2026.08.21.1"

        with self.assertRaisesRegex(KnowledgeSearchError, "版本.*不一致"):
            validate_index_freshness(
                FakeVectorStore(metadatas=metadatas),
                self.snapshot,
            )

    def test_rejects_missing_or_mixed_document_versions(self):
        metadatas = self._fresh_metadatas()
        metadatas[0]["knowledge_version"] = "0.9.0"
        metadatas.pop()

        with self.assertRaisesRegex(KnowledgeSearchError, "版本.*不一致"):
            validate_index_freshness(
                FakeVectorStore(metadatas=metadatas),
                self.snapshot,
            )

    def test_rejects_index_without_version_metadata(self):
        with self.assertRaisesRegex(KnowledgeSearchError, "缺少版本元数据"):
            validate_index_freshness(
                FakeVectorStore(metadatas=[{"knowledge_id": "legacy"}]),
                self.snapshot,
            )

    def test_normalized_relevance_is_bounded(self):
        self.assertEqual(1.0, normalized_euclidean_relevance(0.0))
        self.assertEqual(0.0, normalized_euclidean_relevance(10.0))

    def test_normalizes_domain_typos_and_colloquial_phrases(self):
        result = normalize_business_query("  任物作完了，积份会自已到帐吗？  ")

        self.assertEqual("任物作完了，积份会自已到帐吗？", result.original_query)
        self.assertEqual("任务作完了，积分会自己到账吗？", result.normalized_query)
        self.assertEqual(2, len(result.variants))
        self.assertEqual(
            (("任物", "任务"), ("积份", "积分"), ("自已", "自己"), ("到帐", "到账")),
            result.applied_replacements,
        )

    def test_normalizes_colloquial_task_points_question(self):
        result = normalize_business_query("活干完了，咋分还没到帐？")

        self.assertEqual(
            "任务完成了，积分为什么还没到账？",
            result.normalized_query,
        )
        self.assertEqual(2, len(result.variants))

    def test_keeps_single_query_when_no_normalization_is_needed(self):
        store = FakeVectorStore([(rule_document(), 0.90)])
        service = KnowledgeSearchService(store, relevance_threshold=0.50)

        service.search("处理中是否等于兑换成功")

        self.assertEqual([("处理中是否等于兑换成功", 6)], store.queries)

    def test_merges_raw_and_normalized_retrieval_by_highest_chunk_score(self):
        exchange = rule_document("exchange:1.0.0:0001")
        points = Document(
            page_content="任务完成后积分可能处于待领取状态。",
            metadata={
                **rule_document("points:1.0.0:0001").metadata,
                "chunk_id": "points:1.0.0:0001",
                "knowledge_id": "points-and-tasks",
                "title": "积分与任务规则",
            },
        )
        raw_query = "任物作完了，积份会自已到帐吗？"
        normalized_query = "任务作完了，积分会自己到账吗？"
        store = FakeVectorStore(
            results_by_query={
                raw_query: [(exchange, 0.38), (points, 0.37)],
                normalized_query: [(points, 0.82), (exchange, 0.31)],
            }
        )
        service = KnowledgeSearchService(store, relevance_threshold=0.30)

        result = service.search("任物作完了，积份会自已到帐吗？", limit=2)

        self.assertEqual([raw_query, normalized_query], [item[0] for item in store.queries])
        self.assertEqual(
            ["points-and-tasks", "exchange-rules-and-status"],
            [match.knowledge_id for match in result.matches],
        )
        self.assertEqual(0.82, result.matches[0].score)

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
