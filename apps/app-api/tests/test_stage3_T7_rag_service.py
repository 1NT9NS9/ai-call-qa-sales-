import importlib
import shutil
import unittest
import uuid
from unittest.mock import patch

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


CREATE_CALL_PAYLOAD = {
    "external_call_id": "ext-call-stage3-t7",
    "source_type": "api",
    "metadata": {"campaign": "stage3", "channel": "sales"},
}


class Stage3RAGServiceTests(unittest.TestCase):
    def test_rag_service_returns_matching_chunks_for_transcript_derived_query(
        self,
    ) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage3-t7-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            with temporary_postgres_database("stage3_t7") as database_url:
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
                        create_call_response = client.post("/calls", json=CREATE_CALL_PAYLOAD)
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
                                        "text": "The pricing feels expensive and our budget needs internal approval.",
                                        "start_ms": 0,
                                        "end_ms": 1000,
                                        "sequence_no": 1,
                                    },
                                    {
                                        "call_id": call_id,
                                        "speaker": "agent",
                                        "text": "We should focus on value, approval steps, and the cost of inaction.",
                                        "start_ms": 1000,
                                        "end_ms": 2000,
                                        "sequence_no": 2,
                                    },
                                ],
                            )
                            session.commit()

                        matches = app.state.rag_service.search_for_call(
                            call_id=call_id,
                            limit=3,
                        )

                self.assertGreater(
                    len(matches),
                    0,
                    "expected RAGService to return stored knowledge chunks for a transcript-derived query",
                )
                self.assertLessEqual(
                    len(matches),
                    3,
                    "expected RAGService to respect the requested result limit",
                )
                self.assertTrue(
                    any(
                        match.source_path.endswith("objection-handling-pricing.md")
                        for match in matches
                    ),
                    (
                        "expected transcript-derived retrieval to return at least one "
                        "pricing objection handling chunk"
                    ),
                )
        finally:
            clear_src_modules()
            shutil.rmtree(temp_root, ignore_errors=True)
