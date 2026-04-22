from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.stt import build_stt_adapter
from src.config.settings import load_settings
from src.infrastructure.persistence.models import (
    CallProcessingStatus,
    CallSession,
    TranscriptSegment,
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


class TranscriptSegmentResponse(BaseModel):
    speaker: str
    text: str
    start_ms: int
    end_ms: int
    sequence_no: int


class CallDetailResponse(CallSessionResponse):
    transcript_segments: list[TranscriptSegmentResponse]


class AudioUploadAcceptedResponse(BaseModel):
    call_id: int
    bytes_received: int
    content_type: str | None


def _store_uploaded_audio(
    storage_audio_dir: str,
    call_id: int,
    original_filename: str | None,
    audio_bytes: bytes,
) -> str:
    storage_root = Path(storage_audio_dir)
    storage_root.mkdir(parents=True, exist_ok=True)

    suffix = Path(original_filename or "").suffix or ".bin"
    storage_key = f"call-{call_id}{suffix}"
    (storage_root / storage_key).write_bytes(audio_bytes)
    return storage_key


def _build_transcript_segments(
    call_id: int,
    transcript_output: list[Any],
) -> list[TranscriptSegment]:
    ordered_output = sorted(
        transcript_output,
        key=lambda segment: segment.sequence_no,
    )
    return [
        TranscriptSegment(
            call_id=call_id,
            speaker=segment.speaker,
            text=segment.text,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            sequence_no=segment.sequence_no,
        )
        for segment in ordered_output
    ]


def _load_transcript_segments(
    session: Session,
    call_id: int,
) -> list[TranscriptSegment]:
    return list(
        session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.call_id == call_id)
            .order_by(TranscriptSegment.sequence_no)
        )
    )


def _build_call_detail_response(
    call_session: CallSession,
    transcript_segments: list[TranscriptSegment],
) -> CallDetailResponse:
    return CallDetailResponse(
        id=call_session.id,
        external_call_id=call_session.external_call_id,
        processing_status=call_session.processing_status.value,
        audio_storage_key=call_session.audio_storage_key,
        source_type=call_session.source_type,
        metadata=call_session.metadata_json,
        transcript_segments=[
            TranscriptSegmentResponse(
                speaker=segment.speaker,
                text=segment.text,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                sequence_no=segment.sequence_no,
            )
            for segment in transcript_segments
        ],
    )


def _create_engine(database_url: str):
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(database_url, connect_args=connect_args)


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        yield
    finally:
        engine = getattr(application.state, "engine", None)
        if engine is not None:
            engine.dispose()


def create_app() -> FastAPI:
    settings = load_settings()
    application = FastAPI(
        title="AI Call QA & Sales Coach API",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.engine = _create_engine(settings.database_url)
    application.state.stt_adapter = build_stt_adapter()
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

    @application.get("/calls/{call_id}")
    def get_call(
        call_id: int,
        request: Request,
    ) -> CallDetailResponse:
        with request.app.state.session_factory() as session:
            call_session = session.get(CallSession, call_id)
            if call_session is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="CallSession not found.",
                )

            transcript_segments = _load_transcript_segments(
                session=session,
                call_id=call_id,
            )
            return _build_call_detail_response(
                call_session=call_session,
                transcript_segments=transcript_segments,
            )

    @application.post("/calls/{call_id}/audio")
    async def upload_call_audio(
        call_id: int,
        request: Request,
        file: UploadFile = File(...),
    ) -> AudioUploadAcceptedResponse:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded audio file is empty.",
            )

        with request.app.state.session_factory() as session:
            call_session = session.get(CallSession, call_id)
            if call_session is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="CallSession not found.",
                )

            audio_storage_key = _store_uploaded_audio(
                storage_audio_dir=request.app.state.settings.storage_audio_dir,
                call_id=call_id,
                original_filename=file.filename,
                audio_bytes=audio_bytes,
            )
            stored_audio_path = (
                Path(request.app.state.settings.storage_audio_dir)
                / audio_storage_key
            )
            transcript_output = request.app.state.stt_adapter.transcribe(stored_audio_path)
            transcript_segments = _build_transcript_segments(
                call_id=call_id,
                transcript_output=transcript_output,
            )

            call_session.audio_storage_key = audio_storage_key
            session.add_all(transcript_segments)
            call_session.processing_status = CallProcessingStatus.TRANSCRIBED
            try:
                session.commit()
            except Exception:
                session.rollback()
                raise

        return AudioUploadAcceptedResponse(
            call_id=call_id,
            bytes_received=len(audio_bytes),
            content_type=file.content_type,
        )

    return application
