"""将受控业务知识切分并构建可重复生成的本地向量索引。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from chromadb.api import ClientAPI
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.config import Settings
from app.knowledge_catalog import KnowledgeCatalog, KnowledgeCatalogSnapshot


AGENT_SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEPARATORS = ("\n\n", "\n", "。", "；", "，", " ", "")


class KnowledgeIndexError(ValueError):
    """切分参数或索引配置无法安全执行。"""


@dataclass(frozen=True)
class KnowledgeIndexReport:
    catalog_version: str
    document_count: int
    chunk_count: int
    collection_name: str
    index_dir: Path


class KnowledgeChunker:
    """先保留 Markdown 标题语义，再对过长段落做递归切分。"""

    def __init__(self, chunk_size: int = 400, chunk_overlap: int = 60) -> None:
        if chunk_size <= 0:
            raise KnowledgeIndexError("chunk_size 必须大于 0")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise KnowledgeIndexError("chunk_overlap 必须大于等于 0 且小于 chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "heading_1"),
                ("##", "heading_2"),
                ("###", "heading_3"),
            ],
            strip_headers=False,
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=list(DEFAULT_SEPARATORS),
            length_function=len,
        )

    def split(self, snapshot: KnowledgeCatalogSnapshot) -> tuple[Document, ...]:
        chunks: list[Document] = []
        for knowledge_document in snapshot.documents:
            metadata = knowledge_document.metadata
            base_metadata = {
                "knowledge_id": metadata.knowledge_id,
                "knowledge_version": metadata.version,
                "catalog_version": snapshot.version,
                "title": metadata.title,
                "source_path": (
                    f"{knowledge_document.source_path.parent.name}/"
                    f"{knowledge_document.source_path.name}"
                ),
                "source_refs": " | ".join(metadata.source_refs),
                "topics": ",".join(metadata.topics),
                "audience": ",".join(metadata.audience),
                "fact_scope": metadata.fact_scope,
            }

            # 标题切分保留“这一段属于哪个章节”，递归切分只处理仍然过长的段落。
            sections = self.header_splitter.split_text(knowledge_document.body)
            document_chunks: list[Document] = []
            for section in sections:
                section.metadata = {**base_metadata, **section.metadata}
                document_chunks.extend(self.text_splitter.split_documents([section]))

            for chunk_index, chunk in enumerate(document_chunks):
                chunk.metadata["chunk_index"] = chunk_index
                chunk.metadata["chunk_id"] = (
                    f"{metadata.knowledge_id}:{metadata.version}:{chunk_index:04d}"
                )
                chunks.append(chunk)

        if not chunks:
            raise KnowledgeIndexError("受控知识目录没有可切分的 active 文档")
        return tuple(chunks)


class KnowledgeIndexBuilder:
    """构建本地 Chroma 集合；同名集合每次先清空再完整重建。"""

    def __init__(self, chunker: KnowledgeChunker) -> None:
        self.chunker = chunker

    def build(
        self,
        snapshot: KnowledgeCatalogSnapshot,
        embeddings: Embeddings,
        index_dir: Path | str,
        collection_name: str,
        client: ClientAPI | None = None,
    ) -> tuple[KnowledgeIndexReport, Chroma]:
        normalized_collection = collection_name.strip()
        if not normalized_collection:
            raise KnowledgeIndexError("collection_name 不能为空")

        resolved_index_dir = Path(index_dir).resolve()
        resolved_index_dir.mkdir(parents=True, exist_ok=True)
        chunks = self.chunker.split(snapshot)
        ids = [str(chunk.metadata["chunk_id"]) for chunk in chunks]

        # 删除的是当前命名集合，不删除目录中的其他集合或用户文件。
        store_options = {
            "collection_name": normalized_collection,
            "embedding_function": embeddings,
        }
        document_store_options = {
            "collection_name": normalized_collection,
            "embedding": embeddings,
        }
        if client is None:
            store_options["persist_directory"] = str(resolved_index_dir)
            document_store_options["persist_directory"] = str(resolved_index_dir)
        else:
            store_options["client"] = client
            document_store_options["client"] = client

        existing = Chroma(
            **store_options,
        )
        existing.delete_collection()
        vector_store = Chroma.from_documents(
            documents=list(chunks),
            ids=ids,
            **document_store_options,
        )
        report = KnowledgeIndexReport(
            catalog_version=snapshot.version,
            document_count=len(snapshot.documents),
            chunk_count=len(chunks),
            collection_name=normalized_collection,
            index_dir=resolved_index_dir,
        )
        return report, vector_store


def close_vector_store(vector_store: Chroma | None) -> None:
    """释放 Chroma 持久化连接，主要用于测试和进程优雅停机。"""
    if vector_store is None:
        return
    # LangChain 的包装类暂未暴露 close，底层 Chroma Client 提供正式关闭方法。
    vector_store._client.close()


def resolve_index_dir(raw_path: str) -> Path:
    index_path = Path(raw_path)
    if not index_path.is_absolute():
        index_path = AGENT_SERVICE_ROOT / index_path
    return index_path.resolve()


def build_openai_embeddings(settings: Settings) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.rag_embedding_model,
        api_key=settings.require_rag_embedding_api_key(),
        base_url=settings.rag_embedding_base_url,
        check_embedding_ctx_length=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="构建本地 RAG 向量索引")
    parser.add_argument(
        "command",
        choices=("inspect-chunks", "build"),
        help="inspect-chunks 只检查切分；build 会调用 Embedding 服务并重建索引",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    snapshot = KnowledgeCatalog().load()
    chunker = KnowledgeChunker(
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )
    chunks = chunker.split(snapshot)
    if args.command == "inspect-chunks":
        print(
            f"knowledge_chunks_valid catalog={snapshot.version} "
            f"documents={len(snapshot.documents)} chunks={len(chunks)}"
        )
        for chunk in chunks:
            print(
                "knowledge_chunk_valid "
                f"id={chunk.metadata['chunk_id']} "
                f"heading={chunk.metadata.get('heading_2', chunk.metadata.get('heading_1', '-'))} "
                f"characters={len(chunk.page_content)}"
            )
        return

    builder = KnowledgeIndexBuilder(chunker)
    report, _ = builder.build(
        snapshot=snapshot,
        embeddings=build_openai_embeddings(settings),
        index_dir=resolve_index_dir(settings.rag_index_dir),
        collection_name=settings.rag_collection_name,
    )
    print(
        f"knowledge_index_built catalog={report.catalog_version} "
        f"documents={report.document_count} chunks={report.chunk_count} "
        f"collection={report.collection_name} index_dir={report.index_dir}"
    )


if __name__ == "__main__":
    main()
