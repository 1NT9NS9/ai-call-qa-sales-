from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.embeddings import EmbeddingService, build_embedding_service
from src.adapters.stt import build_stt_adapter
from src.config.settings import load_settings
from src.infrastructure.persistence.models import (
    CallProcessingStatus,
    CallSession,
    KnowledgeChunk,
    KnowledgeDocument,
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


class KnowledgeImportResponse(BaseModel):
    imported_count: int
    chunk_count: int


class KnowledgeEmbedResponse(BaseModel):
    embedded_count: int


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


def _knowledge_seed_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "kb_seed"


def _import_seed_knowledge_documents(session: Session) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    kb_seed_dir = _knowledge_seed_dir()
    if not kb_seed_dir.is_dir():
        raise RuntimeError(f"Knowledge seed directory not found: {kb_seed_dir}")

    seed_documents = sorted(
        path
        for path in kb_seed_dir.iterdir()
        if path.is_file() and path.name != ".gitkeep"
    )
    imported_count = 0

    for path in seed_documents:
        source_path = path.relative_to(repo_root).as_posix()
        existing_document = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.source_path == source_path
            )
        )
        if existing_document is not None:
            continue

        session.add(
            KnowledgeDocument(
                source_path=source_path,
                content=path.read_text(encoding="utf-8"),
            )
        )
        imported_count += 1

    session.commit()
    return imported_count


def _split_knowledge_document(content: str) -> list[str]:
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


def _chunk_imported_knowledge_documents(session: Session) -> int:
    documents = list(
        session.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.id))
    )
    chunk_count = 0

    for document in documents:
        existing_chunk = session.scalar(
            select(KnowledgeChunk.id).where(
                KnowledgeChunk.document_id == document.id
            )
        )
        if existing_chunk is not None:
            continue

        chunk_texts = _split_knowledge_document(document.content)
        for chunk_index, chunk_text in enumerate(chunk_texts):
            session.add(
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_text=chunk_text,
                    chunk_index=chunk_index,
                )
            )
            chunk_count += 1

    session.commit()
    return chunk_count


def _embed_knowledge_chunks(
    session: Session,
    embedding_service: EmbeddingService,
) -> int:
    chunks = list(
        session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.embedding.is_(None))
            .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_index)
        )
    )

    embeddings = embedding_service.embed([chunk.chunk_text for chunk in chunks])
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        chunk.embedding = embedding

    session.commit()
    return len(chunks)


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
    application.state.embedding_service = build_embedding_service()
    application.state.stt_adapter = build_stt_adapter()
    application.state.session_factory = sessionmaker(
        bind=application.state.engine,
        expire_on_commit=False,
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/knowledge/import", status_code=status.HTTP_201_CREATED)
    def import_knowledge(request: Request) -> KnowledgeImportResponse:
        with request.app.state.session_factory() as session:
            try:
                imported_count = _import_seed_knowledge_documents(session)
                chunk_count = _chunk_imported_knowledge_documents(session)
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(exc),
                ) from exc

        return KnowledgeImportResponse(
            imported_count=imported_count,
            chunk_count=chunk_count,
        )

    @application.post("/knowledge/embed", status_code=status.HTTP_200_OK)
    def embed_knowledge(request: Request) -> KnowledgeEmbedResponse:
        with request.app.state.session_factory() as session:
            embedded_count = _embed_knowledge_chunks(
                session=session,
                embedding_service=request.app.state.embedding_service,
            )

        return KnowledgeEmbedResponse(
            embedded_count=embedded_count,
        )

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
