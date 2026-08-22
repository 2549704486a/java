"""只读业务知识检索，负责相关性过滤和来源引用组装。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import Settings
from app.knowledge_catalog import KnowledgeCatalog, KnowledgeCatalogSnapshot
from app.knowledge_index import (
    build_openai_embeddings,
    close_vector_store,
    resolve_index_dir,
)
from app.query_normalization import normalize_business_query


def normalized_euclidean_relevance(distance: float) -> float:
    """Keep LangChain's Euclidean conversion while bounding noisy outliers."""
    score = 1.0 - distance / math.sqrt(2.0)
    return max(0.0, min(1.0, score))


class KnowledgeSearchError(RuntimeError):
    """知识索引不可用或检索失败。"""


class KnowledgeVectorStore(Protocol):
    def similarity_search_with_relevance_scores(
        self,
        query: str,
        k: int,
    ) -> list[tuple[Document, float]]: ...

    def get(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class KnowledgeMatch:
    content: str
    score: float
    citation: str
    knowledge_id: str
    knowledge_version: str
    title: str
    section: str
    source_path: str
    source_refs: tuple[str, ...]
    business_type: str
    authority_level: str
    effective_from: str
    effective_until: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "score": round(self.score, 4),
            "citation": self.citation,
            "knowledgeId": self.knowledge_id,
            "knowledgeVersion": self.knowledge_version,
            "title": self.title,
            "section": self.section,
            "sourcePath": self.source_path,
            "sourceRefs": list(self.source_refs),
            "businessType": self.business_type,
            "authorityLevel": self.authority_level,
            "effectiveFrom": self.effective_from,
            "effectiveUntil": self.effective_until,
        }


@dataclass(frozen=True)
class KnowledgeSearchResult:
    code: str
    message: str
    matches: tuple[KnowledgeMatch, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": True,
            "code": self.code,
            "data": {
                "matches": [match.as_dict() for match in self.matches],
            },
            "message": self.message,
            "retryable": False,
        }


class KnowledgeSearchService:
    """从已构建索引中读取稳定规则，不承担实时业务事实查询。"""

    def __init__(
        self,
        vector_store: KnowledgeVectorStore,
        relevance_threshold: float = 0.35,
        default_limit: int = 3,
        allowed_audiences: tuple[str, ...] = ("end_user",),
        owns_vector_store: bool = False,
    ) -> None:
        if not 0 <= relevance_threshold <= 1:
            raise ValueError("relevance_threshold 必须位于 0 到 1 之间")
        if default_limit <= 0:
            raise ValueError("default_limit 必须大于 0")
        self.vector_store = vector_store
        self.relevance_threshold = relevance_threshold
        self.default_limit = default_limit
        self.allowed_audiences = frozenset(allowed_audiences)
        if not self.allowed_audiences:
            raise ValueError("allowed_audiences 不能为空")
        self._owns_vector_store = owns_vector_store

    def search(self, query: str, limit: int | None = None) -> KnowledgeSearchResult:
        query_normalization = normalize_business_query(query)
        actual_limit = self.default_limit if limit is None else limit
        if actual_limit <= 0:
            raise ValueError("limit 必须大于 0")

        try:
            candidate_limit = max(actual_limit * 2, actual_limit)
            candidate_groups = [
                self.vector_store.similarity_search_with_relevance_scores(
                    query_variant,
                    k=candidate_limit,
                )
                for query_variant in query_normalization.variants
            ]
        except Exception as exc:
            raise KnowledgeSearchError("业务知识检索暂时不可用") from exc

        # 原 Query 和标准化 Query 可能召回同一个 Chunk，只保留更高相关度。
        merged_candidates: dict[str, tuple[Document, float]] = {}
        for candidates in candidate_groups:
            for document, score in candidates:
                candidate_key = self._candidate_key(document)
                current = merged_candidates.get(candidate_key)
                if current is None or score > current[1]:
                    merged_candidates[candidate_key] = (document, score)

        matches: list[KnowledgeMatch] = []
        seen_chunk_ids: set[str] = set()
        for document, score in sorted(
            merged_candidates.values(),
            key=lambda item: item[1],
            reverse=True,
        ):
            if not math.isfinite(score) or score < self.relevance_threshold:
                continue
            if not self._is_audience_allowed(document):
                continue
            chunk_id = str(document.metadata.get("chunk_id", "")).strip()
            if chunk_id and chunk_id in seen_chunk_ids:
                continue
            if chunk_id:
                seen_chunk_ids.add(chunk_id)
            matches.append(self._to_match(document, score))
            if len(matches) >= actual_limit:
                break

        if not matches:
            return KnowledgeSearchResult(
                code="NO_RELEVANT_KNOWLEDGE",
                message="受控知识库中没有找到足够相关的可靠内容",
                matches=(),
            )
        return KnowledgeSearchResult(
            code="KNOWLEDGE_FOUND",
            message="已找到可引用的业务规则",
            matches=tuple(matches),
        )

    @staticmethod
    def _candidate_key(document: Document) -> str:
        chunk_id = str(document.metadata.get("chunk_id", "")).strip()
        if chunk_id:
            return chunk_id
        # 兼容旧测试数据或异常索引：没有 chunk_id 时仍避免双路召回重复返回同一内容。
        knowledge_id = str(document.metadata.get("knowledge_id", "")).strip()
        return f"{knowledge_id}\u0000{document.page_content}"

    def close(self) -> None:
        if self._owns_vector_store and isinstance(self.vector_store, Chroma):
            close_vector_store(self.vector_store)

    def _is_audience_allowed(self, document: Document) -> bool:
        raw_audience = str(document.metadata.get("audience", ""))
        audiences = {item.strip() for item in raw_audience.split(",") if item.strip()}
        return bool(audiences & self.allowed_audiences)

    @staticmethod
    def _to_match(document: Document, score: float) -> KnowledgeMatch:
        metadata = document.metadata
        title = str(metadata.get("title", "业务规则")).strip() or "业务规则"
        section = next(
            (
                str(metadata[key]).strip()
                for key in ("heading_3", "heading_2", "heading_1")
                if metadata.get(key)
            ),
            "正文",
        )
        raw_refs = str(metadata.get("source_refs", ""))
        source_refs = tuple(ref.strip() for ref in raw_refs.split("|") if ref.strip())
        effective_until = str(metadata.get("effective_until", "")).strip() or None
        return KnowledgeMatch(
            content=document.page_content.strip(),
            score=float(score),
            citation=f"[{title} / {section}]",
            knowledge_id=str(metadata.get("knowledge_id", "")),
            knowledge_version=str(metadata.get("knowledge_version", "")),
            title=title,
            section=section,
            source_path=str(metadata.get("source_path", "")),
            source_refs=source_refs,
            business_type=str(metadata.get("business_type", "")),
            authority_level=str(metadata.get("authority_level", "")),
            effective_from=str(metadata.get("effective_from", "")),
            effective_until=effective_until,
        )


def validate_index_freshness(
    vector_store: KnowledgeVectorStore,
    snapshot: KnowledgeCatalogSnapshot,
) -> None:
    """要求正式索引与当前受控目录及单篇文档版本完全一致。"""
    try:
        payload = vector_store.get(include=["metadatas"])
    except Exception as exc:
        raise KnowledgeSearchError("无法读取 RAG 索引版本信息") from exc

    ids = payload.get("ids") or []
    metadatas = payload.get("metadatas") or []
    if not ids or not metadatas:
        raise KnowledgeSearchError(
            "RAG 索引集合为空，请先执行 python -m app.knowledge_index build"
        )
    if len(ids) != len(metadatas):
        raise KnowledgeSearchError(
            "RAG 索引版本元数据不完整，请重新执行 python -m app.knowledge_index build"
        )

    actual_catalog_versions: set[str] = set()
    actual_document_versions: dict[str, set[str]] = {}
    for metadata in metadatas:
        if not isinstance(metadata, dict):
            raise KnowledgeSearchError(
                "RAG 索引缺少版本元数据，请重新执行 python -m app.knowledge_index build"
            )
        catalog_version = str(metadata.get("catalog_version", "")).strip()
        knowledge_id = str(metadata.get("knowledge_id", "")).strip()
        knowledge_version = str(metadata.get("knowledge_version", "")).strip()
        if not catalog_version or not knowledge_id or not knowledge_version:
            raise KnowledgeSearchError(
                "RAG 索引缺少版本元数据，请重新执行 python -m app.knowledge_index build"
            )
        actual_catalog_versions.add(catalog_version)
        actual_document_versions.setdefault(knowledge_id, set()).add(
            knowledge_version
        )

    expected_document_versions = {
        document.metadata.knowledge_id: document.metadata.version
        for document in snapshot.documents
    }
    index_is_fresh = (
        actual_catalog_versions == {snapshot.version}
        and set(actual_document_versions) == set(expected_document_versions)
        and all(
            actual_document_versions[knowledge_id] == {knowledge_version}
            for knowledge_id, knowledge_version in expected_document_versions.items()
        )
    )
    if not index_is_fresh:
        raise KnowledgeSearchError(
            "RAG 索引版本与受控知识目录不一致，请重新执行 "
            "python -m app.knowledge_index build"
        )


def open_knowledge_search(
    settings: Settings,
    *,
    allowed_audiences: tuple[str, ...] = ("end_user",),
) -> KnowledgeSearchService:
    """打开已有持久化集合；未建库时拒绝以空知识库启动。"""
    index_dir = resolve_index_dir(settings.rag_index_dir)
    if not index_dir.is_dir():
        raise KnowledgeSearchError(
            "RAG 索引目录不存在，请先执行 python -m app.knowledge_index build"
        )

    vector_store = Chroma(
        collection_name=settings.rag_collection_name,
        embedding_function=build_openai_embeddings(settings),
        persist_directory=str(index_dir),
        relevance_score_fn=normalized_euclidean_relevance,
    )
    try:
        validate_index_freshness(vector_store, KnowledgeCatalog().load())
    except Exception:
        close_vector_store(vector_store)
        raise
    return KnowledgeSearchService(
        vector_store=vector_store,
        relevance_threshold=settings.rag_relevance_threshold,
        default_limit=settings.rag_top_k,
        allowed_audiences=allowed_audiences,
        owns_vector_store=True,
    )
