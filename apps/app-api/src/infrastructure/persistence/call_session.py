from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum as SqlEnum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.base import Base


class CallProcessingStatus(str, Enum):
    CREATED = "created"
    UPLOADED = "uploaded"
    TRANSCRIBED = "transcribed"
    ANALYZED = "analyzed"
    EXPORTED = "exported"
    FAILED = "failed"


class _SessionRecord(Base):
    __tablename__ = "call_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    processing_status: Mapped[CallProcessingStatus] = mapped_column(
        SqlEnum(
            CallProcessingStatus,
            native_enum=False,
            validate_strings=True,
        ),
        nullable=False,
        default=CallProcessingStatus.CREATED,
    )
    audio_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
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
