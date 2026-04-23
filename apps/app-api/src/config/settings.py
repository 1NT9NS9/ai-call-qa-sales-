import os
from dataclasses import dataclass
from pathlib import Path


REQUIRED_STAGE0_KEYS = (
    "APP_ENV",
    "APP_HOST",
    "APP_PORT",
    "DATABASE_URL",
    "STORAGE_AUDIO_DIR",
)

def _resolve_repo_root(settings_path: Path | None = None) -> Path:
    settings_path = settings_path or Path(__file__).resolve()
    fallback_root = settings_path.parents[2]

    for parent in settings_path.parents:
        if (parent / "docker-compose.yml").is_file():
            return parent

    return fallback_root


REPO_ROOT = _resolve_repo_root()
DOTENV_PATH = REPO_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_host: str
    app_port: int
    database_url: str
    storage_audio_dir: str
    webhook_target_url: str | None


def _load_dotenv_values(dotenv_path: Path | None = None) -> dict[str, str]:
    dotenv_path = dotenv_path or DOTENV_PATH

    if not dotenv_path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key, value = line.split("=", 1)
        values[key] = value

    return values


def _get_stage0_value(key: str, dotenv_values: dict[str, str]) -> str:
    env_value = os.getenv(key)
    if env_value is not None and env_value != "":
        return env_value

    dotenv_value = dotenv_values.get(key)
    if dotenv_value is None or dotenv_value == "":
        raise RuntimeError(f"Missing required Stage 0 setting: {key}")

    return dotenv_value


def load_settings() -> Settings:
    dotenv_values = _load_dotenv_values()

    resolved_values: dict[str, str] = {}
    for key in REQUIRED_STAGE0_KEYS:
        resolved_values[key] = _get_stage0_value(key, dotenv_values)

    return Settings(
        app_env=resolved_values["APP_ENV"],
        app_host=resolved_values["APP_HOST"],
        app_port=int(resolved_values["APP_PORT"]),
        database_url=resolved_values["DATABASE_URL"],
        storage_audio_dir=resolved_values["STORAGE_AUDIO_DIR"],
        webhook_target_url=(
            os.getenv("WEBHOOK_TARGET_URL")
            or dotenv_values.get("WEBHOOK_TARGET_URL")
            or None
        ),
    )
