from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chromadb
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from app.config import Settings
from app.knowledge_catalog import KnowledgeCatalog
from app.knowledge_index import (
    KnowledgeChunker,
    KnowledgeIndexBuilder,
    KnowledgeIndexError,
    build_openai_embeddings,
    close_vector_store,
)


class KeywordEmbeddings(Embeddings):
    """只用于离线测试，让检索结果可以稳定复现。"""

    keywords = ("积分", "任务", "兑换", "确认", "库存", "处理中", "成功", "Agent")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [float(text.count(keyword)) for keyword in self.keywords]
        return vector if any(vector) else [0.01] * len(self.keywords)


class FailingEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding provider unavailable")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("embedding provider unavailable")


class KnowledgeIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = KnowledgeCatalog().load()

    def test_chunks_preserve_source_version_and_heading_metadata(self):
        chunks = KnowledgeChunker(chunk_size=220, chunk_overlap=40).split(self.snapshot)

        self.assertGreater(len(chunks), len(self.snapshot.documents))
        self.assertEqual(len(chunks), len({chunk.metadata["chunk_id"] for chunk in chunks}))
        for chunk in chunks:
            self.assertLessEqual(len(chunk.page_content), 220)
            self.assertIn("knowledge_id", chunk.metadata)
            self.assertIn("knowledge_version", chunk.metadata)
            self.assertIn("catalog_version", chunk.metadata)
            self.assertIn("source_refs", chunk.metadata)
            self.assertIn("business_type", chunk.metadata)
            self.assertIn("authority_level", chunk.metadata)
            self.assertIn("effective_from", chunk.metadata)
            self.assertIn("effective_until", chunk.metadata)
            self.assertIn("policy_key", chunk.metadata)
            self.assertIn("supersedes", chunk.metadata)
            self.assertTrue(str(chunk.metadata["source_path"]).startswith("documents/"))
            self.assertTrue(
                "heading_1" in chunk.metadata or "heading_2" in chunk.metadata
            )

    def test_rejects_invalid_overlap(self):
        with self.assertRaisesRegex(KnowledgeIndexError, "chunk_overlap"):
            KnowledgeChunker(chunk_size=100, chunk_overlap=100)

    @patch("app.knowledge_index.OpenAIEmbeddings")
    def test_embedding_client_uses_configured_batch_size(self, embeddings_class):
        settings = Settings(
            rag_embedding_api_key="test-key",
            rag_embedding_model="test-embedding-model",
            rag_embedding_batch_size=7,
        )

        build_openai_embeddings(settings)

        embeddings_class.assert_called_once_with(
            model="test-embedding-model",
            api_key="test-key",
            base_url=None,
            chunk_size=7,
            check_embedding_ctx_length=False,
        )

    def test_build_is_repeatable_and_index_can_retrieve_exchange_rule(self):
        chunker = KnowledgeChunker(chunk_size=260, chunk_overlap=40)
        builder = KnowledgeIndexBuilder(chunker)
        embeddings = KeywordEmbeddings()

        with tempfile.TemporaryDirectory() as temp_dir:
            client = chromadb.EphemeralClient()
            first_store = None
            second_store = None
            try:
                first_report, first_store = builder.build(
                    snapshot=self.snapshot,
                    embeddings=embeddings,
                    index_dir=Path(temp_dir),
                    collection_name="test-business-rules",
                    client=client,
                )
                first_count = len(first_store.get()["ids"])

                second_report, second_store = builder.build(
                    snapshot=self.snapshot,
                    embeddings=embeddings,
                    index_dir=Path(temp_dir),
                    collection_name="test-business-rules",
                    client=client,
                )
                second_count = len(second_store.get()["ids"])
                results = second_store.similarity_search("兑换处理中是否代表成功", k=2)
            finally:
                # Chroma 在 Windows 下共享 SQLite 连接；测试结束前显式释放，避免锁住临时目录。
                close_vector_store(first_store)
                close_vector_store(second_store)

        self.assertEqual(first_report.chunk_count, first_count)
        self.assertEqual(first_count, second_count)
        self.assertEqual(first_report.chunk_count, second_report.chunk_count)
        self.assertTrue(results)
        self.assertEqual("exchange-rules-and-status", results[0].metadata["knowledge_id"])

    def test_failed_rebuild_keeps_previous_collection_available(self):
        client = chromadb.EphemeralClient()
        builder = KnowledgeIndexBuilder(
            KnowledgeChunker(chunk_size=260, chunk_overlap=40)
        )
        original_store = None
        reopened_store = None
        try:
            report, original_store = builder.build(
                snapshot=self.snapshot,
                embeddings=KeywordEmbeddings(),
                index_dir=Path("unused-in-memory-index"),
                collection_name="failure-safe-rules",
                client=client,
            )

            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                builder.build(
                    snapshot=self.snapshot,
                    embeddings=FailingEmbeddings(),
                    index_dir=Path("unused-in-memory-index"),
                    collection_name="failure-safe-rules",
                    client=client,
                )

            reopened_store = Chroma(
                collection_name="failure-safe-rules",
                embedding_function=KeywordEmbeddings(),
                client=client,
            )
            self.assertEqual(report.chunk_count, len(reopened_store.get()["ids"]))
        finally:
            close_vector_store(original_store)
            close_vector_store(reopened_store)


if __name__ == "__main__":
    unittest.main()
