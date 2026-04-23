import importlib
import json
import logging
import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage5-t4",
    "source_type": "api",
    "metadata": {"campaign": "stage5", "channel": "sales"},
}
AUDIO_UPLOAD = {
    "file": (
        "call.wav",
        b"RIFF$\x00\x00\x00WAVEfmt ",
        "audio/wav",
    )
}
VALID_ANALYSIS_RESULT = {
    "summary": "Customer raised pricing concerns and requested follow-up material.",
    "score": 8.8,
    "score_breakdown": [
        {
            "criterion": "Discovery",
            "score": 4.4,
            "max_score": 5.0,
            "reason": "The rep identified the pricing blocker clearly.",
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
    "next_best_action": "Send ROI proof and a mutual action plan.",
    "coach_feedback": "Keep tying price to rollout value.",
    "used_knowledge": [],
    "confidence": 0.91,
    "needs_review": False,
    "review_reasons": [],
}


class _FakeBoundModel:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    def invoke(self, payload):
        return SimpleNamespace(content=self._response_text)


class _FakeChatModel:
    def __init__(self, response_text: str) -> None:
        self.bound_tools = None
        self.bound_model = _FakeBoundModel(response_text)

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self.bound_model


class _FakeWebhookResponse:
    def __init__(self, status_code: int = 202) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None


class _RecordingHttpxClient:
    def __init__(self, *args, **kwargs) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url, *args, **kwargs):
        return _FakeWebhookResponse()


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class Stage5PipelineLoggingTests(unittest.TestCase):
    def _create_clean_database_context(self) -> tuple[Path, str]:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage5-t4-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(temp_root / 'stage5.db').as_posix()}"
        return temp_root, database_url

    def test_end_to_end_sample_run_emits_ordered_structured_pipeline_logs(self) -> None:
        temp_root, database_url = self._create_clean_database_context()
        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": database_url,
            "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
            "WEBHOOK_TARGET_URL": "https://receiver.example.test/stage5",
        }

        try:
            with patch.dict("os.environ", env_values, clear=True):
                alembic_config = Config(str(ALEMBIC_INI_PATH))
                command.upgrade(alembic_config, "head")

                clear_src_modules()
                main_module = importlib.import_module("src.main")
                stt_module = importlib.import_module("src.adapters.stt")
                analysis_service_module = importlib.import_module(
                    "src.application.analysis_service"
                )

                try:
                    app = main_module.create_app()
                    app.state.stt_adapter = Mock(
                        transcribe=Mock(
                            return_value=[
                                stt_module.TranscribedSegment(
                                    speaker="customer",
                                    text="Pricing feels high for our team.",
                                    start_ms=0,
                                    end_ms=1000,
                                    sequence_no=1,
                                ),
                                stt_module.TranscribedSegment(
                                    speaker="agent",
                                    text="I can send ROI proof and next steps today.",
                                    start_ms=1000,
                                    end_ms=2000,
                                    sequence_no=2,
                                ),
                            ]
                        )
                    )
                    app.state.rag_service = SimpleNamespace(
                        search_for_call=lambda call_id, limit=5: []
                    )
                    pipeline_logger = logging.getLogger("app.pipeline")
                    previous_level = pipeline_logger.level
                    previous_disabled = pipeline_logger.disabled
                    list_handler = _ListHandler()
                    list_handler.setLevel(logging.INFO)
                    pipeline_logger.addHandler(list_handler)
                    pipeline_logger.disabled = False
                    pipeline_logger.setLevel(logging.INFO)

                    try:
                        with TestClient(app) as client:
                            create_response = client.post("/calls", json=CREATE_CALL_PAYLOAD)
                            self.assertEqual(create_response.status_code, 201)
                            call_id = create_response.json()["id"]

                            upload_response = client.post(
                                f"/calls/{call_id}/audio",
                                files=AUDIO_UPLOAD,
                            )
                            self.assertGreaterEqual(upload_response.status_code, 200)
                            self.assertLess(upload_response.status_code, 300)

                            analysis_service = (
                                analysis_service_module.build_analysis_service(
                                    session_factory=app.state.session_factory,
                                    rag_service=app.state.rag_service,
                                    chat_model=_FakeChatModel(
                                        json.dumps(VALID_ANALYSIS_RESULT)
                                    ),
                                )
                            )
                            analysis_result = analysis_service.analyze(call_id=call_id)
                            self.assertFalse(analysis_result["needs_review"])

                            with patch(
                                "src.adapters.delivery.httpx.Client",
                                new=_RecordingHttpxClient,
                            ):
                                export_response = client.post(f"/calls/{call_id}/export")
                                self.assertEqual(export_response.status_code, 200)
                    finally:
                        pipeline_logger.removeHandler(list_handler)
                        pipeline_logger.disabled = previous_disabled
                        pipeline_logger.setLevel(previous_level)
                finally:
                    clear_src_modules()

            log_events = [
                json.loads(entry)
                for entry in list_handler.messages
            ]
            ordered_events = [event["event"] for event in log_events]

            self.assertEqual(
                ordered_events,
                [
                    "pipeline.started",
                    "transcription.completed",
                    "analysis.started",
                    "analysis.completed",
                    "export.started",
                    "webhook.delivery_result",
                ],
            )
            self.assertTrue(all(event["call_id"] == call_id for event in log_events))
            self.assertEqual(log_events[0]["processing_status"], "created")
            self.assertEqual(log_events[1]["processing_status"], "transcribed")
            self.assertEqual(log_events[3]["processing_status"], "analyzed")
            self.assertEqual(log_events[5]["processing_status"], "exported")
            self.assertEqual(log_events[5]["status"], "success")
            self.assertEqual(log_events[5]["response_code"], 202)
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
