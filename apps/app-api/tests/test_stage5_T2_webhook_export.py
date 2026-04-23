import importlib
import json
import shutil
import threading
import unittest
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient
from sqlalchemy import insert


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage5-t2",
    "source_type": "api",
    "metadata": {"campaign": "stage5", "channel": "sales"},
}
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


class _WebhookReceiverHandler(BaseHTTPRequestHandler):
    received_requests: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        payload = json.loads(raw_body.decode("utf-8"))
        self.__class__.received_requests.append(
            {
                "path": self.path,
                "payload": payload,
            }
        )

        response_body = json.dumps({"accepted": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: object) -> None:
        return


class Stage5WebhookExportTests(unittest.TestCase):
    def _create_clean_database_context(self) -> tuple[Path, str]:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage5-t2-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(temp_root / 'stage5.db').as_posix()}"
        return temp_root, database_url

    def test_export_endpoint_posts_completed_result_to_configured_webhook(
        self,
    ) -> None:
        temp_root, database_url = self._create_clean_database_context()
        receiver = ThreadingHTTPServer(("127.0.0.1", 0), _WebhookReceiverHandler)
        receiver_thread = threading.Thread(target=receiver.serve_forever, daemon=True)
        receiver_thread.start()
        _WebhookReceiverHandler.received_requests = []

        webhook_url = (
            f"http://127.0.0.1:{receiver.server_address[1]}/demo-webhook"
        )
        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": database_url,
            "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
            "WEBHOOK_TARGET_URL": webhook_url,
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
                                    {
                                        "call_id": call_id,
                                        "speaker": "customer",
                                        "text": "Pricing still feels high for our team.",
                                        "start_ms": 0,
                                        "end_ms": 1100,
                                        "sequence_no": 1,
                                    },
                                    {
                                        "call_id": call_id,
                                        "speaker": "agent",
                                        "text": "I can send the ROI summary and next steps today.",
                                        "start_ms": 1100,
                                        "end_ms": 2400,
                                        "sequence_no": 2,
                                    },
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

                        export_response = client.post(f"/calls/{call_id}/export")

                        with app.state.session_factory() as session:
                            refreshed_call = session.get(
                                persistence_models.CallSession,
                                call_id,
                            )
                finally:
                    clear_src_modules()

            self.assertEqual(export_response.status_code, 200)
            body = export_response.json()
            self.assertEqual(body["result_id"], call_id)
            self.assertEqual(body["status"], "completed")
            self.assertEqual(body["target_url"], webhook_url)
            datetime.fromisoformat(body["delivered_at"].replace("Z", "+00:00"))

            self.assertEqual(len(_WebhookReceiverHandler.received_requests), 1)
            delivered_request = _WebhookReceiverHandler.received_requests[0]
            self.assertEqual(delivered_request["path"], "/demo-webhook")

            delivered_payload = delivered_request["payload"]
            self.assertEqual(delivered_payload["resultId"], call_id)
            self.assertEqual(delivered_payload["status"], "completed")
            self.assertEqual(delivered_payload["result"], ANALYSIS_RESULT)
            datetime.fromisoformat(
                str(delivered_payload["deliveredAt"]).replace("Z", "+00:00")
            )

            self.assertEqual(
                refreshed_call.processing_status,
                persistence_models.CallProcessingStatus.EXPORTED,
            )
        finally:
            clear_src_modules()
            receiver.shutdown()
            receiver.server_close()
            receiver_thread.join(timeout=5)
            shutil.rmtree(temp_root, ignore_errors=True)
