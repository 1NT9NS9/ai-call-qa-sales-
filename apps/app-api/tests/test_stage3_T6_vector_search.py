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


class Stage3VectorSearchTests(unittest.TestCase):
    def test_stage3_vector_search_returns_stored_chunks_from_pgvector_index(self) -> None:
        seed_documents = sorted(
            path
            for path in KB_SEED_DIR.iterdir()
            if path.is_file() and path.name != ".gitkeep"
        )
        self.assertGreaterEqual(len(seed_documents), 5)
        self.assertLessEqual(len(seed_documents), 10)

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage3-t6-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage3_t6") as database_url:
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
                        search_response = client.post(
                            "/knowledge/search",
                            json={
                                "query": "pricing budget approval value objection",
                                "limit": 3,
                            },
                        )

                self.assertEqual(import_response.status_code, 201)
                self.assertEqual(embed_response.status_code, 200)
                self.assertEqual(search_response.status_code, 200)

                search_payload = search_response.json()
                matches = search_payload["matches"]

                self.assertGreater(
                    len(matches),
                    0,
                    "expected vector search to return stored knowledge chunk matches",
                )
                self.assertLessEqual(
                    len(matches),
                    3,
                    "expected vector search to respect the requested result limit",
                )
                self.assertTrue(
                    any(
                        match["source_path"].endswith("objection-handling-pricing.md")
                        for match in matches
                    ),
                    "expected a pricing-focused query to return at least one pricing chunk",
                )

                with psycopg.connect(database_url.replace("+psycopg", "")) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT chunk_id FROM knowledge_chunk_vectors"
                        )
                        stored_chunk_ids = {row[0] for row in cursor.fetchall()}

                self.assertTrue(
                    stored_chunk_ids,
                    "expected pgvector-stored chunk ids to exist before search verification",
                )
                self.assertTrue(
                    all(match["chunk_id"] in stored_chunk_ids for match in matches),
                    "expected vector search to return only chunk ids that exist in the stored vector set",
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
