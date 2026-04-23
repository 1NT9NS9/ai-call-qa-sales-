import importlib
import shutil
import unittest
import uuid
from pathlib import Path
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
from sqlalchemy import create_engine, select, text


REPO_ROOT = Path(__file__).resolve().parents[3]
KB_SEED_DIR = REPO_ROOT / "data" / "kb_seed"


class Stage3KnowledgeEmbeddingTests(unittest.TestCase):
    def test_stage3_flow_generates_embeddings_for_imported_chunk_texts(self) -> None:
        seed_documents = sorted(
            path
            for path in KB_SEED_DIR.iterdir()
            if path.is_file() and path.name != ".gitkeep"
        )
        self.assertGreaterEqual(len(seed_documents), 5)
        self.assertLessEqual(len(seed_documents), 10)

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        temp_root = TEST_TMP_ROOT / f"stage3-t4-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=True)
        engine = None

        try:
            with temporary_postgres_database("stage3_t4") as database_url:
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
                    self.assertEqual(import_response.status_code, 201)

                    engine = create_engine(database_url)
                    with engine.connect() as connection:
                        imported_chunks = connection.execute(
                            select(persistence_models.KnowledgeChunk.__table__).order_by(
                                persistence_models.KnowledgeChunk.document_id,
                                persistence_models.KnowledgeChunk.chunk_index,
                            )
                        ).mappings().all()
                        stored_vector_count_before_embed = connection.execute(
                            text("SELECT COUNT(*) FROM knowledge_chunk_vectors")
                        ).scalar_one()

                    self.assertGreater(
                        len(imported_chunks),
                        0,
                        "expected stored knowledge chunks before verifying embedding generation",
                    )
                    self.assertEqual(
                        stored_vector_count_before_embed,
                        0,
                        "expected /knowledge/import to stop before vector persistence begins",
                    )

                with patch.dict("os.environ", env_values, clear=True):
                    clear_src_modules()
                    main_module = importlib.import_module("src.main")
                    app = main_module.create_app()

                    with TestClient(app) as client:
                        embed_response = client.post("/knowledge/embed")

                self.assertEqual(embed_response.status_code, 200)
                self.assertEqual(
                    embed_response.json()["embedded_count"],
                    len(imported_chunks),
                    "expected /knowledge/embed to process every stored chunk",
                )
                engine.dispose()
                engine = create_engine(database_url)
                with engine.connect() as connection:
                    stored_vector_count_after_embed = connection.execute(
                        text("SELECT COUNT(*) FROM knowledge_chunk_vectors")
                    ).scalar_one()

                self.assertGreater(
                    stored_vector_count_after_embed,
                    0,
                    "expected /knowledge/embed to persist stored vectors for imported chunks",
                )
                self.assertEqual(
                    stored_vector_count_after_embed,
                    len(imported_chunks),
                    "expected /knowledge/embed to persist one stored vector per imported chunk",
                )
        finally:
            clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
