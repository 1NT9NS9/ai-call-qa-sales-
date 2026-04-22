from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import load_settings
from src.infrastructure.persistence.models import (
    CallProcessingStatus,
    CallSession,
)


class CreateCallSessionRequest(BaseModel):
    external_call_id: str | None = None
    audio_storage_key: str | None = None
    source_type: str | None = None
    metadata: dict[str, Any] | None = None


class CallSessionResponse(BaseModel):
    id: int
    external_call_id: str | None
    processing_status: str
    audio_storage_key: str | None
    source_type: str | None
    metadata: dict[str, Any] | None


def _create_engine(database_url: str):
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(database_url, connect_args=connect_args)


def create_app() -> FastAPI:
    settings = load_settings()
    application = FastAPI(title="AI Call QA & Sales Coach API")
    application.state.settings = settings
    application.state.engine = _create_engine(settings.database_url)
    application.state.session_factory = sessionmaker(
        bind=application.state.engine,
        expire_on_commit=False,
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/calls", status_code=status.HTTP_201_CREATED)
    def create_call_session(
        payload: CreateCallSessionRequest,
        request: Request,
    ) -> CallSessionResponse:
        with request.app.state.session_factory() as session:
            call_session = CallSession(
                external_call_id=payload.external_call_id,
                processing_status=CallProcessingStatus.CREATED,
                audio_storage_key=payload.audio_storage_key,
                source_type=payload.source_type,
                metadata_json=payload.metadata,
            )
            session.add(call_session)
            session.commit()
            session.refresh(call_session)

        return CallSessionResponse(
            id=call_session.id,
            external_call_id=call_session.external_call_id,
            processing_status=call_session.processing_status.value,
            audio_storage_key=call_session.audio_storage_key,
            source_type=call_session.source_type,
            metadata=call_session.metadata_json,
        )

    return application


app = create_app()
