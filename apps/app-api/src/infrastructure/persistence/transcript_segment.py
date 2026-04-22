from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.base import Base
from src.infrastructure.persistence.call_session import _SessionRecord


class _SegmentRecord(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(
        ForeignKey("call_sessions.id"),
        nullable=False,
    )
    speaker: Mapped[str] = mapped_column(String(100), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)

    call: Mapped[_SessionRecord] = relationship()
