import unittest
from pathlib import Path
from unittest.mock import patch

from src.adapters.embeddings import _resolve_repo_root


class Stage3EmbeddingAdapterTests(unittest.TestCase):
    def test_resolve_repo_root_falls_back_safely_for_container_paths(self) -> None:
        adapter_path = Path("/app/src/adapters/embeddings.py")

        with patch(
            "pathlib.Path.is_file",
            autospec=True,
            return_value=False,
        ), patch(
            "pathlib.Path.is_dir",
            autospec=True,
            return_value=False,
        ):
            repo_root = _resolve_repo_root(adapter_path)

        self.assertEqual(repo_root, Path("/app"))
