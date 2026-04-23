import importlib
import math
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


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_magnitude = math.sqrt(sum(value * value for value in left))
    right_magnitude = math.sqrt(sum(value * value for value in right))
    if left_magnitude == 0 or right_magnitude == 0:
        return 0.0

    return numerator / (left_magnitude * right_magnitude)


class Stage3KnowledgeEmbeddingTests(unittest.TestCase):
    def test_stage3_flow_generates_embeddings_for_stored_chunks(self) -> None:
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
                app = main_module.create_app()

                try:
                    with TestClient(app) as client:
                        import_response = client.post("/knowledge/import")
                finally:
                    pass

            self.assertGreaterEqual(import_response.status_code, 200)
            self.assertLess(import_response.status_code, 300)

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

            self.assertGreater(
                len(imported_chunks),
                0,
                "expected stored knowledge chunks before verifying embeddings",
            )
            self.assertTrue(
                all(row["embedding"] is None for row in imported_chunks),
                "expected /knowledge/import to stop before embedding generation",
            )

            with patch.dict("os.environ", env_values, clear=True):
                clear_src_modules()
                main_module = importlib.import_module("src.main")
                app = main_module.create_app()

                try:
                    with TestClient(app) as client:
                        embed_response = client.post("/knowledge/embed")
                finally:
                    clear_src_modules()

            self.assertEqual(embed_response.status_code, 200)

            engine.dispose()
            engine = create_engine(database_url)
            with engine.connect() as connection:
                imported_chunks = connection.execute(
                    select(persistence_models.KnowledgeChunk.__table__).order_by(
                        persistence_models.KnowledgeChunk.document_id,
                        persistence_models.KnowledgeChunk.chunk_index,
                    )
                ).mappings().all()

            self.assertGreater(
                len(imported_chunks),
                0,
                "expected stored knowledge chunks before verifying embeddings",
            )
            self.assertTrue(
                all(row["embedding"] is not None for row in imported_chunks),
                "expected stored chunks to have generated embeddings instead of null vectors",
            )
            self.assertTrue(
                all(isinstance(row["embedding"], list) for row in imported_chunks),
                "expected generated chunk embeddings to be stored as lists",
            )
            self.assertTrue(
                all(len(row["embedding"]) > 0 for row in imported_chunks),
                "expected generated chunk embeddings to be non-empty vectors",
            )

            query_embedding = app.state.embedding_service.embed(
                ["budget pricing objection and internal approval"]
            )[0]
            document_paths = {
                row["id"]: row["source_path"] for row in imported_documents
            }
            pricing_similarities = [
                _cosine_similarity(query_embedding, row["embedding"])
                for row in imported_chunks
                if document_paths[row["document_id"]].endswith(
                    "objection-handling-pricing.md"
                )
            ]
            follow_up_similarities = [
                _cosine_similarity(query_embedding, row["embedding"])
                for row in imported_chunks
                if document_paths[row["document_id"]].endswith(
                    "follow-up-email-guidelines.md"
                )
            ]

            self.assertTrue(
                pricing_similarities,
                "expected pricing knowledge chunks to exist for semantic embedding verification",
            )
            self.assertTrue(
                follow_up_similarities,
                "expected follow-up knowledge chunks to exist for semantic embedding verification",
            )
            self.assertGreater(
                max(pricing_similarities),
                max(follow_up_similarities),
                (
                    "expected the embedding path to preserve topical similarity so a "
                    "pricing query is closer to pricing chunks than unrelated follow-up chunks"
                ),
            )
        finally:
            clear_src_modules()
            if engine is not None:
                engine.dispose()
            shutil.rmtree(temp_root, ignore_errors=True)
