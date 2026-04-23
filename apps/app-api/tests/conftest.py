import os
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg


APP_API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_API_ROOT.parents[1]
ALEMBIC_INI_PATH = APP_API_ROOT / "alembic.ini"
SRC_ROOT = APP_API_ROOT / "src"
TEST_TMP_ROOT = APP_API_ROOT / "test-tmp-runs"
MINIMAL_ENV_VALUES = {
    "APP_ENV": "test",
    "APP_HOST": "127.0.0.1",
    "APP_PORT": "8000",
    "DATABASE_URL": "postgresql+psycopg://app_user:app_password@db:5432/app_db",
    "STORAGE_AUDIO_DIR": "/tmp/audio",
}

if str(APP_API_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_API_ROOT))


def clear_src_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key, value = line.split("=", 1)
        values[key] = value

    return values


def _postgres_connection_settings() -> tuple[str, str, str, int, list[str]]:
    dotenv_values = {}
    dotenv_path = REPO_ROOT / ".env"
    if dotenv_path.is_file():
        dotenv_values = load_env_file(dotenv_path)

    database = os.getenv("POSTGRES_DB") or dotenv_values.get("POSTGRES_DB") or "app_db"
    user = os.getenv("POSTGRES_USER") or dotenv_values.get("POSTGRES_USER") or "app_user"
    password = (
        os.getenv("POSTGRES_PASSWORD")
        or dotenv_values.get("POSTGRES_PASSWORD")
        or "app_password"
    )
    port = int(
        os.getenv("POSTGRES_PORT") or dotenv_values.get("POSTGRES_PORT") or "5432"
    )
    configured_host = os.getenv("POSTGRES_HOST") or dotenv_values.get("POSTGRES_HOST")
    host_candidates = [
        host
        for host in (
            configured_host,
            "127.0.0.1",
            "localhost",
            "db",
        )
        if host
    ]
    unique_hosts: list[str] = []
    for host in host_candidates:
        if host not in unique_hosts:
            unique_hosts.append(host)

    return database, user, password, port, unique_hosts


def _resolve_postgres_host() -> tuple[str, str, str, int]:
    _, user, password, port, host_candidates = _postgres_connection_settings()

    last_error: Exception | None = None
    for host in host_candidates:
        try:
            with psycopg.connect(
                f"postgresql://{user}:{password}@{host}:{port}/postgres",
                connect_timeout=3,
            ):
                return host, user, password, port
        except Exception as exc:  # pragma: no cover - exercised only when host probing fails
            last_error = exc

    raise RuntimeError(
        "Could not connect to a local Postgres test server."
    ) from last_error


@contextmanager
def temporary_postgres_database(prefix: str):
    host, user, password, port = _resolve_postgres_host()
    database_name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"postgresql://{user}:{password}@{host}:{port}/postgres"
    sqlalchemy_url = (
        f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database_name}"
    )

    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {database_name}")

    try:
        yield sqlalchemy_url
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity WHERE datname = %s",
                    (database_name,),
                )
                cursor.execute(f"DROP DATABASE IF EXISTS {database_name}")
