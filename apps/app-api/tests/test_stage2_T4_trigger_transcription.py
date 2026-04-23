import importlib
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage2-t4",
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
class Stage2TriggerTranscriptionTests(unittest.TestCase):
    def test_post_call_audio_invokes_stt_adapter_for_uploaded_audio(self) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage2-t4-{uuid.uuid4().hex}"
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

                clear_src_modules()
                main_module = importlib.import_module("src.main")
                persistence_models = importlib.import_module(
                    "src.infrastructure.persistence.models"
                )

                try:
                    app = main_module.create_app()
                    transcribe_mock = Mock(return_value=[])
                    app.state.stt_adapter = Mock(transcribe=transcribe_mock)

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
                    clear_src_modules()

            engine = create_engine(database_url)
            with engine.connect() as connection:
                row = connection.execute(
                    select(persistence_models.CallSession.__table__).where(
                        persistence_models.CallSession.id == call_id
                    )
                ).mappings().one()

            audio_storage_key = row["audio_storage_key"]
            self.assertIsNotNone(audio_storage_key)
            transcribe_mock.assert_called_once_with(Path(temp_root / "audio" / audio_storage_key))
        finally:
            clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
