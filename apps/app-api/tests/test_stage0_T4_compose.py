import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKER_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


class Stage0ComposeTests(unittest.TestCase):
    def test_compose_defines_backend_and_database_services(self) -> None:
        compose_text = DOCKER_COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("services:", compose_text)
        self.assertIn("app-api:", compose_text)
        self.assertIn("db:", compose_text)
        self.assertIn("context: .", compose_text)
        self.assertIn("dockerfile: apps/app-api/Dockerfile", compose_text)
        self.assertIn("image: pgvector/pgvector:pg16", compose_text)
        self.assertIn("depends_on:", compose_text)
        self.assertIn("db:", compose_text)
        self.assertIn("condition: service_healthy", compose_text)
        self.assertIn("healthcheck:", compose_text)
        self.assertIn("CMD-SHELL", compose_text)
        self.assertIn(
            (
                "pg_isready -U ${POSTGRES_USER:-app_user} "
                "-d ${POSTGRES_DB:-app_db}"
            ),
            compose_text,
        )

    def test_compose_uses_local_ports_and_stage0_mounts(self) -> None:
        compose_text = DOCKER_COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn('      - "127.0.0.1:8000:8000"', compose_text)
        self.assertIn('      - "127.0.0.1:5432:5432"', compose_text)
        self.assertIn("env_file:", compose_text)
        self.assertIn("      - .env", compose_text)
        self.assertIn("      - ./apps/app-api/src:/app/src", compose_text)
        self.assertIn(
            "      - ./storage/audio:/app/storage/audio",
            compose_text,
        )
        self.assertIn(
            (
                "command: uvicorn src.main:create_app "
                "--factory --host 0.0.0.0 --port 8000"
            ),
            compose_text,
        )
