import unittest
from pathlib import Path


APP_API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_ROOT = APP_API_ROOT / "alembic"
VERSIONS_ROOT = ALEMBIC_ROOT / "versions"
REQUIRED_STAGE1_TABLES = {
    "call_sessions",
    "transcript_segments",
    "knowledge_documents",
    "knowledge_chunks",
    "call_analyses",
    "delivery_events",
}


def _migration_files() -> list[Path]:
    return sorted(
        path
        for path in VERSIONS_ROOT.glob("*.py")
        if path.name != "__init__.py"
    )


class Stage1MigrationTests(unittest.TestCase):
    def test_stage1_migration_files_exist(self) -> None:
        migration_files = _migration_files()

        self.assertTrue(
            migration_files,
            "Stage 1 requires Alembic revision files under apps/app-api/alembic/versions.",
        )

    def test_stage1_migrations_cover_all_persistence_tables(self) -> None:
        migration_files = _migration_files()

        self.assertTrue(
            migration_files,
            "Cannot validate Stage 1 migration coverage because no Alembic revision files exist.",
        )

        combined_text = "\n".join(
            path.read_text(encoding="utf-8") for path in migration_files
        )

        missing_tables = sorted(
            table_name
            for table_name in REQUIRED_STAGE1_TABLES
            if table_name not in combined_text
        )

        self.assertFalse(
            missing_tables,
            (
                "Stage 1 migrations do not cover all required persistence tables: "
                f"{missing_tables}"
            ),
        )
