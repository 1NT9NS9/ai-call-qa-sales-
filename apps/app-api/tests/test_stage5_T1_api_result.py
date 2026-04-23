import importlib
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient
from sqlalchemy import insert


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage5-t1",
    "source_type": "api",
    "metadata": {"campaign": "stage5", "channel": "sales"},
}
TRANSCRIPT_SEGMENTS = [
    {
        "speaker": "customer",
        "text": "Pricing still feels high for our team.",
        "start_ms": 0,
        "end_ms": 1100,
        "sequence_no": 1,
    },
    {
        "speaker": "agent",
        "text": "I can send the ROI summary and next steps today.",
        "start_ms": 1100,
        "end_ms": 2400,
        "sequence_no": 2,
    },
]
ANALYSIS_RESULT = {
    "summary": "Customer raised a pricing objection and asked for follow-up material.",
    "score": 8.4,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 4.2,
            "max_score": 5.0,
            "reason": "The rep identified the pricing concern clearly.",
        }
    ],
    "objections": [
        {
            "text": "Pricing feels high.",
            "handled": True,
            "evidence_segment_ids": [1, 2],
        }
    ],
    "risks": [],
    "next_best_action": "Send the ROI summary and confirm next steps.",
    "coach_feedback": "Keep tying price back to business value.",
    "used_knowledge": [],
    "confidence": 0.9,
    "needs_review": False,
    "review_reasons": [],
}


class Stage5ApiResultTests(unittest.TestCase):
    def _create_clean_database_context(self) -> tuple[Path, str]:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage5-t1-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(temp_root / 'stage5.db').as_posix()}"
        return temp_root, database_url

    def test_get_call_returns_persisted_final_result_for_known_analyzed_call(
        self,
    ) -> None:
        temp_root, database_url = self._create_clean_database_context()

        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": database_url,
            "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
        }

        try:
            with patch.dict("os.environ", env_values, clear=True):
                alembic_config = Config(str(ALEMBIC_INI_PATH))
                command.upgrade(alembic_config, "head")

                clear_src_modules()
                main_module = importlib.import_module("src.main")
                persistence_models = importlib.import_module(
                    "src.infrastructure.persistence.models"
                )

                try:
                    app = main_module.create_app()

                    with TestClient(app) as client:
                        create_response = client.post("/calls", json=CREATE_CALL_PAYLOAD)
                        self.assertEqual(create_response.status_code, 201)

                        call_id = create_response.json()["id"]
                        with app.state.session_factory() as session:
                            session.execute(
                                insert(persistence_models.TranscriptSegment),
                                [
                                    {"call_id": call_id, **segment}
                                    for segment in TRANSCRIPT_SEGMENTS
                                ],
                            )
                            session.add(
                                persistence_models.CallAnalysis(
                                    call_id=call_id,
                                    result_json=ANALYSIS_RESULT,
                                    confidence=ANALYSIS_RESULT["confidence"],
                                    review_required=False,
                                    review_reasons=[],
                                )
                            )
                            call_session = session.get(
                                persistence_models.CallSession,
                                call_id,
                            )
                            call_session.processing_status = (
                                persistence_models.CallProcessingStatus.ANALYZED
                            )
                            session.commit()

                        response = client.get(f"/calls/{call_id}")
                finally:
                    clear_src_modules()

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["id"], call_id)
            self.assertEqual(payload["processing_status"], "analyzed")
            self.assertEqual(payload["result"], ANALYSIS_RESULT)
            self.assertEqual(
                [segment["sequence_no"] for segment in payload["transcript_segments"]],
                [1, 2],
            )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
