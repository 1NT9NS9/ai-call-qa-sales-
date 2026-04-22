import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.inspection import inspect as sqlalchemy_inspect


APP_API_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = APP_API_ROOT / "src"
REQUIRED_KNOWLEDGECHUNK_COLUMNS = {
    "id",
    "document_id",
    "chunk_text",
    "embedding",
    "chunk_index",
}
MINIMAL_ENV_VALUES = {
    "APP_ENV": "test",
    "APP_HOST": "127.0.0.1",
    "APP_PORT": "8000",
    "DATABASE_URL": "postgresql+psycopg://app_user:app_password@db:5432/app_db",
    "STORAGE_AUDIO_DIR": "/tmp/audio",
}


def _candidate_module_names() -> list[str]:
    module_names: list[str] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue

        module_text = path.read_text(encoding="utf-8")
        if (
            "KnowledgeDocument" not in module_text
            and "KnowledgeChunk" not in module_text
        ):
            continue

        module_name = ".".join(path.relative_to(APP_API_ROOT).with_suffix("").parts)
        module_names.append(module_name)

    return module_names


class Stage1KnowledgeModelTests(unittest.TestCase):
    def _load_mapped_class(self, class_name: str):
        candidate_class_found = False

        with patch.dict("os.environ", MINIMAL_ENV_VALUES, clear=True):
            for module_name in _candidate_module_names():
                sys.modules.pop(module_name, None)
                module = importlib.import_module(module_name)
                candidate = getattr(module, class_name, None)

                if candidate is None:
                    continue

                candidate_class_found = True

                try:
                    mapper = sqlalchemy_inspect(candidate)
                except NoInspectionAvailable:
                    continue

                return candidate, mapper

        if candidate_class_found:
            self.fail(
                f"Found a {class_name} class, but it is not mapped as a "
                "SQLAlchemy persistence model."
            )

        self.fail(
            f"No {class_name} persistence model was found under apps/app-api/src."
        )

    def test_knowledgedocument_exists_in_persistence_layer(self) -> None:
        _, mapper = self._load_mapped_class("KnowledgeDocument")

        self.assertGreater(
            len(mapper.columns),
            0,
            "KnowledgeDocument should expose at least one persisted column.",
        )

    def test_knowledgechunk_model_contains_required_stage1_columns(self) -> None:
        _, mapper = self._load_mapped_class("KnowledgeChunk")

        column_names = {column.name for column in mapper.columns}

        self.assertTrue(
            REQUIRED_KNOWLEDGECHUNK_COLUMNS.issubset(column_names),
            (
                "KnowledgeChunk is missing one or more required persisted "
                f"fields: {sorted(REQUIRED_KNOWLEDGECHUNK_COLUMNS - column_names)}"
            ),
        )

    def test_knowledgechunk_document_id_links_to_knowledgedocument(self) -> None:
        knowledge_document_model, _ = self._load_mapped_class("KnowledgeDocument")
        knowledge_chunk_model, mapper = self._load_mapped_class("KnowledgeChunk")

        self.assertIn("document_id", mapper.columns)

        document_id_column = knowledge_chunk_model.__table__.columns["document_id"]
        foreign_keys = list(document_id_column.foreign_keys)

        self.assertTrue(
            foreign_keys,
            "KnowledgeChunk.document_id is expected to have a foreign key to KnowledgeDocument.",
        )
        self.assertEqual(len(foreign_keys), 1)
        self.assertIs(
            next(iter(foreign_keys)).column.table,
            knowledge_document_model.__table__,
        )
