from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.base import Base
from src.infrastructure.persistence.call_session import _SessionRecord


class _DeliveryRecord(Base):
    __tablename__ = "delivery_events"

    call_id: Mapped[int] = mapped_column(
        ForeignKey("call_sessions.id"),
        primary_key=True,
    )
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(100), nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempted_at: Mapped[datetime] = mapped_column(nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    call: Mapped[_SessionRecord] = relationship()
