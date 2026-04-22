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

REPO_ROOT = Path(__file__).resolve().parents[4]
DOTENV_PATH = REPO_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_host: str
    app_port: int
    database_url: str
    storage_audio_dir: str


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
    value = os.getenv(key, dotenv_values.get(key))
    if value in (None, ""):
        raise RuntimeError(f"Missing required Stage 0 setting: {key}")

    return value


def load_settings() -> Settings:
    dotenv_values = _load_dotenv_values()

    resolved_values = {
        key: _get_stage0_value(key, dotenv_values) for key in REQUIRED_STAGE0_KEYS
    }

    return Settings(
        app_env=resolved_values["APP_ENV"],
        app_host=resolved_values["APP_HOST"],
        app_port=int(resolved_values["APP_PORT"]),
        database_url=resolved_values["DATABASE_URL"],
        storage_audio_dir=resolved_values["STORAGE_AUDIO_DIR"],
    )
