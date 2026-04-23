import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKER_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


class Stage0PgvectorBootstrapTests(unittest.TestCase):
    def test_compose_defines_explicit_pgvector_bootstrap_step(self) -> None:
        compose_text = DOCKER_COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("db-bootstrap:", compose_text)
        self.assertIn(
            'condition: service_completed_successfully',
            compose_text,
        )
        self.assertIn('restart: "no"', compose_text)
        self.assertIn(
            (
                'psql -h db -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" '
                '-v ON_ERROR_STOP=1 -c '
                '"CREATE EXTENSION IF NOT EXISTS vector"'
            ),
            compose_text,
        )
        self.assertIn(
            (
                'psql -h db -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" '
                '-tAc "SELECT extname FROM pg_extension '
                "WHERE extname = 'vector'\" | grep -qx vector"
            ),
            compose_text,
        )
