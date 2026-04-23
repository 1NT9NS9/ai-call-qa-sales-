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


REPO_ROOT = Path(__file__).resolve().parents[3]
KB_SEED_DIR = REPO_ROOT / "data" / "kb_seed"


class Stage3KnowledgeImportTests(unittest.TestCase):
    def test_post_knowledge_import_loads_seed_documents_as_knowledge_documents(
        self,
    ) -> None:
        seed_documents = sorted(
            path
            for path in KB_SEED_DIR.iterdir()
            if path.is_file() and path.name != ".gitkeep"
        )
        self.assertGreaterEqual(len(seed_documents), 5)
        self.assertLessEqual(len(seed_documents), 10)

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage3-t2-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(temp_root / 'stage3.db').as_posix()}"
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

                clear_src_modules()
                main_module = importlib.import_module("src.main")
                persistence_models = importlib.import_module(
                    "src.infrastructure.persistence.models"
                )

                try:
                    with TestClient(main_module.create_app()) as client:
                        response = client.post("/knowledge/import")
                finally:
                    clear_src_modules()

            self.assertGreaterEqual(response.status_code, 200)
            self.assertLess(response.status_code, 300)

            engine = create_engine(database_url)
            with engine.connect() as connection:
                imported_documents = connection.execute(
                    select(persistence_models.KnowledgeDocument.__table__)
                ).mappings().all()

            self.assertEqual(len(imported_documents), len(seed_documents))
            imported_by_path = {
                row["source_path"]: row["content"] for row in imported_documents
            }
            expected_by_path = {
                path.relative_to(REPO_ROOT).as_posix(): path.read_text(encoding="utf-8")
                for path in seed_documents
            }
            self.assertEqual(imported_by_path, expected_by_path)
        finally:
            clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
