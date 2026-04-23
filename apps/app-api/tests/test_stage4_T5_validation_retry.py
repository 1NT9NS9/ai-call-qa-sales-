import importlib
import inspect
import unittest
from types import SimpleNamespace

from src.services.rag import RetrievedKnowledgeChunk


MODEL_PARAMETER_NAMES = (
    "llm",
    "chat_model",
    "model",
    "analysis_model",
    "llm_model",
)
VALID_ANALYSIS_OUTPUT = {
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


class _FakeBoundLLM:
    def __init__(self, parent, responses):
        self._parent = parent
        self._responses = responses
        self._index = 0

    def invoke(self, payload):
        self._parent.invocations.append(payload)
        response = self._responses[self._index]
        if self._index < len(self._responses) - 1:
            self._index += 1
        return response


class _FakeLangChainModel:
    def __init__(self, responses):
        self._responses = responses
        self.bound_tools = None
        self.invocations: list[object] = []

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return _FakeBoundLLM(self, self._responses)


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


def _analysis_service_module():
    return importlib.import_module("src.application.analysis_service")


def _build_service_with_fake_model(fake_model):
    analysis_service_module = _analysis_service_module()
    build_service = analysis_service_module.build_analysis_service
    signature = inspect.signature(build_service)

    rag_service = SimpleNamespace(
        search_for_call=lambda call_id, limit=5: [
            RetrievedKnowledgeChunk(
                chunk_id=7,
                document_id=3,
                source_path="data/kb_seed/objection-handling-pricing.md",
                chunk_text="Handle pricing objections by reframing value.",
                chunk_index=0,
                distance=0.12,
            )
        ][:limit]
    )
    session_factory = _FakeSessionFactory(
        call_session=SimpleNamespace(
            id=99,
            external_call_id="ext-99",
            processing_status=SimpleNamespace(value="transcribed"),
            audio_storage_key="call-99.wav",
            source_type="api",
            metadata_json={"campaign": "stage4", "channel": "sales"},
        ),
        transcript_segments=[
            SimpleNamespace(
                id=1,
                speaker="customer",
                text="Pricing is expensive.",
                start_ms=0,
                end_ms=1000,
                sequence_no=1,
            )
        ],
    )

    kwargs = {
        "session_factory": session_factory,
        "rag_service": rag_service,
    }
    for parameter_name in MODEL_PARAMETER_NAMES:
        if parameter_name in signature.parameters:
            kwargs[parameter_name] = fake_model
            break

    return build_service(**kwargs)


class Stage4ValidationRetryTests(unittest.TestCase):
    def test_schema_conformant_output_passes_validation(self) -> None:
        service = _build_service_with_fake_model(
            _FakeLangChainModel(
                responses=[{"content": importlib.import_module("json").dumps(VALID_ANALYSIS_OUTPUT)}]
            )
        )

        result = service.analyze(call_id=99)

        self.assertEqual(result, VALID_ANALYSIS_OUTPUT)

    def test_invalid_json_triggers_exactly_one_retry(self) -> None:
        fake_model = _FakeLangChainModel(
            responses=[
                {"content": '{"summary":'},
                {"content": importlib.import_module("json").dumps(VALID_ANALYSIS_OUTPUT)},
            ]
        )
        service = _build_service_with_fake_model(fake_model)

        result = service.analyze(call_id=99)

        self.assertEqual(result, VALID_ANALYSIS_OUTPUT)
        self.assertEqual(len(fake_model.invocations), 2)

    def test_schema_invalid_json_triggers_exactly_one_retry(self) -> None:
        fake_model = _FakeLangChainModel(
            responses=[
                {"content": '{"summary": "stub"}'},
                {"content": importlib.import_module("json").dumps(VALID_ANALYSIS_OUTPUT)},
            ]
        )
        service = _build_service_with_fake_model(fake_model)

        result = service.analyze(call_id=99)

        self.assertEqual(result, VALID_ANALYSIS_OUTPUT)
        self.assertEqual(len(fake_model.invocations), 2)

    def test_invalid_output_does_not_retry_more_than_once(self) -> None:
        analysis_service_module = _analysis_service_module()
        fake_model = _FakeLangChainModel(
            responses=[
                {"content": '{"summary":'},
                {"content": '{"summary":'},
            ]
        )
        service = _build_service_with_fake_model(fake_model)

        with self.assertRaises(analysis_service_module.AnalysisOutputValidationError):
            service.analyze(call_id=99)

        self.assertEqual(len(fake_model.invocations), 2)
