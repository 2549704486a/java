"""只读业务知识检索，负责相关性过滤和来源引用组装。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import Settings
from app.knowledge_index import (
    build_openai_embeddings,
    close_vector_store,
    resolve_index_dir,
)


class KnowledgeSearchError(RuntimeError):
    """知识索引不可用或检索失败。"""


class KnowledgeVectorStore(Protocol):
    def similarity_search_with_relevance_scores(
        self,
        query: str,
        k: int,
    ) -> list[tuple[Document, float]]: ...


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
        owns_vector_store: bool = False,
    ) -> None:
        if not 0 <= relevance_threshold <= 1:
            raise ValueError("relevance_threshold 必须位于 0 到 1 之间")
        if default_limit <= 0:
            raise ValueError("default_limit 必须大于 0")
        self.vector_store = vector_store
        self.relevance_threshold = relevance_threshold
        self.default_limit = default_limit
        self._owns_vector_store = owns_vector_store

    def search(self, query: str, limit: int | None = None) -> KnowledgeSearchResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query 不能为空")
        actual_limit = self.default_limit if limit is None else limit
        if actual_limit <= 0:
            raise ValueError("limit 必须大于 0")

        try:
            # 多取一些候选，过滤低相关结果和重复 Chunk 后仍尽量满足 limit。
            candidates = self.vector_store.similarity_search_with_relevance_scores(
                normalized_query,
                k=max(actual_limit * 2, actual_limit),
            )
        except Exception as exc:
            raise KnowledgeSearchError("业务知识检索暂时不可用") from exc

        matches: list[KnowledgeMatch] = []
        seen_chunk_ids: set[str] = set()
        for document, score in candidates:
            if not math.isfinite(score) or score < self.relevance_threshold:
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

    def close(self) -> None:
        if self._owns_vector_store and isinstance(self.vector_store, Chroma):
            close_vector_store(self.vector_store)

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
        )


def open_knowledge_search(settings: Settings) -> KnowledgeSearchService:
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
    )
    if not vector_store.get(limit=1).get("ids"):
        close_vector_store(vector_store)
        raise KnowledgeSearchError(
            "RAG 索引集合为空，请先执行 python -m app.knowledge_index build"
        )
    return KnowledgeSearchService(
        vector_store=vector_store,
        relevance_threshold=settings.rag_relevance_threshold,
        default_limit=settings.rag_top_k,
        owns_vector_store=True,
    )
