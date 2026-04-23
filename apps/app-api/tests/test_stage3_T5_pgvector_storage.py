import importlib
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from alembic import command
from alembic.config import Config
from conftest import (
    ALEMBIC_INI_PATH,
    TEST_TMP_ROOT,
    clear_src_modules,
    temporary_postgres_database,
)
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[3]
KB_SEED_DIR = REPO_ROOT / "data" / "kb_seed"


class Stage3PgvectorStorageTests(unittest.TestCase):
    def test_stage3_embed_flow_persists_chunk_vectors_in_pgvector(self) -> None:
        seed_documents = sorted(
            path
            for path in KB_SEED_DIR.iterdir()
            if path.is_file() and path.name != ".gitkeep"
        )
        self.assertGreaterEqual(len(seed_documents), 5)
        self.assertLessEqual(len(seed_documents), 10)

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage3-t5-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage3_t5") as database_url:
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

                    clear_src_modules()
                    main_module = importlib.import_module("src.main")
                    app = main_module.create_app()

                    with TestClient(app) as client:
                        import_response = client.post("/knowledge/import")
                        embed_response = client.post("/knowledge/embed")

                self.assertEqual(import_response.status_code, 201)
                self.assertEqual(embed_response.status_code, 200)

                import_payload = import_response.json()
                self.assertGreaterEqual(import_payload["imported_count"], 5)
                self.assertLessEqual(import_payload["imported_count"], 10)
                self.assertGreater(
                    import_payload["chunk_count"],
                    0,
                    "expected /knowledge/import to persist knowledge chunks before embedding",
                )
                self.assertEqual(
                    embed_response.json()["embedded_count"],
                    import_payload["chunk_count"],
                    "expected /knowledge/embed to persist a vector for every imported chunk",
                )

                with psycopg.connect(database_url.replace("+psycopg", "")) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT data_type, udt_name
                            FROM information_schema.columns
                            WHERE table_name = 'knowledge_chunk_vectors'
                              AND column_name = 'embedding'
                            """
                        )
                        embedding_column = cursor.fetchone()
                        cursor.execute(
                            """
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = 'knowledge_chunks'
                              AND column_name = 'embedding'
                            """
                        )
                        legacy_embedding_column = cursor.fetchone()
                        cursor.execute("SELECT COUNT(*) FROM knowledge_chunks")
                        chunk_count = cursor.fetchone()[0]
                        cursor.execute("SELECT COUNT(*) FROM knowledge_chunk_vectors")
                        vector_count = cursor.fetchone()[0]
                        cursor.execute(
                            """
                            SELECT COUNT(*)
                            FROM knowledge_chunk_vectors
                            WHERE vector_dims(embedding) > 0
                            """
                        )
                        non_empty_vector_count = cursor.fetchone()[0]

                self.assertEqual(
                    embedding_column,
                    ("USER-DEFINED", "vector"),
                    "expected knowledge_chunk_vectors.embedding to use the pgvector type",
                )
                self.assertIsNone(
                    legacy_embedding_column,
                    "expected the legacy knowledge_chunks.embedding column to be removed",
                )
                self.assertEqual(
                    vector_count,
                    chunk_count,
                    "expected every imported knowledge chunk to have a pgvector row",
                )
                self.assertGreater(
                    vector_count,
                    0,
                    "expected stored vectors to exist in knowledge_chunk_vectors",
                )
                self.assertEqual(
                    non_empty_vector_count,
                    vector_count,
                    "expected persisted pgvector rows to contain non-empty vectors",
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
