import importlib
import shutil
import unittest
import uuid
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from conftest import ALEMBIC_INI_PATH, TEST_TMP_ROOT, clear_src_modules
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select


REPO_ROOT = Path(__file__).resolve().parents[3]
KB_SEED_DIR = REPO_ROOT / "data" / "kb_seed"


class Stage3KnowledgeChunkingTests(unittest.TestCase):
    def test_post_knowledge_import_persists_retrievable_chunks_for_imported_documents(
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
        temp_root = TEST_TMP_ROOT / f"stage3-t3-{uuid.uuid4().hex}"
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
                imported_chunks = connection.execute(
                    select(persistence_models.KnowledgeChunk.__table__).order_by(
                        persistence_models.KnowledgeChunk.document_id,
                        persistence_models.KnowledgeChunk.chunk_index,
                    )
                ).mappings().all()

            self.assertEqual(len(imported_documents), len(seed_documents))
            self.assertGreater(
                len(imported_chunks),
                0,
                "expected imported knowledge documents to produce persisted chunks",
            )

            chunk_counts_by_document = Counter(
                row["document_id"] for row in imported_chunks
            )
            imported_document_ids = {row["id"] for row in imported_documents}

            self.assertEqual(
                set(chunk_counts_by_document),
                imported_document_ids,
                "expected every imported knowledge document to have persisted chunks",
            )
            self.assertTrue(
                all(count > 0 for count in chunk_counts_by_document.values()),
                "expected each imported knowledge document to be represented by at least one chunk",
            )
            self.assertTrue(
                all(row["chunk_text"] for row in imported_chunks),
                "expected persisted chunks to contain non-empty chunk_text values",
            )
        finally:
            clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
