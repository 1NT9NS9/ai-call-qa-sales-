import importlib
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select


APP_API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = APP_API_ROOT / "alembic.ini"
TEST_TMP_ROOT = APP_API_ROOT / "test-tmp-runs"
CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage2-t6",
    "source_type": "api",
    "metadata": {"campaign": "stage2", "channel": "sales"},
}
AUDIO_UPLOAD = {
    "file": (
        "call.wav",
        b"RIFF$\x00\x00\x00WAVEfmt ",
        "audio/wav",
    )
}


def _clear_src_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)


class Stage2StoreTranscriptSegmentsTests(unittest.TestCase):
    def test_post_call_audio_persists_transcript_segments_for_call_in_sequence_order(
        self,
    ) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage2-t6-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(temp_root / 'stage2.db').as_posix()}"
        engine = None

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

                _clear_src_modules()
                main_module = importlib.import_module("src.main")
                stt_module = importlib.import_module("src.adapters.stt")
                persistence_models = importlib.import_module(
                    "src.infrastructure.persistence.models"
                )

                try:
                    app = main_module.create_app()
                    app.state.stt_adapter = Mock(
                        transcribe=Mock(
                            return_value=[
                                stt_module.TranscribedSegment(
                                    speaker="agent",
                                    text="second",
                                    start_ms=200,
                                    end_ms=300,
                                    sequence_no=2,
                                ),
                                stt_module.TranscribedSegment(
                                    speaker="customer",
                                    text="first",
                                    start_ms=0,
                                    end_ms=100,
                                    sequence_no=1,
                                ),
                            ]
                        )
                    )

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
                finally:
                    _clear_src_modules()

            engine = create_engine(database_url)
            with engine.connect() as connection:
                rows = connection.execute(
                    select(persistence_models.TranscriptSegment.__table__)
                    .where(persistence_models.TranscriptSegment.call_id == call_id)
                    .order_by(persistence_models.TranscriptSegment.sequence_no)
                ).mappings().all()

            self.assertEqual(len(rows), 2)
            self.assertEqual([row["call_id"] for row in rows], [call_id, call_id])
            self.assertEqual([row["sequence_no"] for row in rows], [1, 2])
            self.assertEqual([row["text"] for row in rows], ["first", "second"])
            self.assertEqual([row["speaker"] for row in rows], ["customer", "agent"])
            self.assertEqual([row["start_ms"] for row in rows], [0, 200])
            self.assertEqual([row["end_ms"] for row in rows], [100, 300])
        finally:
            _clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
