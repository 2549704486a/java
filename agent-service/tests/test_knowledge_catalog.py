from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.knowledge_catalog import KnowledgeCatalog, KnowledgeCatalogError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class KnowledgeCatalogTest(unittest.TestCase):
    def test_current_catalog_is_valid_and_versioned(self):
        snapshot = KnowledgeCatalog().load()

        self.assertEqual("2026.08.21.1", snapshot.version)
        self.assertEqual(
            {"agent-service-guide", "exchange-rules-and-status", "points-and-tasks"},
            {document.metadata.knowledge_id for document in snapshot.documents},
        )
        self.assertTrue(
            all(document.metadata.fact_scope == "stable_rules_only" for document in snapshot.documents)
        )

    def test_rejects_document_path_outside_knowledge_directory(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            knowledge_dir = Path(temp_dir) / "knowledge"
            knowledge_dir.mkdir()
            self._write_manifest(
                knowledge_dir,
                [{"id": "outside", "path": "../outside.md"}],
            )

            with self.assertRaisesRegex(KnowledgeCatalogError, "路径越界"):
                KnowledgeCatalog(knowledge_dir, PROJECT_ROOT).load()

    def test_rejects_duplicate_knowledge_ids(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            knowledge_dir = Path(temp_dir) / "knowledge"
            knowledge_dir.mkdir()
            duplicate = {"id": "duplicate", "path": "documents/a.md"}
            self._write_manifest(knowledge_dir, [duplicate, duplicate])

            with self.assertRaisesRegex(KnowledgeCatalogError, "重复知识 ID"):
                KnowledgeCatalog(knowledge_dir, PROJECT_ROOT).load()

    def test_rejects_missing_source_reference(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            knowledge_dir = Path(temp_dir) / "knowledge"
            document_path = knowledge_dir / "documents" / "sample.md"
            document_path.parent.mkdir(parents=True)
            content = """---
knowledge_id: sample
title: 测试知识
version: 1.0.0
status: active
audience: [end_user]
topics: [test]
fact_scope: stable_rules_only
source_refs: [missing-source.md]
---

# 测试知识

## 适用问题
测试。

## 规则说明
测试。

## 实时信息边界
测试。

## 来源
测试。
"""
            document_path.write_text(content, encoding="utf-8")
            self._write_manifest(
                knowledge_dir,
                [{"id": "sample", "path": "documents/sample.md"}],
            )

            with self.assertRaisesRegex(KnowledgeCatalogError, "来源文件不存在"):
                KnowledgeCatalog(knowledge_dir, PROJECT_ROOT).load()

    def test_rejects_missing_required_section(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            knowledge_dir = Path(temp_dir) / "knowledge"
            document_path = knowledge_dir / "documents" / "sample.md"
            document_path.parent.mkdir(parents=True)
            content = """---
knowledge_id: sample
title: 测试知识
version: 1.0.0
status: active
audience: [end_user]
topics: [test]
fact_scope: stable_rules_only
source_refs: [agent-service/app/prompt.py]
---

# 测试知识

## 适用问题

测试。
"""
            document_path.write_text(content, encoding="utf-8")
            self._write_manifest(
                knowledge_dir,
                [{"id": "sample", "path": "documents/sample.md"}],
            )

            with self.assertRaisesRegex(KnowledgeCatalogError, "缺少章节"):
                KnowledgeCatalog(knowledge_dir, PROJECT_ROOT).load()

    @staticmethod
    def _write_manifest(knowledge_dir: Path, documents: list[dict]) -> None:
        manifest = {
            "schema_version": 1,
            "catalog_version": "2026.08.21.1",
            "documents": documents,
        }
        (knowledge_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
