import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
README_PATH = REPO_ROOT / "README.md"


class Stage0ReadmeTests(unittest.TestCase):
    def test_readme_documents_stage0_local_startup_flow(self) -> None:
        readme_text = README_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "Create a local `.env` file from `.env.example` before "
            "starting the stack.",
            readme_text,
        )
        self.assertIn("docker compose up --build", readme_text)
        self.assertIn("GET http://127.0.0.1:8000/health", readme_text)
