import importlib
import shutil
import unittest
import uuid
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
    "external_call_id": "ext-call-stage4-t3",
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


class Stage4AnalysisContextTests(unittest.TestCase):
    def test_stage4_prompt_context_assembles_fixed_transcript_retrieval_and_metadata(
        self,
    ) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage4-t3-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage4_t3") as database_url:
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
                                    {
                                        "call_id": call_id,
                                        **segment,
                                    }
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

                        analysis_service = analysis_service_module.build_analysis_service(
                            session_factory=app.state.session_factory,
                            rag_service=app.state.rag_service,
                        )
                        prompt_context = analysis_service.build_prompt_context(
                            call_id=call_id,
                            context_limit=5,
                        )

                self.assertEqual(prompt_context["call_id"], call_id)
                self.assertEqual(
                    [segment["speaker"] for segment in prompt_context["transcript"]],
                    [segment["speaker"] for segment in FIXED_TRANSCRIPT_SEGMENTS],
                )
                self.assertEqual(
                    [segment["text"] for segment in prompt_context["transcript"]],
                    [segment["text"] for segment in FIXED_TRANSCRIPT_SEGMENTS],
                )
                self.assertTrue(
                    all(
                        segment["segment_id"] > 0
                        for segment in prompt_context["transcript"]
                    ),
                    "expected transcript rows to be loaded from persisted TranscriptSegment ids",
                )
                self.assertTrue(
                    prompt_context["retrieved_context"],
                    "expected assembled prompt context to include retrieved KB context",
                )
                self.assertLessEqual(len(prompt_context["retrieved_context"]), 5)
                retrieved_source_paths = [
                    item["source_path"] for item in prompt_context["retrieved_context"]
                ]
                self.assertTrue(
                    any(
                        source_path.endswith("mutual-action-plan-template.md")
                        for source_path in retrieved_source_paths
                    ),
                    (
                        "expected the fixed transcript fixture to retrieve mutual action "
                        "plan guidance through the real Stage 3 path"
                    ),
                )
                self.assertTrue(
                    any(
                        source_path.endswith("objection-handling-pricing.md")
                        for source_path in retrieved_source_paths
                    ),
                    (
                        "expected the fixed transcript fixture to retrieve pricing guidance "
                        "through the real Stage 3 path"
                    ),
                )
                self.assertEqual(
                    prompt_context["call_metadata"],
                    {
                        "call_id": call_id,
                        "external_call_id": "ext-call-stage4-t3",
                        "processing_status": "transcribed",
                        "audio_storage_key": None,
                        "source_type": "api",
                        "metadata": {"campaign": "stage4", "channel": "sales"},
                    },
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
