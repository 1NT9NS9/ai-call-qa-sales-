import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"


class Stage3KnowledgeBaseDockerInputTests(unittest.TestCase):
    def test_dockerignore_allows_markdown_seed_documents_for_stage3_import(self) -> None:
        dockerignore_text = DOCKERIGNORE_PATH.read_text(encoding="utf-8")

        self.assertIn("data/kb_seed/*", dockerignore_text)
        self.assertIn("!data/kb_seed/.gitkeep", dockerignore_text)
        self.assertIn("!data/kb_seed/*.md", dockerignore_text)
