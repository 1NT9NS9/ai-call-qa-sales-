import importlib
import inspect
import json
import unittest
from types import SimpleNamespace

from conftest import clear_src_modules


VALID_ANALYSIS_RESULT = {
    "summary": "Customer raised pricing concerns and asked for next steps.",
    "score": 8.5,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 4.0,
            "max_score": 5.0,
            "reason": "The rep uncovered budget approval blockers.",
        }
    ],
    "objections": [
        {
            "text": "Pricing feels expensive.",
            "handled": True,
            "evidence_segment_ids": [1],
        }
    ],
    "risks": [
        {
            "text": "Budget approval may delay the deal.",
            "severity": "medium",
            "evidence_segment_ids": [1],
        }
    ],
    "next_best_action": "Send a mutual action plan with pricing justification.",
    "coach_feedback": "Keep tying price to business impact.",
    "used_knowledge": [
        {
            "document_id": 3,
            "chunk_id": 7,
            "reason": "Pricing objection guidance strengthened the recommendation.",
        }
    ],
    "confidence": 0.82,
    "needs_review": False,
    "review_reasons": [],
}
SCHEMA_INVALID_ANALYSIS_RESULT = {
    **VALID_ANALYSIS_RESULT,
    "summary": 123,
}
INVALID_JSON_RESPONSE = '{"summary": "missing closing brace"'
ANALYSIS_MODEL_PARAMETER_NAMES = (
    "chat_model",
    "llm",
    "model",
    "analysis_model",
    "llm_model",
)


class _FakeTranscriptSegment:
    def __init__(
        self,
        *,
        segment_id: int,
        speaker: str,
        text: str,
        start_ms: int,
        end_ms: int,
        sequence_no: int,
    ) -> None:
        self.id = segment_id
        self.speaker = speaker
        self.text = text
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.sequence_no = sequence_no


class _FakeSessionContext:
    def __init__(self, transcript_segments, call_session):
        self._transcript_segments = transcript_segments
        self._call_session = call_session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalars(self, *_args, **_kwargs):
        return list(self._transcript_segments)

    def get(self, *_args, **_kwargs):
        return self._call_session


class _FakeSessionFactory:
    def __init__(self, transcript_segments, call_session):
        self._transcript_segments = transcript_segments
        self._call_session = call_session

    def __call__(self):
        return _FakeSessionContext(
            transcript_segments=self._transcript_segments,
            call_session=self._call_session,
        )


class _FakeBoundModel:
    def __init__(self, parent):
        self._parent = parent

    def invoke(self, payload):
        self._parent.invocation_payloads.append(payload)
        try:
            response_text = self._parent.responses[self._parent._index]
        except IndexError as exc:
            raise AssertionError("Fake analysis model ran out of queued responses.") from exc
        self._parent._index += 1
        if isinstance(response_text, dict):
            return response_text
        return SimpleNamespace(content=response_text)


class _FakeChatModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.bound_tools = None
        self.invocation_payloads = []
        self._index = 0

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return _FakeBoundModel(self)


def _analysis_service_module():
    clear_src_modules()
    return importlib.import_module("src.application.analysis_service")


def _build_analysis_service(*, fake_chat_model):
    analysis_service_module = _analysis_service_module()
    build_service = analysis_service_module.build_analysis_service

    transcript_segments = [
        _FakeTranscriptSegment(
            segment_id=1,
            speaker="customer",
            text="The pricing feels expensive and finance needs a plan.",
            start_ms=0,
            end_ms=1000,
            sequence_no=1,
        ),
        _FakeTranscriptSegment(
            segment_id=2,
            speaker="agent",
            text="I will send next steps and ROI framing.",
            start_ms=1000,
            end_ms=2000,
            sequence_no=2,
        ),
    ]
    call_session = SimpleNamespace(
        id=99,
        external_call_id="ext-stage4-t5",
        processing_status=SimpleNamespace(value="transcribed"),
        audio_storage_key="call-99.wav",
        source_type="api",
        metadata_json={"campaign": "stage4", "channel": "sales"},
    )
    session_factory = _FakeSessionFactory(
        transcript_segments=transcript_segments,
        call_session=call_session,
    )
    rag_service = SimpleNamespace(
        search_for_call=lambda call_id, limit=5: [
            {
                "chunk_id": 7,
                "document_id": 3,
                "source_path": "data/kb_seed/objection-handling-pricing.md",
                "chunk_text": "Handle pricing objections by reframing value.",
                "chunk_index": 0,
                "distance": 0.12,
            }
        ][:limit]
    )

    signature = inspect.signature(build_service)
    kwargs = {}
    for parameter in signature.parameters.values():
        if parameter.name == "session_factory":
            kwargs[parameter.name] = session_factory
        elif parameter.name == "rag_service":
            kwargs[parameter.name] = rag_service
        elif parameter.name in ANALYSIS_MODEL_PARAMETER_NAMES:
            kwargs[parameter.name] = fake_chat_model

    return build_service(**kwargs)


class Stage4OutputValidationRetryTests(unittest.TestCase):
    def test_stage4_accepts_schema_conformant_analysis_output(self) -> None:
        service = _build_analysis_service(
            fake_chat_model=_FakeChatModel(
                [json.dumps(VALID_ANALYSIS_RESULT)]
            )
        )

        result = service.analyze(call_id=99)

        self.assertEqual(
            result,
            VALID_ANALYSIS_RESULT,
            "expected Stage 4 analysis to parse and return schema-valid JSON output",
        )

    def test_stage4_invalid_json_triggers_exactly_one_retry(self) -> None:
        fake_model = _FakeChatModel(
            [
                INVALID_JSON_RESPONSE,
                json.dumps(VALID_ANALYSIS_RESULT),
            ]
        )
        service = _build_analysis_service(fake_chat_model=fake_model)

        result = service.analyze(call_id=99)

        self.assertEqual(result, VALID_ANALYSIS_RESULT)
        self.assertEqual(
            len(fake_model.invocation_payloads),
            2,
            "expected invalid JSON to trigger exactly one retry",
        )

    def test_stage4_schema_invalid_json_triggers_exactly_one_retry(self) -> None:
        fake_model = _FakeChatModel(
            [
                json.dumps(SCHEMA_INVALID_ANALYSIS_RESULT),
                json.dumps(VALID_ANALYSIS_RESULT),
            ]
        )
        service = _build_analysis_service(fake_chat_model=fake_model)

        result = service.analyze(call_id=99)

        self.assertEqual(result, VALID_ANALYSIS_RESULT)
        self.assertEqual(
            len(fake_model.invocation_payloads),
            2,
            "expected schema-invalid JSON to trigger exactly one retry",
        )

    def test_stage4_invalid_json_in_dict_shaped_langchain_response_triggers_one_retry(
        self,
    ) -> None:
        fake_model = _FakeChatModel(
            [
                {
                    "content": INVALID_JSON_RESPONSE,
                    "tool_names": ["retrieve_context", "get_call_metadata"],
                },
                {
                    "content": json.dumps(VALID_ANALYSIS_RESULT),
                    "tool_names": ["retrieve_context", "get_call_metadata"],
                },
            ]
        )
        service = _build_analysis_service(fake_chat_model=fake_model)

        result = service.analyze(call_id=99)

        self.assertEqual(result, VALID_ANALYSIS_RESULT)
        self.assertEqual(
            len(fake_model.invocation_payloads),
            2,
            "expected invalid JSON in a dict-shaped LangChain response to trigger exactly one retry",
        )
        self.assertNotEqual(
            result,
            {
                "content": INVALID_JSON_RESPONSE,
                "tool_names": ["retrieve_context", "get_call_metadata"],
            },
            "expected the service not to accept the invalid response payload directly",
        )

    def test_stage4_schema_invalid_dict_shaped_langchain_response_triggers_one_retry(
        self,
    ) -> None:
        fake_model = _FakeChatModel(
            [
                {
                    "content": json.dumps(SCHEMA_INVALID_ANALYSIS_RESULT),
                    "tool_names": ["retrieve_context", "get_call_metadata"],
                },
                {
                    "content": json.dumps(VALID_ANALYSIS_RESULT),
                    "tool_names": ["retrieve_context", "get_call_metadata"],
                },
            ]
        )
        service = _build_analysis_service(fake_chat_model=fake_model)

        result = service.analyze(call_id=99)

        self.assertEqual(result, VALID_ANALYSIS_RESULT)
        self.assertEqual(
            len(fake_model.invocation_payloads),
            2,
            "expected schema-invalid JSON in a dict-shaped LangChain response to trigger exactly one retry",
        )
        self.assertNotEqual(
            result,
            {
                "content": json.dumps(SCHEMA_INVALID_ANALYSIS_RESULT),
                "tool_names": ["retrieve_context", "get_call_metadata"],
            },
            "expected the service not to accept a schema-invalid response payload directly",
        )

    def test_stage4_does_not_retry_more_than_once_for_repeated_invalid_output(
        self,
    ) -> None:
        fake_model = _FakeChatModel(
            [
                INVALID_JSON_RESPONSE,
                INVALID_JSON_RESPONSE,
                json.dumps(VALID_ANALYSIS_RESULT),
            ]
        )
        service = _build_analysis_service(fake_chat_model=fake_model)

        with self.assertRaises(Exception):
            service.analyze(call_id=99)

        self.assertEqual(
            len(fake_model.invocation_payloads),
            2,
            "expected Stage 4 to stop after the initial attempt plus one retry",
        )

    def test_stage4_dict_shaped_langchain_response_stops_after_retry_budget_is_exhausted(
        self,
    ) -> None:
        fake_model = _FakeChatModel(
            [
                {
                    "content": INVALID_JSON_RESPONSE,
                    "tool_names": ["retrieve_context", "get_call_metadata"],
                },
                {
                    "content": json.dumps(SCHEMA_INVALID_ANALYSIS_RESULT),
                    "tool_names": ["retrieve_context", "get_call_metadata"],
                },
                {
                    "content": json.dumps(VALID_ANALYSIS_RESULT),
                    "tool_names": ["retrieve_context", "get_call_metadata"],
                },
            ]
        )
        service = _build_analysis_service(fake_chat_model=fake_model)

        with self.assertRaises(Exception):
            service.analyze(call_id=99)

        self.assertEqual(
            len(fake_model.invocation_payloads),
            2,
            "expected dict-shaped LangChain responses to stop after the initial attempt plus one retry",
        )
