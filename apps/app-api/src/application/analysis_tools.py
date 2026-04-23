from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.persistence.models import CallSession
from src.services.rag import RAGService, RetrievedKnowledgeChunk

StructuredToolType: Any

try:
    from langchain_core.tools import StructuredTool as _StructuredTool

    StructuredToolType = _StructuredTool
except ImportError:  # pragma: no cover - exercised only when langchain-core is absent
    StructuredToolType = None


@dataclass(frozen=True)
class AnalysisToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class AnalysisTool:
    definition: AnalysisToolDefinition
    handler: Any


@dataclass(frozen=True)
class AnalysisToolAPI:
    _tools: dict[str, AnalysisTool]

    def definitions(self) -> list[AnalysisToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    def tool_names(self) -> list[str]:
        return [definition.name for definition in self.definitions()]

    def invoke(self, tool_name: str, **kwargs: Any) -> Any:
        try:
            tool = self._tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"Unknown analysis tool: {tool_name}") from exc

        return tool.handler(**kwargs)


class RetrieveContextArgs(BaseModel):
    call_id: int
    limit: int = Field(default=5)


class GetCallMetadataArgs(BaseModel):
    call_id: int


def _serialize_retrieved_chunk(
    chunk: RetrievedKnowledgeChunk | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(chunk, Mapping):
        return dict(chunk)

    return asdict(chunk)


def _get_call_metadata(
    *,
    call_id: int,
    session_factory: sessionmaker[Session],
) -> dict[str, Any]:
    with session_factory() as session:
        call_session = session.get(CallSession, call_id)
        if call_session is None:
            raise RuntimeError(f"CallSession not found for call_id={call_id}.")

        return {
            "call_id": call_session.id,
            "external_call_id": call_session.external_call_id,
            "processing_status": call_session.processing_status.value,
            "audio_storage_key": call_session.audio_storage_key,
            "source_type": call_session.source_type,
            "metadata": call_session.metadata_json,
        }


def _retrieve_context(
    *,
    call_id: int,
    rag_service: RAGService,
    limit: int = 5,
) -> list[dict[str, Any]]:
    return [
        _serialize_retrieved_chunk(chunk)
        for chunk in rag_service.search_for_call(call_id=call_id, limit=limit)
    ]


def build_analysis_tool_api(
    *,
    session_factory: sessionmaker[Session],
    rag_service: RAGService,
) -> AnalysisToolAPI:
    tools = {
        "retrieve_context": AnalysisTool(
            definition=AnalysisToolDefinition(
                name="retrieve_context",
                description="Retrieve knowledge-base context for a call.",
                parameters={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["call_id"],
                    "properties": {
                        "call_id": {"type": "integer"},
                        "limit": {"type": "integer", "default": 5},
                    },
                },
            ),
            handler=lambda **kwargs: _retrieve_context(
                rag_service=rag_service,
                **kwargs,
            ),
        ),
        "get_call_metadata": AnalysisTool(
            definition=AnalysisToolDefinition(
                name="get_call_metadata",
                description="Get stored metadata for a call.",
                parameters={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["call_id"],
                    "properties": {
                        "call_id": {"type": "integer"},
                    },
                },
            ),
            handler=lambda **kwargs: _get_call_metadata(
                session_factory=session_factory,
                **kwargs,
            ),
        ),
    }
    return AnalysisToolAPI(_tools=tools)


def build_tool_api(
    *,
    session_factory: sessionmaker[Session],
    rag_service: RAGService,
) -> dict[str, Any]:
    def retrieve_context(call_id: int, limit: int = 5) -> list[dict[str, Any]]:
        return _retrieve_context(
            call_id=call_id,
            limit=limit,
            rag_service=rag_service,
        )

    def get_call_metadata(call_id: int) -> dict[str, Any]:
        return _get_call_metadata(
            call_id=call_id,
            session_factory=session_factory,
        )

    return {
        "retrieve_context": retrieve_context,
        "get_call_metadata": get_call_metadata,
    }


def build_langchain_tools(
    *,
    session_factory: sessionmaker[Session],
    rag_service: RAGService,
) -> list[Any]:
    tool_api = build_tool_api(
        session_factory=session_factory,
        rag_service=rag_service,
    )
    structured_tool_cls = StructuredToolType
    if structured_tool_cls is None:
        return [
            tool_api["retrieve_context"],
            tool_api["get_call_metadata"],
        ]

    return [
        structured_tool_cls.from_function(
            func=tool_api["retrieve_context"],
            name="retrieve_context",
            description="Retrieve knowledge-base context for a call.",
            args_schema=RetrieveContextArgs,
        ),
        structured_tool_cls.from_function(
            func=tool_api["get_call_metadata"],
            name="get_call_metadata",
            description="Get stored metadata for a call.",
            args_schema=GetCallMetadataArgs,
        ),
    ]
