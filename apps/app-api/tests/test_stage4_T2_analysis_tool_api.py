import unittest
from types import SimpleNamespace

from src.application.analysis_service import build_analysis_service
from src.services.rag import RetrievedKnowledgeChunk


class _FakeSessionContext:
    def __init__(self, call_session):
        self._call_session = call_session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, call_id):
        if self._call_session.id != call_id:
            return None
        return self._call_session


class _FakeSessionFactory:
    def __init__(self, call_session):
        self._call_session = call_session

    def __call__(self):
        return _FakeSessionContext(self._call_session)


class _FakeRAGService:
    def __init__(self, matches):
        self._matches = matches
        self.calls = []

    def search_for_call(self, call_id: int, limit: int = 5):
        self.calls.append({"call_id": call_id, "limit": limit})
        return self._matches[:limit]


class Stage4AnalysisToolApiTests(unittest.TestCase):
    def test_stage4_analysis_service_registers_only_approved_tools(self) -> None:
        service = build_analysis_service(
            session_factory=_FakeSessionFactory(
                SimpleNamespace(
                    id=41,
                    external_call_id="ext-41",
                    processing_status=SimpleNamespace(value="transcribed"),
                    audio_storage_key="call-41.wav",
                    source_type="api",
                    metadata_json={"campaign": "stage4"},
                )
            ),
            rag_service=_FakeRAGService([]),
        )

        definitions = service.tool_definitions()

        self.assertEqual(
            [definition["name"] for definition in definitions],
            ["retrieve_context", "get_call_metadata"],
        )
        self.assertEqual(len(definitions), 2)

    def test_stage4_analysis_service_invokes_both_approved_tools_and_no_extra_tool(
        self,
    ) -> None:
        rag_matches = [
            RetrievedKnowledgeChunk(
                chunk_id=7,
                document_id=3,
                source_path="data/kb_seed/objection-handling-pricing.md",
                chunk_text="Handle pricing objections by reframing value.",
                chunk_index=0,
                distance=0.12,
            ),
        ]
        rag_service = _FakeRAGService(rag_matches)
        service = build_analysis_service(
            session_factory=_FakeSessionFactory(
                SimpleNamespace(
                    id=99,
                    external_call_id="ext-99",
                    processing_status=SimpleNamespace(value="transcribed"),
                    audio_storage_key="call-99.wav",
                    source_type="api",
                    metadata_json={"campaign": "stage4", "channel": "sales"},
                )
            ),
            rag_service=rag_service,
        )

        retrieved_context = service.invoke_tool(
            "retrieve_context",
            call_id=99,
            limit=1,
        )
        call_metadata = service.invoke_tool("get_call_metadata", call_id=99)

        self.assertEqual(
            retrieved_context,
            [
                {
                    "chunk_id": 7,
                    "document_id": 3,
                    "source_path": "data/kb_seed/objection-handling-pricing.md",
                    "chunk_text": "Handle pricing objections by reframing value.",
                    "chunk_index": 0,
                    "distance": 0.12,
                }
            ],
        )
        self.assertEqual(rag_service.calls, [{"call_id": 99, "limit": 1}])
        self.assertEqual(
            call_metadata,
            {
                "call_id": 99,
                "external_call_id": "ext-99",
                "processing_status": "transcribed",
                "audio_storage_key": "call-99.wav",
                "source_type": "api",
                "metadata": {"campaign": "stage4", "channel": "sales"},
            },
        )
        with self.assertRaisesRegex(KeyError, "Unknown analysis tool"):
            service.invoke_tool("extra_tool", call_id=99)
