import json
import unittest
from types import SimpleNamespace
from typing import Any

from src.application.analysis_service import AnalysisService
from src.application.analysis_tools import (
    AnalysisToolAPI,
    build_analysis_tool_api,
    build_langchain_tools,
)
from src.services.rag import RetrievedKnowledgeChunk


APPROVED_TOOL_NAMES = ["retrieve_context", "get_call_metadata"]
VALID_ANALYSIS_RESULT = {
    "summary": "Customer raised pricing and approval concerns.",
    "score": 7.5,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 3.0,
            "max_score": 5.0,
            "reason": "Some context gathered.",
        }
    ],
    "objections": [
        {
            "text": "Pricing is expensive.",
            "handled": True,
            "evidence_segment_ids": [1],
        }
    ],
    "risks": [
        {
            "text": "Internal approval may stall.",
            "severity": "medium",
            "evidence_segment_ids": [1],
        }
    ],
    "next_best_action": "Send a mutual action plan.",
    "coach_feedback": "Tie value to approval process.",
    "used_knowledge": [
        {
            "document_id": 3,
            "chunk_id": 7,
            "reason": "Pricing objection guidance applied.",
        }
    ],
    "confidence": 0.82,
    "needs_review": False,
    "review_reasons": [],
}


class _RecordingToolAPI:
    def __init__(self, inner: AnalysisToolAPI) -> None:
        self._inner = inner
        self.invocations: list[str] = []

    def definitions(self):
        return self._inner.definitions()

    def invoke(self, tool_name: str, **kwargs: Any) -> Any:
        self.invocations.append(tool_name)
        return self._inner.invoke(tool_name, **kwargs)


class _FakeBoundModel:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.invocations: list[object] = []

    def invoke(self, payload):
        self.invocations.append(payload)
        return SimpleNamespace(content=self._response_text)


class _FakeChatModel:
    def __init__(self, response_text: str) -> None:
        self.bound_tools = None
        self.bound_model = _FakeBoundModel(response_text)

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self.bound_model


class _FakeSessionContext:
    def __init__(self, call_session, transcript_segments):
        self._call_session = call_session
        self._transcript_segments = transcript_segments

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalars(self, *_args, **_kwargs):
        return list(self._transcript_segments)

    def get(self, *_args, **_kwargs):
        return self._call_session


class _FakeSessionFactory:
    def __init__(self, call_session, transcript_segments):
        self._call_session = call_session
        self._transcript_segments = transcript_segments

    def __call__(self):
        return _FakeSessionContext(self._call_session, self._transcript_segments)


class _FakeRAGService:
    def __init__(self):
        self.calls: list[dict[str, int]] = []

    def search_for_call(self, call_id: int, limit: int = 5):
        self.calls.append({"call_id": call_id, "limit": limit})
        return [
            RetrievedKnowledgeChunk(
                chunk_id=7,
                document_id=3,
                source_path="data/kb_seed/objection-handling-pricing.md",
                chunk_text="Handle pricing objections by reframing value.",
                chunk_index=0,
                distance=0.12,
            )
        ][:limit]


def _tool_name(tool: object) -> str | None:
    for attr_name in ("name", "tool_name", "__name__"):
        value = getattr(tool, attr_name, None)
        if isinstance(value, str) and value:
            return value

    if hasattr(tool, "func"):
        return _tool_name(getattr(tool, "func"))

    return None


class Stage4ApprovedToolBoundaryTests(unittest.TestCase):
    def test_stage4_analysis_run_registers_and_uses_only_approved_tools(self) -> None:
        call_session = SimpleNamespace(
            id=99,
            external_call_id="ext-99",
            processing_status=SimpleNamespace(value="transcribed"),
            audio_storage_key="call-99.wav",
            source_type="api",
            metadata_json={"campaign": "stage4", "channel": "sales"},
        )
        transcript_segments = [
            SimpleNamespace(
                id=1,
                speaker="customer",
                text="The pricing feels expensive and finance needs approval support.",
                start_ms=0,
                end_ms=1000,
                sequence_no=1,
            ),
            SimpleNamespace(
                id=2,
                speaker="agent",
                text="I will send next steps, ROI framing, and a mutual action plan.",
                start_ms=1000,
                end_ms=2000,
                sequence_no=2,
            ),
        ]
        session_factory = _FakeSessionFactory(call_session, transcript_segments)
        rag_service = _FakeRAGService()
        recording_tool_api = _RecordingToolAPI(
            build_analysis_tool_api(
                session_factory=session_factory,
                rag_service=rag_service,
            )
        )
        fake_chat_model = _FakeChatModel(json.dumps(VALID_ANALYSIS_RESULT))
        service = AnalysisService(
            tool_api=recording_tool_api,
            session_factory=session_factory,
            chat_model=fake_chat_model,
            langchain_tools=build_langchain_tools(
                session_factory=session_factory,
                rag_service=rag_service,
            ),
        )

        result = service.analyze(call_id=99)

        self.assertEqual(
            [definition["name"] for definition in service.tool_definitions()],
            APPROVED_TOOL_NAMES,
            "expected Stage 4 tool registration to expose only the approved tools",
        )
        self.assertEqual(
            [_tool_name(tool) for tool in fake_chat_model.bound_tools],
            APPROVED_TOOL_NAMES,
            "expected the Stage 4 analysis run to bind only the approved tools into LangChain",
        )
        self.assertEqual(
            recording_tool_api.invocations,
            APPROVED_TOOL_NAMES,
            "expected the Stage 4 analysis run to invoke only retrieve_context and get_call_metadata",
        )
        self.assertEqual(
            rag_service.calls,
            [{"call_id": 99, "limit": 5}],
            "expected the approved retrieve_context path to be the only retrieval call during analysis",
        )
        self.assertEqual(
            len(fake_chat_model.bound_model.invocations),
            1,
            "expected the bounded Stage 4 analysis run to invoke the bound model once",
        )
        self.assertEqual(
            result,
            VALID_ANALYSIS_RESULT,
            "expected the bounded Stage 4 analysis run to complete successfully",
        )
        with self.assertRaisesRegex(KeyError, "Unknown analysis tool"):
            service.invoke_tool("extra_tool", call_id=99)
