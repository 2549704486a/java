"""加载并校验进入 RAG 索引前的受控业务知识源。"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


# 业务知识是部署资源，不放在 Python 包内；从 app/knowledge 回到 agent-service 根目录。
DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
REQUIRED_SECTIONS = ("适用问题", "规则说明", "实时信息边界", "来源")


class KnowledgeCatalogError(ValueError):
    """知识目录、文档元数据或文件完整性不符合项目约定。"""


class CatalogDocumentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    path: str = Field(min_length=1)


class CatalogManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    catalog_version: str = Field(pattern=r"^\d{4}\.\d{2}\.\d{2}\.\d+$")
    documents: list[CatalogDocumentEntry] = Field(min_length=1)


class KnowledgeMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    status: Literal["active", "draft", "retired"]
    audience: list[str] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    fact_scope: Literal["stable_rules_only"]
    business_type: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    authority_level: Literal[
        "official_policy",
        "system_contract",
        "operations_manual",
        "historical_case",
    ]
    effective_from: date
    effective_until: date | None = None
    policy_key: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    )
    supersedes: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_effective_window(self) -> "KnowledgeMetadata":
        if self.effective_until is not None and self.effective_until < self.effective_from:
            raise ValueError("知识失效日期不能早于生效日期")
        if self.knowledge_id in self.supersedes:
            raise ValueError("知识文档不能声明替代自身")
        if self.supersedes and self.policy_key is None:
            raise ValueError("声明 supersedes 时必须同时声明 policy_key")
        if len(self.supersedes) != len(set(self.supersedes)):
            raise ValueError("supersedes 不能包含重复知识 ID")
        return self


@dataclass(frozen=True)
class KnowledgeDocument:
    metadata: KnowledgeMetadata
    body: str
    source_path: Path


@dataclass(frozen=True)
class KnowledgeCatalogSnapshot:
    version: str
    documents: tuple[KnowledgeDocument, ...]


class KnowledgeCatalog:
    """只向后续切分和索引阶段暴露已经通过治理校验的文档。"""

    def __init__(
        self,
        knowledge_dir: Path | str = DEFAULT_KNOWLEDGE_DIR,
        project_root: Path | str | None = None,
    ) -> None:
        self.knowledge_dir = Path(knowledge_dir).resolve()
        self.project_root = Path(project_root).resolve() if project_root else self.knowledge_dir.parents[1]

    def load(self) -> KnowledgeCatalogSnapshot:
        manifest = self._load_manifest()
        ids = [entry.id for entry in manifest.documents]
        if len(ids) != len(set(ids)):
            raise KnowledgeCatalogError("manifest.json 中存在重复知识 ID")

        validated_documents = tuple(self._load_document(entry) for entry in manifest.documents)
        self._validate_supersedes(validated_documents)
        # retired/draft 文档仍要通过完整性校验，但不能进入后续切分和索引输入。
        documents = tuple(
            document
            for document in validated_documents
            if document.metadata.status == "active"
        )
        return KnowledgeCatalogSnapshot(
            version=manifest.catalog_version,
            documents=documents,
        )

    @staticmethod
    def _validate_supersedes(documents: tuple[KnowledgeDocument, ...]) -> None:
        documents_by_id = {
            document.metadata.knowledge_id: document
            for document in documents
        }
        for document in documents:
            metadata = document.metadata
            for target_id in metadata.supersedes:
                target = documents_by_id.get(target_id)
                if target is None:
                    raise KnowledgeCatalogError(
                        f"supersedes 指向不存在的知识：{metadata.knowledge_id} -> {target_id}"
                    )
                if target.metadata.policy_key != metadata.policy_key:
                    raise KnowledgeCatalogError(
                        "替代关系两端必须使用相同 policy_key："
                        f"{metadata.knowledge_id} -> {target_id}"
                    )

    def _load_manifest(self) -> CatalogManifest:
        manifest_path = self.knowledge_dir / "manifest.json"
        try:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            return CatalogManifest.model_validate(raw_manifest)
        except FileNotFoundError as exc:
            raise KnowledgeCatalogError(f"知识目录清单不存在：{manifest_path}") from exc
        except json.JSONDecodeError as exc:
            raise KnowledgeCatalogError(f"manifest.json 不是有效 JSON：{manifest_path}") from exc
        except ValidationError as exc:
            raise KnowledgeCatalogError(f"manifest.json 契约校验失败：{exc}") from exc

    def _load_document(self, entry: CatalogDocumentEntry) -> KnowledgeDocument:
        source_path = self._safe_child_path(entry.path)
        try:
            text = source_path.read_text(encoding="utf-8-sig")
        except FileNotFoundError as exc:
            raise KnowledgeCatalogError(f"知识文档不存在：{source_path}") from exc

        metadata, body = self._parse_front_matter(source_path, text)
        if metadata.knowledge_id != entry.id:
            raise KnowledgeCatalogError(
                f"知识 ID 与清单不一致：{entry.id} != {metadata.knowledge_id}"
            )
        self._validate_sections(source_path, body)
        self._validate_source_refs(source_path, metadata.source_refs)
        return KnowledgeDocument(
            metadata=metadata,
            body=body,
            source_path=source_path,
        )

    def _safe_child_path(self, relative_path: str) -> Path:
        candidate = (self.knowledge_dir / relative_path).resolve()
        try:
            candidate.relative_to(self.knowledge_dir)
        except ValueError as exc:
            raise KnowledgeCatalogError(f"知识文档路径越界：{relative_path}") from exc
        if candidate == self.knowledge_dir:
            raise KnowledgeCatalogError(f"知识文档路径不能指向目录：{relative_path}")
        return candidate

    @staticmethod
    def _parse_front_matter(source_path: Path, content: str) -> tuple[KnowledgeMetadata, str]:
        parts = content.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise KnowledgeCatalogError(f"知识文档缺少 YAML Front Matter：{source_path}")
        try:
            raw_metadata = yaml.safe_load(parts[1])
            metadata = KnowledgeMetadata.model_validate(raw_metadata)
        except (yaml.YAMLError, ValidationError) as exc:
            raise KnowledgeCatalogError(f"知识文档元数据校验失败：{source_path}：{exc}") from exc

        body = parts[2].strip()
        if not body:
            raise KnowledgeCatalogError(f"知识文档正文为空：{source_path}")
        return metadata, body

    @staticmethod
    def _validate_sections(source_path: Path, body: str) -> None:
        missing = [section for section in REQUIRED_SECTIONS if f"## {section}" not in body]
        if missing:
            raise KnowledgeCatalogError(f"知识文档缺少章节 {missing}：{source_path}")

    def _validate_source_refs(self, source_path: Path, source_refs: list[str]) -> None:
        for source_ref in source_refs:
            ref_path = Path(source_ref)
            if ref_path.is_absolute():
                raise KnowledgeCatalogError(f"来源必须使用项目相对路径：{source_path}：{source_ref}")
            candidate = (self.project_root / ref_path).resolve()
            try:
                candidate.relative_to(self.project_root)
            except ValueError as exc:
                raise KnowledgeCatalogError(f"来源路径越界：{source_path}：{source_ref}") from exc
            if not candidate.is_file():
                raise KnowledgeCatalogError(f"来源文件不存在：{source_path}：{source_ref}")


def main() -> None:
    parser = argparse.ArgumentParser(description="校验受控 RAG 业务知识源")
    parser.add_argument("--knowledge-dir", type=Path, default=DEFAULT_KNOWLEDGE_DIR)
    args = parser.parse_args()

    snapshot = KnowledgeCatalog(args.knowledge_dir).load()
    print(f"knowledge_catalog_valid version={snapshot.version} documents={len(snapshot.documents)}")
    for document in snapshot.documents:
        print(
            "knowledge_document_valid "
            f"id={document.metadata.knowledge_id} "
            f"version={document.metadata.version}"
        )


if __name__ == "__main__":
    main()
