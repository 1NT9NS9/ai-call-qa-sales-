import importlib
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage2-t2",
    "source_type": "api",
    "metadata": {"campaign": "stage2", "channel": "sales"},
}
AUDIO_FILENAME = "call.wav"
AUDIO_BYTES = b"RIFF$\x00\x00\x00WAVEfmt "
AUDIO_UPLOAD = {
    "file": (
        AUDIO_FILENAME,
        AUDIO_BYTES,
        "audio/wav",
    )
}
class Stage2PersistAudioTests(unittest.TestCase):
    def test_post_call_audio_stores_uploaded_file_and_persists_audio_storage_key(
        self,
    ) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage2-t2-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        storage_root = temp_root / "audio"
        database_url = f"sqlite:///{(temp_root / 'stage2.db').as_posix()}"
        engine = None

        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": database_url,
            "STORAGE_AUDIO_DIR": str(storage_root),
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
                    with TestClient(main_module.create_app()) as client:
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
            self.assertNotEqual(audio_storage_key, "")

            stored_path = Path(audio_storage_key)
            if not stored_path.is_absolute():
                stored_path = storage_root / stored_path

            self.assertTrue(stored_path.is_file())
            self.assertEqual(stored_path.read_bytes(), AUDIO_BYTES)
            self.assertEqual(stored_path.parent, storage_root)
        finally:
            clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
