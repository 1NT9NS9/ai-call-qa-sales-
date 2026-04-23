import importlib
import json
import shutil
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from conftest import (
    ALEMBIC_INI_PATH,
    TEST_TMP_ROOT,
    clear_src_modules,
    temporary_postgres_database,
)
from fastapi.testclient import TestClient
from sqlalchemy import insert


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage4-t8",
    "source_type": "api",
    "metadata": {"campaign": "stage4", "channel": "sales"},
}
FIXED_TRANSCRIPT_SEGMENTS = [
    {
        "speaker": "customer",
        "text": "The pricing feels expensive and finance approval is taking too long.",
        "start_ms": 0,
        "end_ms": 1300,
        "sequence_no": 1,
    },
    {
        "speaker": "agent",
        "text": "I can send ROI proof, rollout timing, and a mutual action plan today.",
        "start_ms": 1300,
        "end_ms": 2800,
        "sequence_no": 2,
    },
]
VALID_HAPPY_PATH_ANALYSIS_RESULT = {
    "summary": "Customer raised pricing and finance approval concerns.",
    "score": 8.7,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 4.5,
            "max_score": 5.0,
            "reason": "The rep surfaced the pricing objection and approval blocker.",
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
            "text": "Finance approval may delay the deal.",
            "severity": "medium",
            "evidence_segment_ids": [1],
        }
    ],
    "next_best_action": "Send ROI proof and a mutual action plan.",
    "coach_feedback": "Keep connecting price to rollout value and approval urgency.",
    "used_knowledge": [
        {
            "document_id": 3,
            "chunk_id": 7,
            "reason": "Pricing objection guidance supported the recommendation.",
        }
    ],
    "confidence": 0.12,
    "needs_review": False,
    "review_reasons": [],
}
EXPECTED_STAGE4_FIELDS = {
    "summary",
    "score",
    "score_breakdown",
    "objections",
    "risks",
    "next_best_action",
    "coach_feedback",
    "used_knowledge",
    "confidence",
    "needs_review",
    "review_reasons",
}


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


class Stage4BoundedVerificationTests(unittest.TestCase):
    def test_stage4_happy_path_end_to_end_persists_schema_conformant_analysis_result(
        self,
    ) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage4-t8-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage4_t8") as database_url:
                env_values = {
                    "APP_ENV": "test",
                    "APP_HOST": "127.0.0.1",
                    "APP_PORT": "8000",
                    "DATABASE_URL": database_url,
                    "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
                }

                with patch.dict("os.environ", env_values, clear=True):
                    alembic_config = Config(str(ALEMBIC_INI_PATH))
                    command.upgrade(alembic_config, "head")

                    clear_src_modules()
                    main_module = importlib.import_module("src.main")
                    analysis_service_module = importlib.import_module(
                        "src.application.analysis_service"
                    )
                    persistence_models = importlib.import_module(
                        "src.infrastructure.persistence.models"
                    )
                    app = main_module.create_app()

                    with TestClient(app) as client:
                        import_response = client.post("/knowledge/import")
                        embed_response = client.post("/knowledge/embed")
                        create_call_response = client.post(
                            "/calls",
                            json=CREATE_CALL_PAYLOAD,
                        )
                        self.assertEqual(import_response.status_code, 201)
                        self.assertEqual(embed_response.status_code, 200)
                        self.assertEqual(create_call_response.status_code, 201)

                        call_id = create_call_response.json()["id"]
                        with app.state.session_factory() as session:
                            session.execute(
                                insert(persistence_models.TranscriptSegment),
                                [
                                    {"call_id": call_id, **segment}
                                    for segment in FIXED_TRANSCRIPT_SEGMENTS
                                ],
                            )
                            call_session = session.get(
                                persistence_models.CallSession,
                                call_id,
                            )
                            call_session.processing_status = (
                                persistence_models.CallProcessingStatus.TRANSCRIBED
                            )
                            session.commit()

                        fake_chat_model = _FakeChatModel(
                            json.dumps(VALID_HAPPY_PATH_ANALYSIS_RESULT)
                        )
                        analysis_service = analysis_service_module.build_analysis_service(
                            session_factory=app.state.session_factory,
                            rag_service=app.state.rag_service,
                            chat_model=fake_chat_model,
                        )

                        result_payload = analysis_service.analyze(call_id=call_id)

                        with app.state.session_factory() as session:
                            persisted_analysis = session.get(
                                persistence_models.CallAnalysis,
                                call_id,
                            )
                            persisted_call = session.get(
                                persistence_models.CallSession,
                                call_id,
                            )

                self.assertIsInstance(
                    result_payload,
                    dict,
                    "expected the Stage 4 happy path to return a structured analysis payload",
                )
                self.assertEqual(
                    set(result_payload),
                    EXPECTED_STAGE4_FIELDS,
                    "expected the happy-path analysis payload to include exactly the Stage 4 contract fields",
                )
                self.assertIsInstance(result_payload["summary"], str)
                self.assertIsInstance(result_payload["score"], (int, float))
                self.assertIsInstance(result_payload["score_breakdown"], list)
                self.assertIsInstance(result_payload["objections"], list)
                self.assertIsInstance(result_payload["risks"], list)
                self.assertIsInstance(result_payload["used_knowledge"], list)
                self.assertIsInstance(result_payload["needs_review"], bool)
                self.assertEqual(
                    result_payload["review_reasons"],
                    [],
                    "expected the fixed happy path not to route through review mode",
                )
                self.assertGreaterEqual(result_payload["confidence"], 0.0)
                self.assertLessEqual(result_payload["confidence"], 1.0)

                self.assertIsNotNone(
                    persisted_analysis,
                    "expected the happy-path Stage 4 run to persist a CallAnalysis record",
                )
                self.assertEqual(
                    persisted_analysis.result_json,
                    result_payload,
                    "expected the persisted CallAnalysis payload to match the returned happy-path payload",
                )
                self.assertEqual(
                    persisted_analysis.confidence,
                    result_payload["confidence"],
                    "expected the persisted confidence to match the returned happy-path confidence",
                )
                self.assertFalse(
                    persisted_analysis.review_required,
                    "expected the happy path to persist a non-review analysis record",
                )
                self.assertEqual(
                    persisted_call.processing_status,
                    persistence_models.CallProcessingStatus.ANALYZED,
                    "expected the successful Stage 4 happy path to move the call lifecycle to analyzed",
                )
                self.assertEqual(
                    len(fake_chat_model.bound_model.invocations),
                    1,
                    "expected the bounded Stage 4 happy-path verification to invoke the model once",
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
