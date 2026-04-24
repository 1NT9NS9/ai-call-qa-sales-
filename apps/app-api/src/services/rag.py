from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.embeddings import EmbeddingService
from src.infrastructure.persistence.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    TranscriptSegment,
)


@dataclass(frozen=True)
class IndexableKnowledgeDocument:
    source_path: str
    content: str


@dataclass(frozen=True)
class RetrievedKnowledgeChunk:
    chunk_id: int
    document_id: int
    source_path: str
    chunk_text: str
    chunk_index: int
    distance: float


class RAGService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedding_service: EmbeddingService,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_service = embedding_service

    def index(self, documents: list[IndexableKnowledgeDocument]) -> None:
        if not documents:
            return

        with self._session_factory() as session:
            if session.bind is None or session.bind.dialect.name != "postgresql":
                raise RuntimeError(
                    "RAG indexing requires PostgreSQL with pgvector."
                )

            indexed_chunks: list[tuple[int, str]] = []
            for document in documents:
                existing_document = session.scalar(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.source_path == document.source_path
                    )
                )
                if existing_document is not None:
                    continue

                persisted_document = KnowledgeDocument(
                    source_path=document.source_path,
                    content=document.content,
                )
                session.add(persisted_document)
                session.flush()

                chunk_texts = self._split_document(document.content)
                for chunk_index, chunk_text in enumerate(chunk_texts):
                    persisted_chunk = KnowledgeChunk(
                        document_id=persisted_document.id,
                        chunk_text=chunk_text,
                        chunk_index=chunk_index,
                    )
                    session.add(persisted_chunk)
                    session.flush()
                    indexed_chunks.append((persisted_chunk.id, persisted_chunk.chunk_text))

            if indexed_chunks:
                embeddings = self._embedding_service.embed(
                    [chunk_text for _, chunk_text in indexed_chunks]
                )
                for (chunk_id, _chunk_text), embedding in zip(
                    indexed_chunks,
                    embeddings,
                    strict=True,
                ):
                    session.execute(
                        text(
                            """
                            INSERT INTO knowledge_chunk_vectors (chunk_id, embedding)
                            VALUES (:chunk_id, CAST(:embedding AS vector))
                            ON CONFLICT (chunk_id) DO UPDATE
                            SET embedding = EXCLUDED.embedding
                            """
                        ),
                        {
                            "chunk_id": chunk_id,
                            "embedding": json.dumps(embedding),
                        },
                    )

            session.commit()

    def search(self, query: str, limit: int = 5) -> list[RetrievedKnowledgeChunk]:
        with self._session_factory() as session:
            return self._search(session=session, query=query, limit=limit)

    def search_for_call(
        self,
        call_id: int,
        limit: int = 5,
    ) -> list[RetrievedKnowledgeChunk]:
        with self._session_factory() as session:
            query = self._build_transcript_query(session=session, call_id=call_id)
            return self._search(session=session, query=query, limit=limit)

    def _build_transcript_query(self, session: Session, call_id: int) -> str:
        transcript_segments = list(
            session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.call_id == call_id)
                .order_by(TranscriptSegment.sequence_no)
            )
        )
        if not transcript_segments:
            raise RuntimeError(
                f"No transcript segments found for call_id={call_id}."
            )

        return " ".join(segment.text for segment in transcript_segments)

    @staticmethod
    def _split_document(content: str) -> list[str]:
        chunks: list[str] = []
        current_lines: list[str] = []

        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            if line.strip():
                current_lines.append(line)
                continue

            if current_lines:
                chunks.append("\n".join(current_lines).strip())
                current_lines = []

        if current_lines:
            chunks.append("\n".join(current_lines).strip())

        return chunks

    def _search(
        self,
        session: Session,
        query: str,
        limit: int,
    ) -> list[RetrievedKnowledgeChunk]:
        if session.bind is None or session.bind.dialect.name != "postgresql":
            raise RuntimeError(
                "Stage 3 vector search requires PostgreSQL with pgvector."
            )

        query_embedding = self._embedding_service.embed([query])[0]
        rows = session.execute(
            text(
                """
                SELECT
                    knowledge_chunks.id AS chunk_id,
                    knowledge_chunks.document_id AS document_id,
                    knowledge_documents.source_path AS source_path,
                    knowledge_chunks.chunk_text AS chunk_text,
                    knowledge_chunks.chunk_index AS chunk_index,
                    knowledge_chunk_vectors.embedding <=> CAST(:embedding AS vector) AS distance
                FROM knowledge_chunk_vectors
                JOIN knowledge_chunks
                    ON knowledge_chunks.id = knowledge_chunk_vectors.chunk_id
                JOIN knowledge_documents
                    ON knowledge_documents.id = knowledge_chunks.document_id
                ORDER BY distance ASC, knowledge_chunks.id ASC
                LIMIT :limit
                """
            ),
            {
                "embedding": json.dumps(query_embedding),
                "limit": limit,
            },
        ).mappings()

        return [RetrievedKnowledgeChunk(**dict(row)) for row in rows]


def build_rag_service(
    session_factory: sessionmaker[Session],
    embedding_service: EmbeddingService,
) -> RAGService:
    return RAGService(
        session_factory=session_factory,
        embedding_service=embedding_service,
    )
