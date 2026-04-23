import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE_PATH = REPO_ROOT / "apps" / "app-api" / "Dockerfile"


class Stage0DockerfileTests(unittest.TestCase):
    def test_dockerfile_defines_minimal_backend_image_contract(self) -> None:
        dockerfile_text = DOCKERFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("FROM python:3.12-slim", dockerfile_text)
        self.assertIn("WORKDIR /app", dockerfile_text)
        self.assertIn(
            "COPY apps/app-api/requirements.txt /app/requirements.txt",
            dockerfile_text,
        )
        self.assertIn(
            "RUN pip install --no-cache-dir -r /app/requirements.txt",
            dockerfile_text,
        )
        self.assertIn("COPY apps/app-api/src /app/src", dockerfile_text)
        self.assertIn("COPY data/kb_seed /app/data/kb_seed", dockerfile_text)
        self.assertIn("EXPOSE 8000", dockerfile_text)
        self.assertIn(
            (
                'CMD ["uvicorn", "src.main:create_app", "--factory", '
                '"--host", "0.0.0.0", "--port", "8000"]'
            ),
            dockerfile_text,
        )
