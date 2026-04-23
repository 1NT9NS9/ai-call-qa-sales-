import importlib
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class HealthEndpointTests(unittest.TestCase):
    def test_health_returns_ok_status(self) -> None:
        env_values = {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": "8000",
            "DATABASE_URL": (
                "postgresql+psycopg://"
                "app_user:app_password@db:5432/app_db"
            ),
            "STORAGE_AUDIO_DIR": "/tmp/audio",
        }

        try:
            with patch.dict("os.environ", env_values, clear=True):
                sys.modules.pop("src.main", None)
                main_module = importlib.import_module("src.main")

                with TestClient(main_module.create_app()) as client:
                    response = client.get("/health")
        finally:
            sys.modules.pop("src.main", None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
