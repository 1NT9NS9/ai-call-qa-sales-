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
from sqlalchemy import create_engine, inspect, select


APP_API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = APP_API_ROOT / "alembic.ini"
REQUIRED_STAGE1_TABLES = {
    "call_sessions",
    "transcript_segments",
    "knowledge_documents",
    "knowledge_chunks",
    "call_analyses",
    "delivery_events",
}
CALLS_PAYLOAD = {
    "external_call_id": "ext-call-008",
    "audio_storage_key": "audio/uploads/ext-call-008.wav",
    "source_type": "api",
    "metadata": {"campaign": "stage1", "channel": "sales"},
}


def _clear_src_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)


class Stage1BoundedVerificationTests(unittest.TestCase):
    def _create_clean_database_context(self) -> tuple[Path, str]:
        temp_root = APP_API_ROOT / f".tmp-stage1-t8-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(temp_root / 'stage1.db').as_posix()}"
        return temp_root, database_url

    def test_clean_database_migrations_create_stage1_schema_and_keep_review_fields_separate(
        self,
    ) -> None:
        temp_root, database_url = self._create_clean_database_context()
        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": database_url,
            "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
        }
        engine = None

        try:
            with patch.dict("os.environ", env_values, clear=True):
                alembic_config = Config(str(ALEMBIC_INI_PATH))
                command.upgrade(alembic_config, "head")

            engine = create_engine(database_url)
            inspector = inspect(engine)
            table_names = set(inspector.get_table_names())

            self.assertTrue(REQUIRED_STAGE1_TABLES.issubset(table_names))

            call_session_columns = {
                column["name"] for column in inspector.get_columns("call_sessions")
            }
            call_analysis_columns = {
                column["name"] for column in inspector.get_columns("call_analyses")
            }

            self.assertIn("processing_status", call_session_columns)
            self.assertIn("review_required", call_analysis_columns)
            self.assertIn("review_reasons", call_analysis_columns)
            self.assertNotIn("review_required", call_session_columns)
            self.assertNotIn("review_reasons", call_session_columns)
        finally:
            _clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_post_calls_creates_persisted_callsession_with_stored_processing_status(
        self,
    ) -> None:
        temp_root, database_url = self._create_clean_database_context()
        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": database_url,
            "STORAGE_AUDIO_DIR": str(temp_root / "audio"),
        }
        engine = None

        try:
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

            self.assertEqual(response.status_code, 201)

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
