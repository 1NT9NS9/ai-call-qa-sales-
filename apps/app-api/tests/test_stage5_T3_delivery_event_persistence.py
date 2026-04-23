import importlib
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient


WEBHOOK_TARGET_URL = "https://receiver.example.test/stage5"
CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage5-t3",
    "source_type": "api",
    "metadata": {"campaign": "stage5", "channel": "sales"},
}
ANALYSIS_RESULT = {
    "summary": "Customer raised a pricing objection and asked for next steps.",
    "score": 8.9,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 4.4,
            "max_score": 5.0,
            "reason": "The rep identified the pricing concern and follow-up need.",
        }
    ],
    "objections": [
        {
            "text": "Pricing feels high.",
            "handled": True,
            "evidence_segment_ids": [1],
        }
    ],
    "risks": [],
    "next_best_action": "Send ROI proof and confirm a mutual action plan.",
    "coach_feedback": "Keep tying the price back to rollout value.",
    "used_knowledge": [],
    "confidence": 0.93,
    "needs_review": False,
    "review_reasons": [],
}


class _FakeSuccessResponse:
    def __init__(self, status_code: int = 202) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


class _SuccessHttpxClient:
    def __init__(self, *args, **kwargs) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url, *args, **kwargs):
        return _FakeSuccessResponse()


class _FailureHttpxClient:
    def __init__(self, *args, **kwargs) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url, *args, **kwargs):
        request = httpx.Request("POST", url)
        response = httpx.Response(502, request=request)
        raise httpx.HTTPStatusError(
            "Server error '502 Bad Gateway' for url",
            request=request,
            response=response,
        )


class Stage5DeliveryEventPersistenceTests(unittest.TestCase):
    def _create_clean_database_context(self) -> tuple[Path, str]:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage5-t3-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(temp_root / 'stage5.db').as_posix()}"
        return temp_root, database_url

    def _create_app(self, env_values: dict[str, str]):
        clear_src_modules()
        with patch.dict("os.environ", env_values, clear=True):
            alembic_config = Config(str(ALEMBIC_INI_PATH))
            command.upgrade(alembic_config, "head")
            main_module = importlib.import_module("src.main")
            persistence_models = importlib.import_module(
                "src.infrastructure.persistence.models"
            )
            app = main_module.create_app()

        return app, persistence_models

    def _seed_analyzed_call(self, client: TestClient, app, persistence_models) -> int:
        create_response = client.post("/calls", json=CREATE_CALL_PAYLOAD)
        self.assertEqual(create_response.status_code, 201)
        call_id = create_response.json()["id"]

        with app.state.session_factory() as session:
            session.add(
                persistence_models.CallAnalysis(
                    call_id=call_id,
                    result_json=ANALYSIS_RESULT,
                    confidence=ANALYSIS_RESULT["confidence"],
                    review_required=False,
                    review_reasons=[],
                )
            )
            call_session = session.get(persistence_models.CallSession, call_id)
            call_session.processing_status = (
                persistence_models.CallProcessingStatus.ANALYZED
            )
            session.commit()

        return call_id

    def test_export_persists_success_delivery_event(self) -> None:
        temp_root, database_url = self._create_clean_database_context()
        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": database_url,
            "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
            "WEBHOOK_TARGET_URL": WEBHOOK_TARGET_URL,
        }

        try:
            app, persistence_models = self._create_app(env_values)

            with TestClient(app) as client:
                call_id = self._seed_analyzed_call(client, app, persistence_models)
                with patch(
                    "src.adapters.delivery.httpx.Client",
                    new=_SuccessHttpxClient,
                ):
                    export_response = client.post(f"/calls/{call_id}/export")

            self.assertEqual(export_response.status_code, 200)

            with app.state.session_factory() as session:
                persisted_event = session.get(
                    persistence_models.DeliveryEvent,
                    {"call_id": call_id, "attempt_no": 1},
                )

            self.assertIsNotNone(persisted_event)
            self.assertEqual(persisted_event.target_url, WEBHOOK_TARGET_URL)
            self.assertEqual(persisted_event.delivery_status, "success")
            self.assertEqual(persisted_event.response_code, 202)
            self.assertEqual(persisted_event.attempt_no, 1)
            self.assertIsNotNone(persisted_event.attempted_at)
            self.assertIsNone(persisted_event.error_message)
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_export_persists_failed_delivery_event(self) -> None:
        temp_root, database_url = self._create_clean_database_context()
        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": database_url,
            "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
            "WEBHOOK_TARGET_URL": WEBHOOK_TARGET_URL,
        }

        try:
            app, persistence_models = self._create_app(env_values)

            with TestClient(app) as client:
                call_id = self._seed_analyzed_call(client, app, persistence_models)
                with patch(
                    "src.adapters.delivery.httpx.Client",
                    new=_FailureHttpxClient,
                ):
                    export_response = client.post(f"/calls/{call_id}/export")

            self.assertEqual(export_response.status_code, 502)

            with app.state.session_factory() as session:
                persisted_event = session.get(
                    persistence_models.DeliveryEvent,
                    {"call_id": call_id, "attempt_no": 1},
                )
                call_session = session.get(
                    persistence_models.CallSession,
                    call_id,
                )

            self.assertIsNotNone(persisted_event)
            self.assertEqual(persisted_event.target_url, WEBHOOK_TARGET_URL)
            self.assertEqual(persisted_event.delivery_status, "failed")
            self.assertEqual(persisted_event.response_code, 502)
            self.assertEqual(persisted_event.attempt_no, 1)
            self.assertIsNotNone(persisted_event.attempted_at)
            self.assertIn("502", persisted_event.error_message)
            self.assertEqual(
                call_session.processing_status,
                persistence_models.CallProcessingStatus.ANALYZED,
            )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
