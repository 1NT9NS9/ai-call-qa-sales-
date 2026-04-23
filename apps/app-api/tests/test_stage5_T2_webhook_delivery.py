import importlib
import os
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient


WEBHOOK_TARGET_URL = "https://receiver.example.test/stage5"
CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage5-t2",
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
class _FakeWebhookResponse:
    def __init__(self, status_code: int = 202) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


class _RecordingHttpxClient:
    def __init__(self, recorded_calls: list[dict[str, object]], *args, **kwargs) -> None:
        self._recorded_calls = recorded_calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url, *args, **kwargs):
        self._recorded_calls.append(
            {
                "url": url,
                "args": args,
                "kwargs": kwargs,
            }
        )
        return _FakeWebhookResponse()


class Stage5WebhookDeliveryTests(unittest.TestCase):
    def _create_clean_database_context(self) -> tuple[Path, str]:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage5-t2-{uuid.uuid4().hex}"
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

    def _mark_call_transcribed(self, app, persistence_models, call_id: int) -> None:
        with app.state.session_factory() as session:
            call_session = session.get(persistence_models.CallSession, call_id)
            call_session.processing_status = (
                persistence_models.CallProcessingStatus.TRANSCRIBED
            )
            session.commit()

    def test_stage5_export_endpoint_posts_completed_result_to_single_webhook_target(
        self,
    ) -> None:
        temp_root, database_url = self._create_clean_database_context()
        recorded_calls: list[dict[str, object]] = []
        fake_httpx_client = lambda *args, **kwargs: _RecordingHttpxClient(
            recorded_calls, *args, **kwargs
        )

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
                call_id = self._create_call(client)
                self._mark_call_analyzed(app, persistence_models, call_id)

                with patch(
                    "src.adapters.delivery.httpx.Client",
                    new=fake_httpx_client,
                ):
                    export_response = client.post(f"/calls/{call_id}/export")

            self.assertEqual(export_response.status_code, 200)
            response_payload = export_response.json()
            self.assertEqual(response_payload["result_id"], call_id)
            self.assertEqual(response_payload["status"], "completed")
            self.assertEqual(response_payload["target_url"], WEBHOOK_TARGET_URL)
            datetime.fromisoformat(
                response_payload["delivered_at"].replace("Z", "+00:00")
            )

            self.assertEqual(
                len(recorded_calls),
                1,
                "expected exactly one outbound webhook POST for the Stage 5 T2 happy path",
            )
            outbound_request = recorded_calls[0]
            self.assertEqual(outbound_request["url"], WEBHOOK_TARGET_URL)

            payload = outbound_request["kwargs"]["json"]
            self.assertEqual(
                set(payload),
                {"resultId", "status", "deliveredAt", "result"},
                "expected the Stage 5 T2 webhook payload to stay minimal and include the final result data",
            )
            self.assertEqual(payload["resultId"], call_id)
            self.assertEqual(payload["status"], "completed")
            datetime.fromisoformat(payload["deliveredAt"].replace("Z", "+00:00"))
            self.assertEqual(payload["result"], ANALYSIS_RESULT)
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_stage5_export_endpoint_skips_webhook_delivery_for_non_completed_calls(
        self,
    ) -> None:
        temp_root, database_url = self._create_clean_database_context()
        recorded_calls: list[dict[str, object]] = []
        fake_httpx_client = lambda *args, **kwargs: _RecordingHttpxClient(
            recorded_calls, *args, **kwargs
        )

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
                call_id = self._create_call(client)
                self._mark_call_transcribed(app, persistence_models, call_id)

                with patch(
                    "src.adapters.delivery.httpx.Client",
                    new=fake_httpx_client,
                ):
                    export_response = client.post(f"/calls/{call_id}/export")

            self.assertEqual(export_response.status_code, 409)
            self.assertEqual(
                recorded_calls,
                [],
                "expected Stage 5 T2 to avoid outbound webhook delivery before the result is completed",
            )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
