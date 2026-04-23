import unittest
from pathlib import Path

from conftest import load_env_file


REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
DOCKER_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
STORAGE_AUDIO_PATH = REPO_ROOT / "storage" / "audio"


class Stage0AudioStorageTests(unittest.TestCase):
    def test_audio_storage_directory_exists_in_repo(self) -> None:
        self.assertTrue(STORAGE_AUDIO_PATH.is_dir())
        self.assertTrue((STORAGE_AUDIO_PATH / ".gitkeep").is_file())

    def test_compose_mount_matches_configured_audio_storage_path(
        self,
    ) -> None:
        env_values = load_env_file(ENV_EXAMPLE_PATH)
        compose_text = DOCKER_COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertEqual(env_values["STORAGE_AUDIO_DIR"], "/app/storage/audio")
        self.assertIn(
            "      - ./storage/audio:/app/storage/audio",
            compose_text,
        )
