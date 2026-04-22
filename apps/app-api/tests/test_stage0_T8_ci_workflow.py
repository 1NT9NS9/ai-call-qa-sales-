import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


class Stage0CiWorkflowTests(unittest.TestCase):
    def test_ci_workflow_runs_stage0_smoke_checks(self) -> None:
        workflow_text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("Prepare Stage 0 environment", workflow_text)
        self.assertIn("cp .env.example .env", workflow_text)
        self.assertIn("docker compose config", workflow_text)
        self.assertIn("set -euxo pipefail", workflow_text)
        self.assertIn("docker compose up --build -d", workflow_text)
        self.assertIn("for attempt in $(seq 1 30); do", workflow_text)
        self.assertIn(
            (
                "curl -fsS http://127.0.0.1:8000/health | "
                "grep -qx '{\"status\":\"ok\"}'"
            ),
            workflow_text,
        )
        self.assertIn(
            (
                "docker compose exec -T app-api sh -lc "
                '"test -d /app/storage/audio"'
            ),
            workflow_text,
        )
        self.assertIn(
            (
                "docker compose exec -T db sh -lc "
                '"psql -U \\"\\$POSTGRES_USER\\" -d '
                '\\"\\$POSTGRES_DB\\" -tAc \\"SELECT extname FROM '
                'pg_extension WHERE extname = \'vector\'\\" | grep -qx '
                'vector"'
            ),
            workflow_text,
        )
        self.assertIn("Dump Compose state on failure", workflow_text)
        self.assertIn("docker compose ps", workflow_text)
        self.assertIn("docker compose logs --no-color", workflow_text)
        self.assertIn("if: always()", workflow_text)
        self.assertIn("docker compose down -v", workflow_text)
