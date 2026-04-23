import importlib
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from alembic import command
from alembic.config import Config
from conftest import (
    ALEMBIC_INI_PATH,
    TEST_TMP_ROOT,
    clear_src_modules,
    temporary_postgres_database,
)
from fastapi.testclient import TestClient
from sqlalchemy import select


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


class _SuccessfulWebhookResponse:
    def __init__(self, status_code: int = 202) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


class _SuccessfulHttpxClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url, *args, **kwargs):
        return _SuccessfulWebhookResponse()


class _FailingHttpxClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url, *args, **kwargs):
        request = httpx.Request("POST", url)
        response = httpx.Response(502, request=request)
        raise httpx.HTTPStatusError(
            "502 Bad Gateway",
            request=request,
            response=response,
        )


class Stage5DeliveryEventPersistenceTests(unittest.TestCase):
    def _create_temp_root(self) -> Path:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage5-t3-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        return temp_root

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

    def _create_call(self, client: TestClient) -> int:
        response = client.post("/calls", json=CREATE_CALL_PAYLOAD)
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def _mark_call_analyzed(self, app, persistence_models, call_id: int) -> None:
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

    def _load_delivery_events(self, app, persistence_models):
        with app.state.session_factory() as session:
            return list(
                session.scalars(
                    select(persistence_models.DeliveryEvent).order_by(
                        persistence_models.DeliveryEvent.call_id,
                        persistence_models.DeliveryEvent.attempt_no,
                    )
                )
            )

    def test_stage5_deliveryevent_schema_includes_attempt_timestamp_field(
        self,
    ) -> None:
        temp_root = self._create_temp_root()

        try:
            with temporary_postgres_database("stage5_t3") as database_url:
                env_values = {
                    "APP_ENV": "test",
                    "APP_HOST": "127.0.0.1",
                    "APP_PORT": "8000",
                    "DATABASE_URL": database_url,
                    "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
                    "WEBHOOK_TARGET_URL": WEBHOOK_TARGET_URL,
                }

                _app, persistence_models = self._create_app(env_values)
                column_names = set(persistence_models.DeliveryEvent.__table__.columns.keys())
                timestamp_columns = {
                    "attempted_at",
                    "attempt_timestamp",
                    "created_at",
                    "delivered_at",
                }

                self.assertTrue(
                    timestamp_columns & column_names,
                    "expected DeliveryEvent persistence to include an attempt timestamp field for T3 reviewability",
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_stage5_successful_export_persists_reviewable_deliveryevent(
        self,
    ) -> None:
        temp_root = self._create_temp_root()

        try:
            with temporary_postgres_database("stage5_t3") as database_url:
                env_values = {
                    "APP_ENV": "test",
                    "APP_HOST": "127.0.0.1",
                    "APP_PORT": "8000",
                    "DATABASE_URL": database_url,
                    "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
                    "WEBHOOK_TARGET_URL": WEBHOOK_TARGET_URL,
                }

                app, persistence_models = self._create_app(env_values)

                with TestClient(app) as client:
                    call_id = self._create_call(client)
                    self._mark_call_analyzed(app, persistence_models, call_id)

                    with patch(
                        "src.adapters.delivery.httpx.Client",
                        new=_SuccessfulHttpxClient,
                    ):
                        export_response = client.post(f"/calls/{call_id}/export")

                self.assertEqual(export_response.status_code, 200)

                delivery_events = self._load_delivery_events(app, persistence_models)
                self.assertEqual(
                    len(delivery_events),
                    1,
                    "expected one DeliveryEvent record for one successful webhook delivery attempt",
                )

                delivery_event = delivery_events[0]
                self.assertEqual(delivery_event.call_id, call_id)
                self.assertEqual(delivery_event.target_url, WEBHOOK_TARGET_URL)
                self.assertEqual(delivery_event.delivery_status, "success")
                self.assertEqual(delivery_event.response_code, 202)
                self.assertEqual(delivery_event.attempt_no, 1)
                self.assertIsNone(delivery_event.error_message)
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_stage5_failed_export_persists_failed_deliveryevent_with_error_summary(
        self,
    ) -> None:
        temp_root = self._create_temp_root()

        try:
            with temporary_postgres_database("stage5_t3") as database_url:
                env_values = {
                    "APP_ENV": "test",
                    "APP_HOST": "127.0.0.1",
                    "APP_PORT": "8000",
                    "DATABASE_URL": database_url,
                    "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
                    "WEBHOOK_TARGET_URL": WEBHOOK_TARGET_URL,
                }

                app, persistence_models = self._create_app(env_values)

                with TestClient(app) as client:
                    call_id = self._create_call(client)
                    self._mark_call_analyzed(app, persistence_models, call_id)

                    with patch(
                        "src.adapters.delivery.httpx.Client",
                        new=_FailingHttpxClient,
                    ):
                        export_response = client.post(f"/calls/{call_id}/export")

                self.assertEqual(export_response.status_code, 502)

                delivery_events = self._load_delivery_events(app, persistence_models)
                self.assertEqual(
                    len(delivery_events),
                    1,
                    "expected a failed webhook delivery attempt to still persist one DeliveryEvent record",
                )

                delivery_event = delivery_events[0]
                self.assertEqual(delivery_event.call_id, call_id)
                self.assertEqual(delivery_event.target_url, WEBHOOK_TARGET_URL)
                self.assertEqual(delivery_event.delivery_status, "failed")
                self.assertEqual(delivery_event.response_code, 502)
                self.assertEqual(delivery_event.attempt_no, 1)
                self.assertIsInstance(delivery_event.error_message, str)
                self.assertIn("502", delivery_event.error_message)
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
