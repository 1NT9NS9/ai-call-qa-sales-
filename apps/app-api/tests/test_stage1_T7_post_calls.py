import importlib
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select


APP_API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = APP_API_ROOT / "alembic.ini"
CALLS_PAYLOAD = {
    "external_call_id": "ext-call-001",
    "audio_storage_key": "audio/uploads/ext-call-001.wav",
    "source_type": "api",
    "metadata": {"campaign": "stage1", "channel": "sales"},
}


def _clear_src_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)


class Stage1PostCallsTests(unittest.TestCase):
    def test_post_calls_creates_persisted_callsession_with_created_status(
        self,
    ) -> None:
        temp_root = APP_API_ROOT / f".tmp-stage1-t7-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        engine = None
        try:
            database_url = f"sqlite:///{(temp_root / 'stage1.db').as_posix()}"
            env_values = {
                "APP_ENV": "test",
                "APP_HOST": "127.0.0.1",
                "APP_PORT": "8000",
                "DATABASE_URL": database_url,
                "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
            }

            with patch.dict("os.environ", env_values, clear=True):
                alembic_config = Config(str(ALEMBIC_INI_PATH))
                command.upgrade(alembic_config, "head")

                _clear_src_modules()
                main_module = importlib.import_module("src.main")
                persistence_models = importlib.import_module(
                    "src.infrastructure.persistence.models"
                )

                try:
                    with TestClient(main_module.create_app()) as client:
                        response = client.post("/calls", json=CALLS_PAYLOAD)
                finally:
                    _clear_src_modules()

            self.assertGreaterEqual(response.status_code, 200)
            self.assertLess(response.status_code, 300)

            engine = create_engine(database_url)
            with engine.connect() as connection:
                rows = connection.execute(
                    select(persistence_models.CallSession.__table__)
                ).mappings().all()

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["external_call_id"], CALLS_PAYLOAD["external_call_id"])
            self.assertEqual(
                row["audio_storage_key"], CALLS_PAYLOAD["audio_storage_key"]
            )
            self.assertEqual(row["source_type"], CALLS_PAYLOAD["source_type"])
            self.assertEqual(row["metadata"], CALLS_PAYLOAD["metadata"])
            self.assertEqual(
                getattr(row["processing_status"], "value", row["processing_status"]),
                "created",
            )
        finally:
            _clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
