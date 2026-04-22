import unittest
from pathlib import Path
from unittest.mock import patch

from src.config.settings import _load_dotenv_values, load_settings


REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
DOCKER_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


def load_env_example() -> dict[str, str]:
    values: dict[str, str] = {}

    for raw_line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key, value = line.split("=", 1)
        values[key] = value

    return values


class Stage0BootstrapConfigTests(unittest.TestCase):
    def test_env_example_contains_minimal_stage0_bootstrap_keys(self) -> None:
        env_values = load_env_example()

        self.assertEqual(env_values["APP_ENV"], "local")
        self.assertEqual(env_values["APP_HOST"], "127.0.0.1")
        self.assertEqual(env_values["APP_PORT"], "8000")
        self.assertEqual(env_values["POSTGRES_DB"], "app_db")
        self.assertEqual(env_values["POSTGRES_USER"], "app_user")
        self.assertEqual(env_values["POSTGRES_PASSWORD"], "app_password")
        self.assertEqual(env_values["POSTGRES_HOST"], "db")
        self.assertEqual(env_values["POSTGRES_PORT"], "5432")
        self.assertEqual(env_values["STORAGE_AUDIO_DIR"], "/app/storage/audio")
        self.assertIn("@db:5432/app_db", env_values["DATABASE_URL"])

    def test_compose_uses_stage0_environment_contract(self) -> None:
        compose_text = DOCKER_COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("app-api:", compose_text)
        self.assertIn("env_file:", compose_text)
        self.assertIn("- .env", compose_text)
        self.assertIn("POSTGRES_DB: ${POSTGRES_DB:-app_db}", compose_text)
        self.assertIn(
            "POSTGRES_USER: ${POSTGRES_USER:-app_user}",
            compose_text,
        )
        self.assertIn(
            "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-app_password}",
            compose_text,
        )

    def test_app_bootstrap_loads_stage0_settings_from_environment(
        self,
    ) -> None:
        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8010",
            "DATABASE_URL": (
                "postgresql+psycopg://"
                "app_user:app_password@db:5432/app_db"
            ),
            "STORAGE_AUDIO_DIR": "/tmp/audio",
        }

        with patch.dict("os.environ", env_values, clear=True):
            settings = load_settings()

        self.assertEqual(settings.app_env, "test")
        self.assertEqual(settings.app_host, "127.0.0.1")
        self.assertEqual(settings.app_port, 8010)
        self.assertEqual(
            settings.database_url,
            "postgresql+psycopg://app_user:app_password@db:5432/app_db",
        )
        self.assertEqual(settings.storage_audio_dir, "/tmp/audio")

    def test_app_bootstrap_loads_stage0_settings_from_repo_root_dotenv(
        self,
    ) -> None:
        dotenv_contents = "\n".join(
            (
                "APP_ENV=local",
                "APP_HOST=127.0.0.1",
                "APP_PORT=8000",
                (
                    "DATABASE_URL=postgresql+psycopg://"
                    "app_user:app_password@db:5432/app_db"
                ),
                "STORAGE_AUDIO_DIR=/app/storage/audio",
            )
        )
        dotenv_path = REPO_ROOT / "stage0.env"

        def fake_is_file(path: Path) -> bool:
            return path == dotenv_path

        def fake_read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path != dotenv_path:
                raise AssertionError(f"unexpected dotenv read: {path}")
            return dotenv_contents

        with patch("src.config.settings.DOTENV_PATH", dotenv_path), patch.dict(
            "os.environ", {}, clear=True
        ), patch(
            "pathlib.Path.is_file",
            autospec=True,
            side_effect=fake_is_file,
        ), patch(
            "pathlib.Path.read_text",
            autospec=True,
            side_effect=fake_read_text,
        ):
            settings = load_settings()

        self.assertEqual(settings.app_env, "local")
        self.assertEqual(settings.app_host, "127.0.0.1")
        self.assertEqual(settings.app_port, 8000)
        self.assertEqual(
            settings.database_url,
            "postgresql+psycopg://app_user:app_password@db:5432/app_db",
        )
        self.assertEqual(settings.storage_audio_dir, "/app/storage/audio")

    def test_app_bootstrap_does_not_search_arbitrary_parent_dotenv_files(
        self,
    ) -> None:
        dotenv_contents = "\n".join(
            (
                "APP_ENV=wrong",
                "APP_HOST=127.0.0.1",
                "APP_PORT=9999",
                (
                    "DATABASE_URL=postgresql+psycopg://"
                    "wrong:wrong@wrong:5432/wrong"
                ),
                "STORAGE_AUDIO_DIR=/wrong",
            )
        )
        explicit_dotenv_path = REPO_ROOT / "project" / "stage0.env"
        ancestor_dotenv_path = REPO_ROOT / "ancestor.env"

        def fake_is_file(path: Path) -> bool:
            return path == ancestor_dotenv_path

        def fake_read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path != ancestor_dotenv_path:
                raise AssertionError(f"unexpected dotenv read: {path}")
            return dotenv_contents

        with patch(
            "pathlib.Path.is_file",
            autospec=True,
            side_effect=fake_is_file,
        ), patch(
            "pathlib.Path.read_text",
            autospec=True,
            side_effect=fake_read_text,
        ):
            self.assertEqual(_load_dotenv_values(explicit_dotenv_path), {})
