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
APP_API_ROOT = REPO_ROOT / "apps" / "app-api"
SECOND_VECTOR_STORE_PACKAGES = (
    "pinecone",
    "pinecone-client",
    "qdrant-client",
    "chromadb",
    "weaviate-client",
    "pymilvus",
    "faiss-cpu",
    "faiss-gpu",
    "lancedb",
    "redisvl",
)
SECOND_VECTOR_STORE_MARKERS = (
    "pinecone",
    "qdrant",
    "chromadb",
    "weaviate",
    "milvus",
    "faiss",
    "lancedb",
    "redisvl",
)


class Stage3VectorStoreConstraintTests(unittest.TestCase):
    def test_stage3_requirements_do_not_add_a_second_vector_store_dependency(
        self,
    ) -> None:
        requirements_text = (APP_API_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        ).lower()

        unexpected_packages = [
            package
            for package in SECOND_VECTOR_STORE_PACKAGES
            if package in requirements_text
        ]

        self.assertFalse(
            unexpected_packages,
            (
                "Stage 3 must stay on pgvector only; found second vector store "
                f"dependencies in requirements.txt: {unexpected_packages}"
            ),
        )

    def test_stage3_code_and_config_do_not_reference_a_second_vector_store(
        self,
    ) -> None:
        scan_paths = [
            APP_API_ROOT / "src",
            APP_API_ROOT / "alembic",
            APP_API_ROOT / "requirements.txt",
            REPO_ROOT / "docker-compose.yml",
        ]
        matches: list[str] = []

        for scan_path in scan_paths:
            candidate_paths = (
                [scan_path]
                if scan_path.is_file()
                else sorted(
                    path
                    for path in scan_path.rglob("*.py")
                    if path.is_file()
                )
            )
            for candidate_path in candidate_paths:
                text = candidate_path.read_text(encoding="utf-8").lower()
                for marker in SECOND_VECTOR_STORE_MARKERS:
                    if marker in text:
                        matches.append(
                            f"{candidate_path.relative_to(REPO_ROOT).as_posix()}: {marker}"
                        )

        self.assertFalse(
            matches,
            (
                "Stage 3 must not introduce a second vector store in code or "
                f"configuration: {matches}"
            ),
        )

    def test_stage3_postgres_flow_does_not_persist_vectors_in_fallback_storage(
        self,
    ) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage3-t5-constraint-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage3_t5_constraint") as database_url:
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

                with psycopg.connect(database_url.replace("+psycopg", "")) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT COUNT(*) FROM knowledge_chunk_vectors")
                        vector_count = cursor.fetchone()[0]
                        cursor.execute(
                            """
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = 'knowledge_chunks'
                              AND column_name = 'embedding'
                            """
                        )
                        legacy_embedding_column = cursor.fetchone()

                self.assertGreater(
                    vector_count,
                    0,
                    "expected the pgvector table to contain stored chunk vectors",
                )
                self.assertIsNone(
                    legacy_embedding_column,
                    "expected the legacy knowledge_chunks.embedding column to be absent",
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
