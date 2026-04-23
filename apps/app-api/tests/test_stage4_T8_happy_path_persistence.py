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
    {
        "speaker": "customer",
        "text": "If you can send next steps and a mutual action plan, I can review it with finance.",
        "start_ms": 2600,
        "end_ms": 4100,
        "sequence_no": 3,
    },
]
VALID_ANALYSIS_RESULT = {
    "summary": "Customer raised pricing concerns and asked for approval help plus next steps.",
    "score": 8.7,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 4.5,
            "max_score": 5.0,
            "reason": "The rep uncovered pricing and approval blockers clearly.",
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
            "evidence_segment_ids": [1, 3],
        }
    ],
    "next_best_action": "Send a mutual action plan with ROI framing and approval next steps.",
    "coach_feedback": "Tie pricing to rollout value and confirm the finance process earlier.",
    "used_knowledge": [
        {
            "document_id": 3,
            "chunk_id": 7,
            "reason": "Pricing objection guidance improved the response.",
        }
    ],
    "confidence": 0.25,
    "needs_review": False,
    "review_reasons": [],
}
EXPECTED_COMPUTED_CONFIDENCE = 1.0


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


class Stage4HappyPathPersistenceTests(unittest.TestCase):
    def test_stage4_happy_path_end_to_end_persists_schema_conformant_analysis(
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
                            json.dumps(VALID_ANALYSIS_RESULT)
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

                schema_errors = analysis_service._validate_schema_instance(
                    instance=result_payload,
                    schema=analysis_service.load_assets().schema,
                )
                self.assertEqual(
                    schema_errors,
                    [],
                    "expected the happy-path Stage 4 result to conform to the external analysis schema",
                )
                self.assertEqual(
                    len(fake_chat_model.bound_model.invocations),
                    1,
                    "expected the happy-path Stage 4 verification run to invoke the model once",
                )

                analysis_payload = fake_chat_model.bound_model.invocations[0]
                prompt_context = analysis_payload["context"]
                self.assertEqual(
                    [segment["text"] for segment in prompt_context["transcript"]],
                    [segment["text"] for segment in FIXED_TRANSCRIPT_SEGMENTS],
                    "expected the analysis invocation to use the fixed persisted transcript fixture",
                )
                retrieved_source_paths = [
                    item["source_path"] for item in prompt_context["retrieved_context"]
                ]
                self.assertTrue(
                    any(
                        source_path.endswith("mutual-action-plan-template.md")
                        for source_path in retrieved_source_paths
                    ),
                    "expected the happy-path analysis invocation to include mutual action plan guidance from the real Stage 3 path",
                )
                self.assertTrue(
                    any(
                        source_path.endswith("objection-handling-pricing.md")
                        for source_path in retrieved_source_paths
                    ),
                    "expected the happy-path analysis invocation to include pricing guidance from the real Stage 3 path",
                )

                self.assertIsNotNone(
                    persisted_analysis,
                    "expected the happy-path Stage 4 run to persist a CallAnalysis record",
                )
                self.assertEqual(
                    persisted_analysis.result_json,
                    result_payload,
                    "expected the persisted CallAnalysis payload to match the returned analysis payload",
                )
                self.assertEqual(
                    persisted_analysis.confidence,
                    EXPECTED_COMPUTED_CONFIDENCE,
                    "expected the persisted CallAnalysis confidence to store the computed service-owned value",
                )
                self.assertEqual(
                    result_payload["confidence"],
                    EXPECTED_COMPUTED_CONFIDENCE,
                    "expected the happy-path returned payload to mirror the stored confidence",
                )
                self.assertFalse(
                    persisted_analysis.review_required,
                    "expected the happy-path persisted analysis not to require review",
                )
                self.assertEqual(
                    persisted_call.processing_status,
                    persistence_models.CallProcessingStatus.ANALYZED,
                    "expected the happy-path persistence branch to move the call to analyzed",
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
