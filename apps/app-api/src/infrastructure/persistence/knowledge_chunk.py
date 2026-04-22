from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.base import Base
from src.infrastructure.persistence.knowledge_document import _DocumentRecord


class _ChunkRecord(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id"),
        nullable=False,
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped[_DocumentRecord] = relationship()
