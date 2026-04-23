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
    "external_call_id": "ext-call-stage4-t6",
    "source_type": "api",
    "metadata": {"campaign": "stage4", "channel": "sales"},
}
FIXED_TRANSCRIPT_SEGMENTS = [
    {
        "speaker": "customer",
        "text": "The pricing feels expensive and our budget approval is slow.",
        "start_ms": 0,
        "end_ms": 1200,
        "sequence_no": 1,
    },
    {
        "speaker": "agent",
        "text": "We can map the value to your rollout plan and help with internal approval.",
        "start_ms": 1200,
        "end_ms": 2600,
        "sequence_no": 2,
    },
]
VALID_ANALYSIS_RESULT_WITH_SERVICE_OWNED_CONFIDENCE = {
    "summary": "Customer raised pricing concerns and requested approval support.",
    "score": 8.0,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 4.0,
            "max_score": 5.0,
            "reason": "The rep uncovered pricing and approval friction.",
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
            "evidence_segment_ids": [],
        }
    ],
    "next_best_action": "Send a mutual action plan with ROI framing.",
    "coach_feedback": "Tie pricing back to rollout value and next steps.",
    "used_knowledge": [],
    "confidence": 0.11,
    "needs_review": False,
    "review_reasons": [],
}
EXPECTED_COMPUTED_CONFIDENCE = 0.65


class _FakeBoundModel:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.invocations: list[object] = []

    def invoke(self, payload):
        self.invocations.append(payload)
        return SimpleNamespace(content=self._response_text)


class _FakeChatModel:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.bound_tools = None
        self.bound_model = _FakeBoundModel(response_text)

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self.bound_model


class Stage4ConfidencePersistenceTests(unittest.TestCase):
    def _run_successful_analysis(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage4-t6-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage4_t6") as database_url:
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
                    call_session = session.get(persistence_models.CallSession, call_id)
                    call_session.processing_status = (
                        persistence_models.CallProcessingStatus.TRANSCRIBED
                    )
                    session.commit()

                fake_chat_model = _FakeChatModel(
                    json.dumps(VALID_ANALYSIS_RESULT_WITH_SERVICE_OWNED_CONFIDENCE)
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

                return (
                    result_payload,
                    persisted_analysis,
                    persisted_call,
                    persistence_models,
                    fake_chat_model,
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_stage4_successful_analysis_computes_service_owned_confidence(
        self,
    ) -> None:
        (
            result_payload,
            _persisted_analysis,
            _persisted_call,
            _persistence_models,
            fake_chat_model,
        ) = self._run_successful_analysis()

        self.assertIsInstance(
            result_payload,
            dict,
            "expected analyze(call_id) to return the analysis payload",
        )
        self.assertEqual(
            result_payload["confidence"],
            EXPECTED_COMPUTED_CONFIDENCE,
            "expected the returned payload confidence to use the fixed service-owned formula",
        )
        self.assertEqual(
            len(fake_chat_model.bound_model.invocations),
            1,
            "expected the happy-path confidence run to invoke the model once",
        )

    def test_stage4_successful_analysis_persists_callanalysis_and_moves_call_to_analyzed(
        self,
    ) -> None:
        (
            result_payload,
            persisted_analysis,
            persisted_call,
            persistence_models,
            _fake_chat_model,
        ) = self._run_successful_analysis()

        self.assertIsNotNone(
            persisted_analysis,
            "expected a successful analysis run to create a persisted CallAnalysis record",
        )
        self.assertEqual(
            persisted_analysis.result_json,
            result_payload,
            "expected the persisted CallAnalysis payload to match the returned analysis payload",
        )
        self.assertEqual(
            persisted_analysis.confidence,
            EXPECTED_COMPUTED_CONFIDENCE,
            "expected persisted CallAnalysis.confidence to match the fixed formula",
        )
        self.assertEqual(
            result_payload["confidence"],
            persisted_analysis.confidence,
            "expected payload confidence to mirror persisted CallAnalysis.confidence",
        )
        self.assertEqual(
            persisted_call.processing_status,
            persistence_models.CallProcessingStatus.ANALYZED,
            "expected the successful Stage 4 persistence path to move the call to analyzed",
        )
