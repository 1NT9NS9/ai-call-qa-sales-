from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.embeddings import EmbeddingService
from src.infrastructure.persistence.models import TranscriptSegment


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
