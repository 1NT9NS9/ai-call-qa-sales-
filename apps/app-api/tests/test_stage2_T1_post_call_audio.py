import importlib
import shutil
import unittest
import uuid
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage2-t1",
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
class Stage2PostCallAudioTests(unittest.TestCase):
    def test_post_call_audio_accepts_audio_for_existing_call_session(self) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage2-t1-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": f"sqlite:///{(temp_root / 'stage2.db').as_posix()}",
            "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
        }

        try:
            with patch.dict("os.environ", env_values, clear=True):
                alembic_config = Config(str(ALEMBIC_INI_PATH))
                command.upgrade(alembic_config, "head")

                clear_src_modules()
                main_module = importlib.import_module("src.main")

                try:
                    with TestClient(main_module.create_app()) as client:
                        create_response = client.post("/calls", json=CREATE_CALL_PAYLOAD)
                        self.assertEqual(create_response.status_code, 201)

                        call_id = create_response.json()["id"]
                        upload_response = client.post(
                            f"/calls/{call_id}/audio",
                            files=AUDIO_UPLOAD,
                        )
                finally:
                    clear_src_modules()

            self.assertGreaterEqual(upload_response.status_code, 200)
            self.assertLess(upload_response.status_code, 300)
            self.assertEqual(upload_response.json()["call_id"], call_id)
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
