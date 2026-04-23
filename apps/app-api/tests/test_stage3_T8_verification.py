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
from sqlalchemy import insert


REPO_ROOT = Path(__file__).resolve().parents[3]
KB_SEED_DIR = REPO_ROOT / "data" / "kb_seed"
CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage3-t8",
    "source_type": "api",
    "metadata": {"campaign": "stage3", "channel": "sales"},
}


class Stage3BoundedVerificationTests(unittest.TestCase):
    def test_stage3_happy_path_is_stable_for_pgvector_backed_retrieval(self) -> None:
        seed_documents = sorted(
            path
            for path in KB_SEED_DIR.iterdir()
            if path.is_file() and path.name != ".gitkeep"
        )
        self.assertGreaterEqual(len(seed_documents), 5)
        self.assertLessEqual(len(seed_documents), 10)

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage3-t8-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage3_t8") as database_url:
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
                    persistence_models = importlib.import_module(
                        "src.infrastructure.persistence.models"
                    )
                    app = main_module.create_app()

                    with TestClient(app) as client:
                        import_response = client.post("/knowledge/import")
                        embed_response = client.post("/knowledge/embed")
                        create_call_response = client.post(
                            "/calls",
                            json=CREATE_CALL_PAYLOAD,
                        )
                        self.assertEqual(import_response.status_code, 201)
                        self.assertEqual(embed_response.status_code, 200)
                        self.assertEqual(create_call_response.status_code, 201)

                        call_id = create_call_response.json()["id"]
                        with app.state.session_factory() as session:
                            session.execute(
                                insert(persistence_models.TranscriptSegment),
                                [
                                    {
                                        "call_id": call_id,
                                        "speaker": "customer",
                                        "text": "The pricing feels expensive and our budget approval is slow.",
                                        "start_ms": 0,
                                        "end_ms": 1000,
                                        "sequence_no": 1,
                                    },
                                    {
                                        "call_id": call_id,
                                        "speaker": "agent",
                                        "text": "We should address value, approval steps, and the cost of inaction.",
                                        "start_ms": 1000,
                                        "end_ms": 2000,
                                        "sequence_no": 2,
                                    },
                                ],
                            )
                            session.commit()

                        import_payload = import_response.json()
                        embed_payload = embed_response.json()
                        first_matches = app.state.rag_service.search_for_call(
                            call_id=call_id,
                            limit=3,
                        )
                        second_matches = app.state.rag_service.search_for_call(
                            call_id=call_id,
                            limit=3,
                        )

                self.assertGreaterEqual(import_payload["imported_count"], 5)
                self.assertLessEqual(import_payload["imported_count"], 10)
                self.assertGreater(
                    import_payload["chunk_count"],
                    0,
                    "expected imported knowledge documents to produce stored chunks",
                )
                self.assertEqual(
                    embed_payload["embedded_count"],
                    import_payload["chunk_count"],
                    "expected the embedding step to persist vectors for every stored chunk",
                )
                self.assertTrue(
                    first_matches,
                    "expected the retrieval happy path to return stored knowledge chunks",
                )
                self.assertLessEqual(
                    len(first_matches),
                    3,
                    "expected the retrieval flow to respect the requested result limit",
                )
                self.assertEqual(
                    [match.chunk_id for match in first_matches],
                    [match.chunk_id for match in second_matches],
                    "expected repeated happy-path retrieval calls to return a stable chunk ordering",
                )
                self.assertTrue(
                    first_matches[0].source_path.endswith(
                        "objection-handling-pricing.md"
                    ),
                    (
                        "expected the transcript-derived pricing retrieval to retrieve a "
                        "pricing knowledge chunk first"
                    ),
                )

                with psycopg.connect(database_url.replace("+psycopg", "")) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT COUNT(*) FROM knowledge_chunks")
                        chunk_count = cursor.fetchone()[0]
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
                        cursor.execute(
                            "SELECT chunk_id FROM knowledge_chunk_vectors ORDER BY chunk_id"
                        )
                        stored_chunk_ids = {row[0] for row in cursor.fetchall()}

                self.assertEqual(
                    vector_count,
                    chunk_count,
                    "expected the bounded verification run to store vectors for every chunk",
                )
                self.assertGreater(
                    vector_count,
                    0,
                    "expected pgvector-backed chunk vectors to exist during bounded verification",
                )
                self.assertIsNone(
                    legacy_embedding_column,
                    "expected the bounded verification run to use pgvector only",
                )
                self.assertTrue(
                    all(match.chunk_id in stored_chunk_ids for match in first_matches),
                    "expected RAGService retrieval to return only chunk ids stored in pgvector",
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
