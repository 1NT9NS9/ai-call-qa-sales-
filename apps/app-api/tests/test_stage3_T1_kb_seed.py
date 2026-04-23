import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
KB_SEED_DIR = REPO_ROOT / "data" / "kb_seed"


class Stage3KnowledgeBaseSeedTests(unittest.TestCase):
    def test_kb_seed_contains_small_stage3_test_corpus(self) -> None:
        self.assertTrue(KB_SEED_DIR.exists())

        documents = sorted(
            path
            for path in KB_SEED_DIR.iterdir()
            if path.is_file() and path.name != ".gitkeep"
        )

        self.assertGreaterEqual(
            len(documents),
            5,
            f"expected 5-10 seed documents in {KB_SEED_DIR}, found {len(documents)}",
        )
        self.assertLessEqual(
            len(documents),
            10,
            f"expected 5-10 seed documents in {KB_SEED_DIR}, found {len(documents)}",
        )
