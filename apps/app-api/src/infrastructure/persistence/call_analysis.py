from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.base import Base
from src.infrastructure.persistence.call_session import _SessionRecord


class _AnalysisRecord(Base):
    __tablename__ = "call_analyses"

    call_id: Mapped[int] = mapped_column(
        ForeignKey("call_sessions.id"),
        primary_key=True,
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    review_reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    call: Mapped[_SessionRecord] = relationship()
